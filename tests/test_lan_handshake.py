"""Tests for the LAN Mode handshake.

The credential exchange is signed and encrypted, so these build a real
encrypted response with the same key material the printer would use and prove
the handshake recovers the broker details from it -- a stubbed decrypt would
prove nothing.
"""

import base64
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7

from anycubic_cloud_api.exceptions.exceptions import (
    AnycubicLANCloudModeError,
    AnycubicLANError,
    AnycubicLANUnsupportedError,
)
from anycubic_cloud_api.lan.handshake import (
    AnycubicLANHandshake,
    _decrypt_broker_info,
    _extract_mac,
    _sign_request,
)

# 32 chars: the first half signs, the second half is the AES key.
TOKEN = "0123456789abcdef" "fedcba9876543210"
LOCAL_TOKEN = "localtoken123456"

BROKER_PAYLOAD = {
    "broker": "mqtts://10.0.66.28:9883",
    "username": "printer-user",
    "password": "printer-pass",
    "deviceId": "DEVICE1234",
}

INFO_DOCUMENT = {
    "ctrlType": "lan",
    "token": TOKEN,
    "ctrlInfoUrl": "http://10.0.66.28:18910/ctrl",
    "modelId": 20025,
    "cn": "SERIAL123",
    "usn": "uuid:fdm:A4-E8-8D-80-54-C8",
    "modelName": "Anycubic Kobra S1",
    "deviceType": "fdm",
}


def encrypt_payload(payload: dict, token: str, local_token: str) -> str:
    """Encrypt exactly as the printer does, so the test exercises real crypto."""
    key = token[16:32].encode()
    iv = local_token.encode()[:16].ljust(16, b"\0")
    padder = PKCS7(128).padder()
    padded = padder.update(json.dumps(payload).encode()) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()

    return base64.b64encode(encryptor.update(padded) + encryptor.finalize()).decode()


class StubbedHandshake(AnycubicLANHandshake):
    """Replaces only the HTTP call, so signing and decryption stay real."""

    __slots__ = ("fetch",)

    def __init__(self, responses):
        super().__init__(MagicMock(), "10.0.66.28")
        self.fetch = AsyncMock(side_effect=list(responses))

    async def _fetch_json(self, method, url):
        return await self.fetch(method, url)


def make_handshake(responses):
    """A handshake whose HTTP calls return the given responses in order."""
    return StubbedHandshake(responses)


def control_response(payload=None, token=TOKEN, local_token=LOCAL_TOKEN, code=200):
    return {
        "code": code,
        "data": {
            "info": encrypt_payload(payload or BROKER_PAYLOAD, token, local_token),
            "token": local_token,
        },
    }


class TestSigning:
    def test_signature_is_stable_for_the_same_inputs(self):
        first = _sign_request(TOKEN, 1735689600000, "abc123")
        second = _sign_request(TOKEN, 1735689600000, "abc123")

        assert first == second
        assert len(first) == 32

    def test_signature_uses_only_the_first_half_of_the_token(self):
        """The second half is the AES key and must not leak into the signature."""
        other = TOKEN[:16] + "0000000000000000"

        assert _sign_request(TOKEN, 1, "n") == _sign_request(other, 1, "n")

    @pytest.mark.parametrize(
        ("timestamp", "nonce"),
        [(1735689600001, "abc123"), (1735689600000, "abc124")],
    )
    def test_changing_timestamp_or_nonce_changes_the_signature(self, timestamp, nonce):
        assert _sign_request(TOKEN, timestamp, nonce) != _sign_request(
            TOKEN, 1735689600000, "abc123"
        )


class TestDecrypt:
    def test_round_trips_a_real_encrypted_payload(self):
        blob = encrypt_payload(BROKER_PAYLOAD, TOKEN, LOCAL_TOKEN)

        assert _decrypt_broker_info(blob, TOKEN, LOCAL_TOKEN) == BROKER_PAYLOAD

    def test_a_short_local_token_is_padded_not_rejected(self):
        """The IV is padded to 16 bytes, so a short token still decrypts."""
        blob = encrypt_payload(BROKER_PAYLOAD, TOKEN, "short")

        assert _decrypt_broker_info(blob, TOKEN, "short") == BROKER_PAYLOAD

    def test_the_wrong_key_raises_rather_than_returning_junk(self):
        blob = encrypt_payload(BROKER_PAYLOAD, TOKEN, LOCAL_TOKEN)
        wrong = TOKEN[:16] + "0000000000000000"

        with pytest.raises(AnycubicLANError):
            _decrypt_broker_info(blob, wrong, LOCAL_TOKEN)

    @pytest.mark.parametrize("junk", ["", "not-base64!", base64.b64encode(b"x").decode()])
    def test_junk_raises(self, junk):
        with pytest.raises(AnycubicLANError):
            _decrypt_broker_info(junk, TOKEN, LOCAL_TOKEN)


class TestMacExtraction:
    @pytest.mark.parametrize(
        ("usn", "expected"),
        [
            ("uuid:fdm:A4-E8-8D-80-54-C8", "A4-E8-8D-80-54-C8"),
            # Normalised to the form the cloud reports -- see TestMacNormalisation.
            ("uuid:fdm:a4:e8:8d:80:54:c8", "A4-E8-8D-80-54-C8"),
            ("no mac here", None),
            (None, None),
            ("", None),
        ],
    )
    def test_extraction(self, usn, expected):
        assert _extract_mac(usn) == expected


class TestHandshake:
    @pytest.mark.asyncio
    async def test_a_successful_handshake_returns_the_broker(self):
        handshake = make_handshake([INFO_DOCUMENT, control_response()])

        broker = await handshake.async_authenticate()

        assert (broker.host, broker.port) == ("10.0.66.28", 9883)
        assert broker.username == "printer-user"
        assert broker.password == "printer-pass"
        assert broker.device_id == "DEVICE1234"
        assert broker.model_id == "20025"
        assert broker.serial == "SERIAL123"
        assert broker.mac == "A4-E8-8D-80-54-C8"
        assert broker.model_name == "Anycubic Kobra S1"

    @pytest.mark.asyncio
    async def test_a_printer_in_cloud_mode_says_so(self):
        handshake = make_handshake([{**INFO_DOCUMENT, "ctrlType": "cloud"}])

        with pytest.raises(AnycubicLANCloudModeError, match="LAN Mode"):
            await handshake.async_authenticate()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("missing", ["token", "ctrlInfoUrl", "modelId"])
    async def test_an_older_handshake_is_named_not_a_parse_error(self, missing):
        info = {key: value for key, value in INFO_DOCUMENT.items() if key != missing}
        handshake = make_handshake([info])

        with pytest.raises(AnycubicLANUnsupportedError):
            await handshake.async_authenticate()

    @pytest.mark.asyncio
    async def test_a_rejected_control_request_surfaces_the_message(self):
        handshake = make_handshake(
            [INFO_DOCUMENT, {"code": 403, "message": "bad sign"}]
        )

        with pytest.raises(AnycubicLANError, match="bad sign"):
            await handshake.async_authenticate()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "control",
        [
            {"code": 200},
            {"code": 200, "data": "not-a-dict"},
            {"code": 200, "data": {"info": "x"}},
            {"code": 200, "data": {"token": "x"}},
        ],
    )
    async def test_a_malformed_control_reply_raises(self, control):
        handshake = make_handshake([INFO_DOCUMENT, control])

        with pytest.raises(AnycubicLANError):
            await handshake.async_authenticate()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("field", ["broker", "username", "password", "deviceId"])
    async def test_missing_broker_fields_raise(self, field):
        payload = {key: value for key, value in BROKER_PAYLOAD.items() if key != field}
        handshake = make_handshake([INFO_DOCUMENT, control_response(payload)])

        with pytest.raises(AnycubicLANError):
            await handshake.async_authenticate()

    @pytest.mark.asyncio
    async def test_a_broker_url_without_a_port_falls_back_to_the_default(self):
        payload = {**BROKER_PAYLOAD, "broker": "mqtts://10.0.66.28"}
        handshake = make_handshake([INFO_DOCUMENT, control_response(payload)])

        assert (await handshake.async_authenticate()).port == 9883

    @pytest.mark.asyncio
    async def test_an_unparseable_broker_url_raises(self):
        payload = {**BROKER_PAYLOAD, "broker": "://nonsense"}
        handshake = make_handshake([INFO_DOCUMENT, control_response(payload)])

        with pytest.raises(AnycubicLANError):
            await handshake.async_authenticate()

    @pytest.mark.asyncio
    async def test_credentials_are_kept_out_of_the_repr(self):
        handshake = make_handshake([INFO_DOCUMENT, control_response()])

        rendered = repr(await handshake.async_authenticate())

        assert "printer-pass" not in rendered
        assert "printer-user" not in rendered
        assert "10.0.66.28" in rendered

    @pytest.mark.asyncio
    async def test_the_signed_request_carries_all_four_parameters(self):
        handshake = make_handshake([INFO_DOCUMENT, control_response()])

        await handshake.async_authenticate()

        url = handshake.fetch.await_args_list[1].args[1]

        assert url.startswith("http://10.0.66.28:18910/ctrl?")
        for parameter in ("ts=", "nonce=", "sign=", "did="):
            assert parameter in url


class TestNetworkFailures:
    """A wrong address times out; asyncio's TimeoutError is not a ClientError."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "error",
        [
            TimeoutError(),
            OSError("no route to host"),
            __import__("aiohttp").ClientError("refused"),
        ],
    )
    async def test_network_errors_become_a_readable_message(self, error):

        session = MagicMock()
        session.request = MagicMock(side_effect=error)
        handshake = AnycubicLANHandshake(session, "10.0.66.99")

        with pytest.raises(AnycubicLANError, match="10.0.66.99"):
            await handshake.async_fetch_info()


class TestMacNormalisation:
    """Entity unique ids are built from this, so the format must be stable.

    The cloud reports upper case with hyphens for the same printer. If the two
    sources disagreed, switching between cloud and local would recreate every
    entity as a duplicate rather than reusing it.
    """

    @pytest.mark.parametrize(
        "usn",
        [
            "uuid:fdm:A4-E8-8D-80-54-C8",
            "uuid:fdm:a4-e8-8d-80-54-c8",
            "uuid:fdm:A4:E8:8D:80:54:C8",
            "uuid:fdm:a4:e8:8d:80:54:c8",
        ],
    )
    def test_every_form_normalises_to_the_cloud_format(self, usn):
        assert _extract_mac(usn) == "A4-E8-8D-80-54-C8"
