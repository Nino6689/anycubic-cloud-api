"""Getting local MQTT credentials out of a printer in LAN Mode.

A printer with LAN Mode switched on runs its own MQTT broker, but it will not
hand out the credentials for it until you have proved you can reach it on the
local network and have read its discovery document. That proof is a signed
request, and the reply is encrypted with key material taken from the same
document -- so the whole exchange is worthless to anyone who cannot already
talk to the printer directly.

The sequence:

1. ``GET http://<host>:18910/info`` returns the discovery document, including a
   token, the URL to call next, and what model the printer is.
2. That token is split in half. The first half keys an MD5 signature over a
   timestamp and nonce; the second half is the AES key for step 4.
3. ``POST <ctrlInfoUrl>?ts&nonce&sign&did`` returns a base64 blob and a second
   token used as the initialisation vector.
4. AES-CBC decrypting the blob yields the broker address, username, password
   and device id.

Credentials are rotated by the printer and are only meaningful on the local
network, so they are held in memory for the life of the connection and never
written to disk.

The protocol was documented by the ``anycubic_ha_local`` project
(https://github.com/chrisfore/anycubic_ha_local, MIT). This is an independent
implementation of it.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import string
import time
from dataclasses import dataclass
from typing import Any

import aiohttp
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7

from ..const.lan import (
    LAN_AES_BLOCK_BITS,
    LAN_AES_IV_LENGTH,
    LAN_CTRL_TYPE_CLOUD,
    LAN_DEVICE_ID_LENGTH,
    LAN_HTTP_TIMEOUT,
    LAN_INFO_PATH,
    LAN_INFO_PORT,
    LAN_MQTT_DEFAULT_PORT,
    LAN_NONCE_LENGTH,
    LAN_REQUIRED_BROKER_FIELDS,
    LAN_REQUIRED_INFO_FIELDS,
    LAN_TOKEN_KEY_SLICE,
    LAN_TOKEN_SIGN_SLICE,
)
from ..exceptions.error_strings import ErrorsLAN
from ..exceptions.exceptions import (
    AnycubicLANCloudModeError,
    AnycubicLANError,
    AnycubicLANUnsupportedError,
)

# "mqtts://192.168.1.50:9883" -- the scheme is always TLS in practice, but the
# port is taken from the URL rather than assumed.
_BROKER_URL_PATTERN = re.compile(r"^mqtts?://(?P<host>[^:/]+)(?::(?P<port>\d+))?")

# The discovery document reports the MAC inside a URN, e.g.
# "uuid:fdm:AA-BB-CC-DD-EE-FF".
_MAC_PATTERN = re.compile(r"(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}")

_DEVICE_ID_ALPHABET = string.ascii_uppercase + string.digits
_NONCE_ALPHABET = string.ascii_letters + string.digits


@dataclass(frozen=True, slots=True)
class AnycubicLANBroker:
    """Everything needed to reach a printer's own MQTT broker."""

    host: str
    port: int
    username: str
    password: str
    device_id: str
    model_id: str
    serial: str | None = None
    mac: str | None = None
    model_name: str | None = None
    device_type: str | None = None

    def __repr__(self) -> str:
        """Redact the credentials -- this ends up in debug logs and issues."""
        return (
            f"AnycubicLANBroker(host={self.host}, port={self.port}, "
            f"username=<redacted>, password=<redacted>, "
            f"device_id={self.device_id}, model_id={self.model_id}, "
            f"model_name={self.model_name})"
        )


def _sign_request(token: str, timestamp: int, nonce: str) -> str:
    """Sign a control request the way the printer's firmware expects.

    MD5 is the printer's choice, not ours, and it is signing a request that
    only travels across the local network -- so it is flagged as not being
    relied on for security here.
    """
    keyed = hashlib.md5(
        token[LAN_TOKEN_SIGN_SLICE].encode(), usedforsecurity=False
    ).hexdigest()

    return hashlib.md5(
        f"{keyed}{timestamp}{nonce}".encode(), usedforsecurity=False
    ).hexdigest()


def _decrypt_broker_info(payload: str, token: str, local_token: str) -> dict[str, Any]:
    """Decrypt the credential blob returned by the control endpoint."""
    key = token[LAN_TOKEN_KEY_SLICE].encode()
    iv = local_token.encode()[:LAN_AES_IV_LENGTH].ljust(LAN_AES_IV_LENGTH, b"\0")

    try:
        decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
        padded = decryptor.update(base64.b64decode(payload)) + decryptor.finalize()
        unpadder = PKCS7(LAN_AES_BLOCK_BITS).unpadder()
        plaintext = unpadder.update(padded) + unpadder.finalize()
        decoded = json.loads(plaintext.decode())
    except Exception as err:
        raise AnycubicLANError(ErrorsLAN.decrypt_failed) from err

    if not isinstance(decoded, dict):
        raise AnycubicLANError(ErrorsLAN.decrypt_failed)

    return decoded


def _extract_mac(usn: Any) -> str | None:
    """Pull the MAC out of the discovery document's URN, if it has one.

    Normalised to upper case with hyphens, which is the form the cloud reports
    for the same printer. Home Assistant builds entity unique ids from this, so
    the two sources agreeing is what lets a printer switch between the cloud
    and the local connection without every entity being recreated as a
    duplicate.
    """
    if not usn:
        return None

    match = _MAC_PATTERN.search(str(usn))

    if match is None:
        return None

    return match.group(0).replace(":", "-").upper()


class AnycubicLANHandshake:
    """Performs the LAN Mode handshake against one printer."""

    __slots__ = (
        "_session",
        "_host",
        "_debug_logger",
    )

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        debug_logger: Any = None,
    ) -> None:
        self._session = session
        self._host = host
        self._debug_logger = debug_logger

    def _log_to_debug(self, msg: str) -> None:
        if self._debug_logger is not None:
            self._debug_logger.debug(msg)

    async def _fetch_json(self, method: str, url: str) -> dict[str, Any]:
        timeout = aiohttp.ClientTimeout(total=LAN_HTTP_TIMEOUT)

        try:
            async with self._session.request(
                method, url, timeout=timeout
            ) as response:
                response.raise_for_status()
                # The printer serves JSON without a JSON content type, so the
                # check aiohttp would normally make has to be skipped.
                decoded = json.loads(await response.text())
        except (aiohttp.ClientError, TimeoutError, OSError) as err:
            # A wrong address times out rather than refusing, and asyncio's
            # TimeoutError is not a ClientError -- without it the user gets a
            # traceback instead of "check the address".
            raise AnycubicLANError(ErrorsLAN.unreachable.format(self._host)) from err
        except json.JSONDecodeError as err:
            raise AnycubicLANError(ErrorsLAN.bad_response) from err

        if not isinstance(decoded, dict):
            raise AnycubicLANError(ErrorsLAN.bad_response)

        return decoded

    async def async_fetch_info(self) -> dict[str, Any]:
        """Read the printer's discovery document.

        Raises if the printer is in cloud mode, or is an older model that
        speaks a handshake this does not implement.
        """
        info = await self._fetch_json(
            "GET", f"http://{self._host}:{LAN_INFO_PORT}{LAN_INFO_PATH}"
        )

        if info.get("ctrlType") == LAN_CTRL_TYPE_CLOUD:
            raise AnycubicLANCloudModeError(ErrorsLAN.printer_in_cloud_mode)

        missing = [field for field in LAN_REQUIRED_INFO_FIELDS if not info.get(field)]

        if missing:
            # Kobra 2 and earlier answer on this port but with a different,
            # unsigned handshake. Saying so beats a confusing parse error.
            raise AnycubicLANUnsupportedError(ErrorsLAN.unsupported_handshake)

        return info

    async def async_authenticate(self) -> AnycubicLANBroker:
        """Run the full handshake and return the broker credentials."""
        info = await self.async_fetch_info()

        token = str(info["token"])
        timestamp = int(time.time() * 1000)
        nonce = "".join(
            secrets.choice(_NONCE_ALPHABET) for _ in range(LAN_NONCE_LENGTH)
        )
        device_id = "".join(
            secrets.choice(_DEVICE_ID_ALPHABET) for _ in range(LAN_DEVICE_ID_LENGTH)
        )

        query = (
            f"ts={timestamp}"
            f"&nonce={nonce}"
            f"&sign={_sign_request(token, timestamp, nonce)}"
            f"&did={device_id}"
        )

        control = await self._fetch_json("POST", f"{info['ctrlInfoUrl']}?{query}")

        if control.get("code") != 200:
            raise AnycubicLANError(
                ErrorsLAN.control_rejected.format(control.get("message"))
            )

        data = control.get("data")

        if not isinstance(data, dict) or "info" not in data or "token" not in data:
            raise AnycubicLANError(ErrorsLAN.bad_response)

        broker_info = _decrypt_broker_info(
            str(data["info"]), token, str(data["token"])
        )

        missing = [
            field for field in LAN_REQUIRED_BROKER_FIELDS if not broker_info.get(field)
        ]

        if missing:
            raise AnycubicLANError(ErrorsLAN.bad_response)

        match = _BROKER_URL_PATTERN.match(str(broker_info["broker"]))

        if match is None:
            raise AnycubicLANError(ErrorsLAN.bad_response)

        port = match.group("port")

        broker = AnycubicLANBroker(
            host=match.group("host"),
            port=int(port) if port else LAN_MQTT_DEFAULT_PORT,
            username=str(broker_info["username"]),
            password=str(broker_info["password"]),
            device_id=str(broker_info["deviceId"]),
            model_id=str(info["modelId"]),
            serial=info.get("cn") or None,
            mac=_extract_mac(info.get("usn")),
            model_name=info.get("modelName") or None,
            device_type=info.get("deviceType") or None,
        )

        self._log_to_debug(f"Anycubic LAN handshake succeeded: {broker}")

        return broker
