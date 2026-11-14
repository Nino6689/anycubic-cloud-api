"""The AWS camera transport and the printer's video reports (#49).

Some accounts get no Agora block from CAMERA_OPEN, only ``data.token``:
temporary AWS credentials for a Kinesis Video WebRTC channel named after the
printer's key. Those were treated as "no credentials" and retried behind a
fresh login, and the printer's ``video`` reports were logged as unknown.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from anycubic_cloud_api.api.functions import AnycubicAPIFunctions
from anycubic_cloud_api.data_models.consumable import AnycubicConsumableData
from anycubic_cloud_api.data_models.orders import (
    AnycubicKvsCredentials,
    AnycubicShengwangCredentials,
)
from anycubic_cloud_api.data_models.printer import AnycubicPrinter

TOKEN = {
    "expiration": 17943490680000000,
    "region": "eu-west-3",
    "sessionToken": "session",
    "tmpSecretId": "ASIAEXAMPLE",
    "tmpSecretKey": "secret",
}
SHENGWANG = {
    "appid": "app",
    "channel": "chan",
    "rtc_token": "rtc",
    "client_uid": 5,
}


class TestKvsCredentials:
    def test_parsed_from_the_token_block(self):
        creds = AnycubicKvsCredentials.from_order_response(
            {"msgid": "m", "token": TOKEN}, "printer-key"
        )
        assert creds is not None
        assert creds.region == "eu-west-3"
        assert creds.access_key_id == "ASIAEXAMPLE"
        assert creds.secret_access_key == "secret"
        assert creds.session_token == "session"
        assert creds.channel_name == "printer-key"
        assert creds.msg_id == "m"

    @pytest.mark.parametrize("missing", ["region", "sessionToken", "tmpSecretId", "tmpSecretKey"])
    def test_an_incomplete_block_is_no_credentials(self, missing):
        token = {k: v for k, v in TOKEN.items() if k != missing}
        assert AnycubicKvsCredentials.from_order_response({"token": token}, "k") is None

    def test_no_channel_name_is_no_credentials(self):
        assert AnycubicKvsCredentials.from_order_response({"token": TOKEN}, None) is None

    def test_repr_never_shows_secrets(self):
        creds = AnycubicKvsCredentials.from_order_response({"token": TOKEN}, "k")
        text = repr(creds)
        for secret in ("session", "ASIAEXAMPLE", "secret"):
            assert secret not in text


def _api(responses):
    api = AnycubicAPIFunctions.__new__(AnycubicAPIFunctions)
    api._fetch_api_resp = AsyncMock(side_effect=responses)
    api._debug_logger = None
    api._anycubic_auth = MagicMock()
    api._check_can_access_api = AsyncMock(return_value=True)
    api._tokens_changed = False
    return api


def _printer():
    printer = MagicMock()
    printer.id = 7
    printer.key = "printer-key"
    return printer


class TestCameraOpen:
    async def test_aws_only_account_gets_kvs_without_a_relogin(self):
        api = _api([{"code": 1, "data": {"msgid": "m", "token": TOKEN}}])
        creds = await api.send_anycubic_camera_open_order(printer=_printer())
        assert isinstance(creds, AnycubicKvsCredentials)
        assert creds.channel_name == "printer-key"
        assert api._fetch_api_resp.await_count == 1
        api._anycubic_auth.clear_cached_access_user_token.assert_not_called()

    async def test_agora_wins_when_both_are_offered(self):
        api = _api([{"code": 1, "data": {"token": TOKEN, "shengwang": SHENGWANG}}])
        creds = await api.send_anycubic_camera_open_order(printer=_printer())
        assert isinstance(creds, AnycubicShengwangCredentials)

    async def test_neither_still_retries_behind_a_fresh_login(self):
        api = _api([{"code": 1, "data": {}}, {"code": 1, "data": {"token": TOKEN}}])
        creds = await api.send_anycubic_camera_open_order(printer=_printer())
        assert isinstance(creds, AnycubicKvsCredentials)
        assert api._fetch_api_resp.await_count == 2


def _video(state):
    return AnycubicConsumableData({
        "type": "video",
        "action": "startCapture",
        "state": state,
        "code": 200,
        "msgid": "m",
        "timestamp": 1,
        "data": None,
    })


class TestVideoReports:
    def test_push_state_is_recorded(self):
        printer = AnycubicPrinter(
            api_parent=MagicMock(),
            machine_type=20025,
            machine_name="Kobra S1",
            id=1,
            ignore_init_errors=True,
        )
        assert printer.camera_push_state is None

        topic = "anycubic/anycubicCloud/v1/printer/public/20025/key/video/report"
        printer.process_mqtt_update(topic, _video("initSuccess"))
        assert printer.camera_push_state == "initSuccess"
        printer.process_mqtt_update(topic, _video("pushStarted"))
        assert printer.camera_push_state == "pushStarted"
        printer.clear_camera_push_state()
        assert printer.camera_push_state is None
