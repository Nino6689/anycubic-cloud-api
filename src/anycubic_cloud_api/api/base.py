from __future__ import annotations

import asyncio
import json
import time
from typing import Any, overload

import aiohttp
from aiofiles import open as aio_file_open
from aiofiles.os import path as aio_path

from ..const.api_endpoints import API_ENDPOINT
from ..const.const import (
    ACCESS_TOKEN_LOGIN_RETRIES,
    ACCESS_TOKEN_LOGIN_RETRY_INTERVAL,
    ACCESS_TOKEN_RATE_LIMIT_MARKERS,
    ACCESS_TOKEN_RATE_LIMIT_RETRIES,
    ACCESS_TOKEN_RATE_LIMIT_WAIT,
    DEFAULT_USER_AGENT,
    MAX_API_FETCH_TIME_WARN,
    WARN_INTERVAL_API_DURATION,
)
from ..const.regions import (
    REGIONS,
    AnycubicEndpoints,
    AnycubicRegion,
    resolve_region,
)
from ..exceptions.error_strings import (
    ErrorsAPIParsing,
    ErrorsAuth,
    ErrorsAuthTokenExpired,
)
from ..exceptions.exceptions import (
    AnycubicAPIParsingError,
    AnycubicAuthError,
    AnycubicAuthTokensExpired,
    AnycubicRateLimitError,
)
from ..models.auth import AnycubicAuthentication, AnycubicAuthMode
from ..models.http import HTTP_METHODS, AnycubicAPIEndpoint


# `with_origin` has to distinguish three states: "the region's auth domain"
# (the default), "this specific origin", and "send no Origin at all" (None).
# A default argument is bound once at import, so it cannot follow per-instance
# region -- and None is already taken. Hence a sentinel: it means "unset", and
# is resolved against the instance at the single point of use.
USE_REGION_ORIGIN: str = "__region_default__"


class AnycubicAPIBase:
    __slots__ = (
        "_cached_web_auth_token_path",
        "_base_url",
        "_endpoints",
        "_public_api_root",
        "_session",
        "_sessionjar",
        "_debug_logger",
        "_tokens_changed",
        "_log_api_call_info",
        "_last_warn_api_duration",
        "_anycubic_auth",
        "_lan_client",
    )

    def __init__(
        self,
        session: aiohttp.ClientSession,
        cookie_jar: aiohttp.CookieJar,
        debug_logger: Any = None,
        auth_token: str | None = None,
        auth_mode: AnycubicAuthMode | None = None,
        device_id: str | None = None,
        region: AnycubicRegion | str | None = None,
    ) -> None:
        # Cache
        self._cached_web_auth_token_path: str | None = None
        # API
        # Resolved once, here, and never changed: see AnycubicEndpoints.
        self._endpoints: AnycubicEndpoints = REGIONS[resolve_region(region)]
        self._base_url: str = self._endpoints.base_url
        self._public_api_root: str = self._endpoints.public_api_root
        # Internal
        self._session: aiohttp.ClientSession = session
        self._sessionjar: aiohttp.CookieJar = cookie_jar
        self._debug_logger: Any = debug_logger
        self._tokens_changed: bool = False
        self._log_api_call_info: bool = False
        self._last_warn_api_duration: int | None = None
        self._anycubic_auth: AnycubicAuthentication | None = None
        self._lan_client: Any = None

        if auth_token:
            self.set_authentication(
                auth_token=auth_token,
                auth_mode=auth_mode,
                device_id=device_id,
            )

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def endpoints(self) -> AnycubicEndpoints:
        """Every address this instance talks to, fixed at construction.

        There is deliberately no setter. Changing region on a live object
        would leave the cookie jar, the MQTT client id and any in-flight
        session pointed at the previous deployment, and connect_mqtt runs in
        an executor thread reconnecting on its own -- so the result would be
        one client talking to two clouds. Changing region means rebuilding
        the entry.
        """
        return self._endpoints

    def set_lan_client(self, lan_client: Any) -> None:
        """Attach, or with None detach, the printer's local connection.

        Held here because orders are sent from here. A printer answering
        locally has left the cloud behind -- LAN Mode drops its cloud
        connection, and the cloud stops listing it at all -- so once this is
        set, orders that have a local form stop going out over the internet.
        """
        self._lan_client = lan_client

    @property
    def lan_client(self) -> Any:
        return self._lan_client

    @property
    def lan_is_connected(self) -> bool:
        return self._lan_client is not None and bool(self._lan_client.is_connected)

    def set_log_api_call_info(
        self,
        val: bool,
    ) -> None:
        self._log_api_call_info = bool(val)

    @property
    def anycubic_auth(self) -> AnycubicAuthentication:
        if self._anycubic_auth is None:
            raise AnycubicAuthError(ErrorsAuth.missing_auth)
        return self._anycubic_auth

    @property
    def tokens_changed(self) -> bool:
        return self._tokens_changed

    def _log_to_debug(self, msg: str) -> None:
        if self._debug_logger:
            self._debug_logger.debug(msg)

    def _log_to_warn(self, msg: str) -> None:
        if self._debug_logger:
            self._debug_logger.warning(msg)

    def _log_to_error(self, msg: str) -> None:
        if self._debug_logger:
            self._debug_logger.error(msg)

    #
    #
    # API Functions
    # ------------------------------------------

    def _web_headers(self, with_origin: str | None = USE_REGION_ORIGIN) -> dict[str, Any]:
        # The sentinel means the caller expressed no preference, so fall back
        # to this instance's auth domain. `_fetch_ext_resp` and
        # `_fetch_api_resp` only pass the value straight through to here, so
        # resolving once at this single point covers all five signatures.
        #
        # `is` rather than `==`: None is a meaningful value here (send no
        # Origin at all) and a truthiness test would swallow it.
        if with_origin is USE_REGION_ORIGIN:
            with_origin = self._endpoints.auth_domain

        header_dict = {}
        if self.anycubic_auth.requires_user_agent:
            header_dict['User-Agent'] = DEFAULT_USER_AGENT

            if with_origin:
                header_dict['Origin'] = f'https://{with_origin}'

        return header_dict

    def _build_api_url(self, endpoint: AnycubicAPIEndpoint) -> str:
        return f"{self._public_api_root}{endpoint.endpoint}"

    @overload
    async def _fetch_ext_resp(
        self,
        method: HTTP_METHODS,
        base_url: str,
        query: dict[str, Any] | None = None,
        params: dict[str, Any] = {},
        extra_headers: dict[str, Any] = {},
        with_origin: str | None = USE_REGION_ORIGIN,
        put_data: bytes | None = None,
    ) -> dict[Any, Any]: ...

    @overload
    async def _fetch_ext_resp(
        self,
        method: HTTP_METHODS,
        base_url: str,
        query: dict[str, Any] | None = None,
        params: dict[str, Any] = {},
        extra_headers: dict[str, Any] = {},
        with_origin: str | None = USE_REGION_ORIGIN,
        put_data: bytes | None = None,
        is_json: bool = True,
        return_url: bool = False,
    ) -> dict[Any, Any] | str: ...

    async def _fetch_ext_resp(
        self,
        method: HTTP_METHODS,
        base_url: str,
        query: dict[str, Any] | None = None,
        params: dict[str, Any] | list[Any] | str | None = {},
        extra_headers: dict[str, Any] = {},
        with_origin: str | None = USE_REGION_ORIGIN,
        put_data: bytes | None = None,
        is_json: bool = True,
        return_url: bool = False,
    ) -> dict[Any, Any] | str:
        url = base_url
        time_start: float = time.time()
        headers = {**self._web_headers(with_origin=with_origin), **extra_headers}
        if method == HTTP_METHODS.POST:
            if params is not None and (isinstance(params, dict) or isinstance(params, list)):
                data = json.dumps(params)
            elif params is not None:
                data = str(params)
            else:
                data = None
            h_coro = self._session.post(url, params=query, data=data, headers=headers)
        elif method == HTTP_METHODS.PUT:
            h_coro = self._session.put(url, params=query, data=put_data, headers=headers)
        else:
            h_coro = self._session.get(url, params=query, headers=headers)

        response_url = None

        try:
            async with h_coro as resp:
                if is_json:
                    resp_data: dict[str, Any] | str = await resp.json()
                else:
                    resp_data = await resp.text()

                response_url = resp.url
        except Exception:
            raise AnycubicAPIParsingError(ErrorsAPIParsing.api_error_server_maintenance)

        time_end: float = time.time()
        time_diff: float = time_end - time_start
        over_limit: bool = int(time_diff) > MAX_API_FETCH_TIME_WARN
        if (
            over_limit
            and (
                not self._last_warn_api_duration
                or time_end > self._last_warn_api_duration + WARN_INTERVAL_API_DURATION
            )
        ):
            self._log_to_warn(
                f"Responses from server are taking over {MAX_API_FETCH_TIME_WARN}s (Took {int(time_diff)}s)"
            )
        if self._log_api_call_info:
            self._log_to_debug(
                f"Finished fetching {url} in {time_diff:.2f}s."
            )

        if return_url:
            return str(response_url)
        return resp_data

    async def _fetch_aws_put_resp(self, final_url: str, put_data: bytes) -> dict[Any, Any] | str:
        resp = await self._fetch_ext_resp(
            method=HTTP_METHODS.PUT,
            base_url=final_url,
            is_json=False,
            put_data=put_data,
        )

        if isinstance(resp, str) and len(resp) > 0:
            raise AnycubicAPIParsingError(ErrorsAPIParsing.api_error_aws.format(resp))

        return resp

    async def _fetch_api_resp(
        self,
        endpoint: AnycubicAPIEndpoint,
        query: dict[str, Any] | None = None,
        params: dict[str, Any] = {},
        extra_headers: dict[str, Any] = {},
        with_origin: str | None = USE_REGION_ORIGIN,
        with_token: bool = True,
    ) -> dict[Any, Any]:
        resp = await self._fetch_ext_resp(
            method=endpoint.method,
            base_url=self._build_api_url(endpoint),
            query=query,
            params=params,
            extra_headers=self.anycubic_auth.get_auth_headers(
                with_token=with_token
            ),
            with_origin=with_origin,
        )
        return resp

    #
    #
    # Login Functions
    # ------------------------------------------

    def set_authentication(
        self,
        auth_token: str | None,
        auth_mode: AnycubicAuthMode | int | None = None,
        device_id: str | None = None,
        auth_access_token: str | None = None,
        auto_pick_token: bool = True,
    ) -> None:
        if not auth_token and not auth_access_token:
            raise AnycubicAuthError(ErrorsAuth.set_auth_missing_token)

        if isinstance(auth_mode, int):
            auth_mode = AnycubicAuthMode(auth_mode)

        if (
            auto_pick_token and (
                not auth_access_token
                and auth_mode == AnycubicAuthMode.SLICER
            )
        ):
            auth_access_token = f"{auth_token}"
            auth_token = None

        self._anycubic_auth = AnycubicAuthentication(
            auth_token=auth_token,
            auth_mode=auth_mode,
            device_id=device_id,
            auth_access_token=auth_access_token,
        )

    async def _get_user_token_with_access_token_with_retry(self) -> None:
        retries = ACCESS_TOKEN_LOGIN_RETRIES
        rate_limit_waits = ACCESS_TOKEN_RATE_LIMIT_RETRIES
        x = 0
        while True:
            try:
                await self._get_user_token_with_access_token()
                return
            except AnycubicRateLimitError:
                # Not a refusal: wait out the cooldown. If it persists the
                # error propagates as transient, never as an auth failure, so
                # it can neither trigger the web fallback nor a re-auth.
                if rate_limit_waits <= 0:
                    raise
                rate_limit_waits -= 1
                await asyncio.sleep(ACCESS_TOKEN_RATE_LIMIT_WAIT)
            except AnycubicAuthError:
                x += 1
                if x < retries:
                    await asyncio.sleep(ACCESS_TOKEN_LOGIN_RETRY_INTERVAL)
                else:
                    raise

    async def _get_user_token_with_access_token(self) -> None:
        params = self.anycubic_auth.auth_access_token_payload
        resp = await self._fetch_api_resp(
            endpoint=API_ENDPOINT.auth_sig_token,
            query=None,
            params=params,
            with_token=False,
        )
        if not resp or not resp['data']:
            server_message = resp.get('msg') if resp else None
            if server_message and any(
                marker in str(server_message) for marker in ACCESS_TOKEN_RATE_LIMIT_MARKERS
            ):
                error_message = ErrorsAuth.access_token_rate_limited.format(server_message)
                self._log_to_debug(error_message)
                raise AnycubicRateLimitError(error_message)
            error_message = ErrorsAuth.access_token_login_failed.format(server_message)
            self._log_to_debug(error_message)
            raise AnycubicAuthError(error_message)
        self.anycubic_auth.set_auth_token(
            resp['data']['token']
        )
        self._log_to_debug("Logged in and retrieved user token with access_token.")

    def get_auth_config_dict(self) -> dict[str, Any]:
        self._tokens_changed = False

        return self.anycubic_auth.get_auth_config_dict()

    def load_auth_config_from_dict(
        self,
        data: dict[str, Any],
        minimal: bool = False,
    ) -> None:
        self.anycubic_auth.load_auth_config_from_dict(
            data,
            minimal=minimal,
        )
        self._log_to_debug("Loaded auth tokens from dict.")

    async def _load_cached_web_auth_token(self) -> None:
        if (
            self._cached_web_auth_token_path is not None
            and (await aio_path.exists(self._cached_web_auth_token_path))
        ):

            try:
                async with aio_file_open(self._cached_web_auth_token_path, mode='r') as wo:
                    token = await wo.read()
                self.set_authentication(
                    auth_token=token,
                )

            except Exception:
                pass

    async def _check_can_access_api(
        self,
    ) -> bool:
        await self._load_cached_web_auth_token()
        if self.anycubic_auth.requires_access_token:
            try:
                await self._get_user_token_with_access_token_with_retry()
            except AnycubicAuthError:
                # A web token is a JWT too, so one can be mistaken for a slicer
                # token and sent to a login endpoint that will never accept it.
                # Try it as a plain user token before declaring the credentials
                # bad -- they may be perfectly good.
                if self.anycubic_auth.retry_access_token_as_user_token():
                    self._log_to_debug(
                        "Access token login failed; retrying it as a web token."
                    )
                    self._tokens_changed = True
                else:
                    return False
        try:
            await self.get_user_info()
            return True
        except AnycubicAuthTokensExpired:
            # Not an expiry check -- this is raised when the server answers
            # without a user object at all. Saying "expired" sends whoever
            # reads the debug log off inspecting the token's exp claim, which
            # is exactly the wrong place to look.
            self._log_to_debug(
                "Server returned no user for these credentials "
                "(rejected or not recognised)."
            )
            return False

    async def check_api_tokens(self) -> bool:
        if not await self._check_can_access_api():
            if self.anycubic_auth.clear_cached_access_user_token():
                self._tokens_changed = True
                self._log_to_debug("Cleared cached user token.")
                return await self._check_can_access_api()
            return False

        return True

    async def get_user_info(
        self,
        raw_data: bool = False,
    ) -> dict[str, Any]:
        resp = await self._fetch_api_resp(endpoint=API_ENDPOINT.user_info)
        if raw_data:
            return resp

        data: dict[str, Any] | None = resp['data']
        if resp and resp.get('msg') == 'request error':
            raise AnycubicAPIParsingError(ErrorsAPIParsing.api_error_user_server_maintenance)
        if data is None:
            raise AnycubicAuthTokensExpired(ErrorsAuthTokenExpired.invalid_credentials)

        # A rejected token can still return a data object, just without a user
        # id. Treat that as invalid credentials so it surfaces as "invalid
        # auth" rather than a TypeError from int(None) further down.
        if data.get('id') is None:
            raise AnycubicAuthTokensExpired(ErrorsAuthTokenExpired.invalid_credentials)

        self.anycubic_auth.set_api_user_id(data['id'])
        self.anycubic_auth.set_api_user_email(data.get('user_email'))
        self.anycubic_auth.set_api_user_mobile(data.get('mobile'))

        return data
