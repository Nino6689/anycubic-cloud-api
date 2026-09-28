"""The access-token exchange is rate-limited, and that is not a login failure.

Measured 2026-09-28: a second exchange of the same slicer token within about
3 s of a successful one is answered `code 0`, `msg` "请求过于频繁。请稍后再试"
("requests too frequent, try again later") and no data; after 5 s or more it
succeeds. The retry loop tried twice, 2 s apart -- both inside the cooldown --
then treated it as a refused token: the web fallback ran, userInfo refused the
access token as a web token, and the integration asked the user to
re-authenticate with a perfectly good token.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from anycubic_cloud_api import AnycubicAPI
from anycubic_cloud_api.exceptions.exceptions import (
    AnycubicAPIParsingError,
    AnycubicAuthError,
    AnycubicRateLimitError,
)
from anycubic_cloud_api.models.auth import AnycubicAuthMode

RATE_LIMITED = {"code": 0, "msg": "请求过于频繁。请稍后再试", "data": None}
REFUSED = {"code": 0, "msg": "User does not exist", "data": None}
SUCCESS = {"code": 1, "msg": "Login successful", "data": {"token": "user-token"}}


def slicer_api():
    api = AnycubicAPI(session=MagicMock(), cookie_jar=MagicMock())
    api.set_authentication(auth_token="eyJ.access.token", auth_mode=AnycubicAuthMode.SLICER)
    return api


async def run_exchange(api, answers):
    fetch = AsyncMock(side_effect=answers)
    sleep = AsyncMock()
    with patch.object(api, "_fetch_api_resp", fetch), patch("asyncio.sleep", sleep):
        await api._get_user_token_with_access_token_with_retry()
    return fetch, sleep


async def test_a_rate_limit_waits_out_the_cooldown_and_succeeds():
    api = slicer_api()

    fetch, sleep = await run_exchange(api, [RATE_LIMITED, RATE_LIMITED, SUCCESS])

    assert fetch.await_count == 3
    assert api.anycubic_auth._auth_token == "user-token"
    # each wait covers the ~3 s cooldown, unlike the 2 s refusal retry
    assert all(call.args[0] >= 5 for call in sleep.await_args_list)


async def test_a_persistent_rate_limit_is_transient_not_an_auth_failure():
    api = slicer_api()

    with pytest.raises(AnycubicRateLimitError) as err:
        await run_exchange(api, [RATE_LIMITED] * 10)

    # The integration treats parsing errors as "try later"; it must never
    # see this as an auth failure, which is what triggers re-authentication.
    assert isinstance(err.value, AnycubicAPIParsingError)
    assert not isinstance(err.value, AnycubicAuthError)


async def test_a_rate_limit_does_not_use_up_the_refusal_retries():
    api = slicer_api()

    fetch, _ = await run_exchange(api, [RATE_LIMITED, REFUSED, SUCCESS])

    assert fetch.await_count == 3
    assert api.anycubic_auth._auth_token == "user-token"


async def test_a_genuine_refusal_still_fails_after_two_attempts():
    api = slicer_api()

    with pytest.raises(AnycubicAuthError):
        await run_exchange(api, [REFUSED, REFUSED])


async def test_the_web_fallback_is_not_triggered_by_a_rate_limit():
    """_check_can_access_api retries as a web token only on AnycubicAuthError."""
    api = slicer_api()
    fetch = AsyncMock(side_effect=[RATE_LIMITED] * 10)
    with (
        patch.object(api, "_fetch_api_resp", fetch),
        patch("asyncio.sleep", AsyncMock()),
        pytest.raises(AnycubicRateLimitError),
    ):
        await api._check_can_access_api()

    assert api.anycubic_auth._auth_mode == AnycubicAuthMode.SLICER
    assert api.anycubic_auth._auth_access_token == "eyJ.access.token"
