"""Tests for sending orders to the printer locally instead of to the cloud.

The shapes asserted here are Anycubic's own: the slicer ships a cloud command
module and a local one side by side, and these pin the translation between
them. A printer in LAN Mode is gone from the cloud entirely, so getting this
wrong is the difference between a working control and one that silently does
nothing.
"""

import json
from unittest.mock import MagicMock

import pytest

from anycubic_cloud_api.api.functions import AnycubicAPIFunctions
from anycubic_cloud_api.const.enums import AnycubicOrderID
from anycubic_cloud_api.data_models.orders import (
    AnycubicPrinterOrderRequest,
    AnycubicPrinterQueryOrderRequest,
    AnycubicProjectOrderRequest,
)
from anycubic_cloud_api.lan.client import AnycubicLANClient
from anycubic_cloud_api.lan.commands import lan_command_for_order
from anycubic_cloud_api.lan.handshake import AnycubicLANBroker

BROKER = AnycubicLANBroker(
    host="10.0.66.28",
    port=9883,
    username="user",
    password="pass",
    device_id="DEVICE1234",
    model_id="20025",
)


def make_client():
    """A client whose publishes can be read back, with no broker involved."""
    client = AnycubicLANClient(BROKER, lambda *args: None)
    client._client = MagicMock()

    return client


def published(client):
    topic, body = client._client.publish.call_args[0]

    return topic, json.loads(body)


class TestTheEnvelope:
    def test_a_command_carries_the_slicer_s_five_fields(self):
        client = make_client()

        msgid = client.publish_command("light", "control", {"status": 1})
        topic, message = published(client)

        assert topic.endswith("/web/printer/20025/DEVICE1234/light")
        assert message["type"] == "light"
        assert message["action"] == "control"
        assert message["data"] == {"status": 1}
        assert message["msgid"] == msgid
        assert isinstance(message["timestamp"], int)

    def test_the_timestamp_is_in_milliseconds(self):
        """Seconds would be forty years in the printer's past."""
        client = make_client()

        client.publish_command("axis", "turnOff")
        _, message = published(client)

        assert message["timestamp"] > 1_700_000_000_000

    def test_a_command_with_nothing_to_say_sends_null_data(self):
        client = make_client()

        client.publish_command("axis", "turnOff")
        _, message = published(client)

        assert message["data"] is None

    def test_every_command_gets_its_own_id(self):
        client = make_client()

        first = client.publish_command("light", "query")
        second = client.publish_command("light", "query")

        assert first != second


class TestTheMapping:
    @pytest.mark.parametrize(
        ("order", "message_type", "action"),
        [
            (AnycubicOrderID.SET_LIGHT_STATUS, "light", "control"),
            (AnycubicOrderID.GET_LIGHT_STATUS, "light", "query"),
            (AnycubicOrderID.SET_TEMPERATURE, "tempature", "set"),
            (AnycubicOrderID.SET_FAN_SPEED, "fan", "setSpeed"),
            (AnycubicOrderID.MOVE_AXLE, "axis", "move"),
            (AnycubicOrderID.MOVE_AXLE_TURN_OFF, "axis", "turnOff"),
            (AnycubicOrderID.QUERY_PERIPHERALS, "peripherie", "query"),
            (AnycubicOrderID.MULTI_COLOR_BOX_DRY, "multiColorBox", "setDry"),
            (AnycubicOrderID.FEED_FILAMENT, "multiColorBox", "feedFilament"),
            (AnycubicOrderID.MULTI_COLOR_BOX_AUTO_FEED, "multiColorBox", "setAutoFeed"),
            (AnycubicOrderID.MULTI_COLOR_BOX_SET_SLOT, "multiColorBox", "setInfo"),
            (AnycubicOrderID.PAUSE_PRINT, "print", "pause"),
            (AnycubicOrderID.RESUME_PRINT, "print", "resume"),
            (AnycubicOrderID.STOP_PRINT, "print", "stop"),
            (AnycubicOrderID.PRINT_SETTINGS, "print", "update"),
        ],
    )
    def test_orders_map_to_the_shapes_the_slicer_sends(
        self, order, message_type, action
    ):
        command = lan_command_for_order(order)

        assert command is not None
        assert (command.message_type, command.action) == (message_type, action)

    def test_the_firmware_s_own_misspelling_is_preserved(self):
        """Correcting "tempature" gets no reply at all."""
        command = lan_command_for_order(AnycubicOrderID.SET_TEMPERATURE)

        assert command.message_type == "tempature"

    def test_ai_detection_has_no_local_form(self):
        """The slicer marks this one wide-area only, so it must reach the cloud."""
        assert lan_command_for_order(AnycubicOrderID.SET_AI_SETTINGS) is None

    def test_the_camera_order_has_no_local_form(self):
        """Locally the camera is FLV over HTTP, nothing to do with order 1001."""
        assert lan_command_for_order(AnycubicOrderID.CAMERA_OPEN) is None

    def test_an_unmapped_order_is_simply_absent(self):
        assert lan_command_for_order(AnycubicOrderID.START_PRINT) is None


class FakeAPI:
    """Just enough of the API to exercise the dispatch decision.

    The real one needs a session, a cookie jar and a login; the decision being
    tested needs none of that, only somewhere to send and a way to know
    whether it is connected.
    """

    def __init__(self, client=None):
        self._lan_client = client
        self.logged = []
        self.cloud_calls = []

    @property
    def lan_is_connected(self):
        return self._lan_client is not None and self._lan_client.is_connected

    def _log_to_debug(self, msg):
        self.logged.append(msg)

    async def _fetch_api_resp(self, endpoint=None, params=None, **kwargs):
        self.cloud_calls.append(params)

        return {"data": {"msgid": "from-the-cloud"}}

    _send_anycubic_order_over_lan = (
        AnycubicAPIFunctions._send_anycubic_order_over_lan
    )
    _send_anycubic_order = AnycubicAPIFunctions._send_anycubic_order


def connected_client():
    client = make_client()
    client._client.is_connected.return_value = True

    return client


class TestDispatch:
    def test_a_mapped_order_goes_out_locally(self):
        client = connected_client()
        api = FakeAPI(client)

        msgid = api._send_anycubic_order_over_lan(
            AnycubicPrinterOrderRequest(
                order_id=AnycubicOrderID.SET_LIGHT_STATUS,
                printer_id=1,
                order_data={"type": 2, "status": 1, "brightness": 100},
            )
        )

        _, message = published(client)

        assert msgid == message["msgid"]
        assert message["data"] == {"type": 2, "status": 1, "brightness": 100}

    def test_the_order_s_own_payload_is_passed_through_untouched(self):
        """Both transports take the same data; only the routing differs."""
        client = connected_client()
        data = {"multi_color_box": [{"id": 0, "auto_feed": 1}]}

        FakeAPI(client)._send_anycubic_order_over_lan(
            AnycubicProjectOrderRequest(
                order_id=AnycubicOrderID.MULTI_COLOR_BOX_AUTO_FEED,
                printer_id=1,
                project_id=0,
                order_data=data,
            )
        )

        assert published(client)[1]["data"] == data

    def test_an_unmapped_order_is_left_for_the_cloud(self):
        client = connected_client()
        api = FakeAPI(client)

        result = api._send_anycubic_order_over_lan(
            AnycubicPrinterOrderRequest(
                order_id=AnycubicOrderID.SET_AI_SETTINGS,
                printer_id=1,
                order_data={"ai_settings": {}},
            )
        )

        assert result is None
        client._client.publish.assert_not_called()

    def test_nothing_is_sent_without_a_local_connection(self):
        api = FakeAPI(None)

        assert api._send_anycubic_order_over_lan(
            AnycubicPrinterOrderRequest(
                order_id=AnycubicOrderID.SET_LIGHT_STATUS, printer_id=1
            )
        ) is None

    def test_a_disconnected_client_is_not_used(self):
        client = make_client()
        client._client.is_connected.return_value = False

        assert FakeAPI(client)._send_anycubic_order_over_lan(
            AnycubicPrinterOrderRequest(
                order_id=AnycubicOrderID.SET_LIGHT_STATUS, printer_id=1
            )
        ) is None


class TestChoosingBetweenTheTwoTransports:
    @pytest.mark.asyncio
    async def test_a_mapped_order_prefers_the_local_connection(self):
        client = connected_client()
        api = FakeAPI(client)

        result = await api._send_anycubic_order(
            AnycubicPrinterOrderRequest(
                order_id=AnycubicOrderID.SET_LIGHT_STATUS,
                printer_id=1,
                order_data={"status": 1},
            )
        )

        assert api.cloud_calls == []
        assert result == published(client)[1]["msgid"]

    @pytest.mark.asyncio
    async def test_an_unmapped_order_falls_through_to_the_cloud(self):
        client = connected_client()
        api = FakeAPI(client)

        result = await api._send_anycubic_order(
            AnycubicPrinterOrderRequest(
                order_id=AnycubicOrderID.SET_AI_SETTINGS,
                printer_id=1,
                order_data={"ai_settings": {}},
            )
        )

        assert result == "from-the-cloud"
        client._client.publish.assert_not_called()

    @pytest.mark.asyncio
    async def test_an_order_wanting_the_raw_reply_is_never_diverted(self):
        """A caller asking for raw_data wants the cloud's response body.

        Locally there is no response body to give it -- only a message id --
        so diverting one would hand back a string where a dict was promised.
        """
        client = connected_client()
        api = FakeAPI(client)

        result = await api._send_anycubic_order(
            AnycubicPrinterQueryOrderRequest(
                order_id=AnycubicOrderID.GET_LIGHT_STATUS,
                printer_id=1,
            ),
            raw_data=True,
        )

        assert result == {"data": {"msgid": "from-the-cloud"}}
        client._client.publish.assert_not_called()


class TestPrintControls:
    def test_the_project_becomes_a_taskid_in_the_payload(self):
        """Locally there is no project_id field to put it in."""
        client = connected_client()

        FakeAPI(client)._send_anycubic_order_over_lan(
            AnycubicProjectOrderRequest(
                order_id=AnycubicOrderID.PAUSE_PRINT,
                printer_id=1,
                project_id=4242,
                order_data=None,
            )
        )

        _, message = published(client)

        assert message["data"] == {"taskid": "4242"}

    def test_the_taskid_is_a_string(self):
        client = connected_client()

        FakeAPI(client)._send_anycubic_order_over_lan(
            AnycubicProjectOrderRequest(
                order_id=AnycubicOrderID.STOP_PRINT,
                printer_id=1,
                project_id=7,
                order_data=None,
            )
        )

        assert isinstance(published(client)[1]["data"]["taskid"], str)

    def test_a_settings_change_keeps_its_settings(self):
        client = connected_client()

        FakeAPI(client)._send_anycubic_order_over_lan(
            AnycubicProjectOrderRequest(
                order_id=AnycubicOrderID.PRINT_SETTINGS,
                printer_id=1,
                project_id=9,
                order_data={"settings": {"target_nozzle_temp": 210}},
            )
        )

        _, message = published(client)

        assert message["data"] == {
            "settings": {"target_nozzle_temp": 210},
            "taskid": "9",
        }

    def test_a_print_control_without_a_project_is_left_alone(self):
        """Nothing sensible to address it to, so the cloud can refuse it."""
        client = connected_client()
        api = FakeAPI(client)

        result = api._send_anycubic_order_over_lan(
            AnycubicPrinterQueryOrderRequest(
                order_id=AnycubicOrderID.PAUSE_PRINT, printer_id=1
            )
        )

        assert result is None
        client._client.publish.assert_not_called()


class TestTheLightDoesNotNeedAPrintJob:
    """The light belongs to the printer, and the slicer sends it with no
    project at all. Requiring one made it dead on every printer the cloud
    lists no projects for -- which is every printer in LAN Mode, because
    going local removes it from the account."""

    def _api(self, client=None):
        api = FakeAPI(client)
        api._send_order_set_light_status = (
            AnycubicAPIFunctions._send_order_set_light_status.__get__(api)
        )

        return api

    def _printer(self):
        printer = MagicMock()
        printer.id = 1
        printer.light_type = 2

        return printer

    @pytest.mark.asyncio
    async def test_it_reaches_the_printer_with_no_project(self):
        client = connected_client()
        api = self._api(client)

        await api._send_order_set_light_status(
            printer=self._printer(), project=None, light_on=True
        )

        _, message = published(client)

        assert message["action"] == "control"
        assert message["data"] == {"type": 2, "status": 1, "brightness": 100}

    @pytest.mark.asyncio
    async def test_turning_it_off_sends_zero_brightness(self):
        client = connected_client()
        api = self._api(client)

        await api._send_order_set_light_status(
            printer=self._printer(), project=None, light_on=False
        )

        assert published(client)[1]["data"] == {
            "type": 2,
            "status": 0,
            "brightness": 0,
        }

    @pytest.mark.asyncio
    async def test_the_cloud_still_gets_the_project_when_there_is_one(self):
        """That is the form proven against the cloud, so it is left alone."""
        api = self._api()
        project = MagicMock()
        project.id = 77

        await api._send_order_set_light_status(
            printer=self._printer(), project=project, light_on=True
        )

        assert api.cloud_calls[0]["project_id"] == 77

    @pytest.mark.asyncio
    async def test_without_a_project_the_cloud_gets_a_printer_level_order(self):
        """The slicer sends no project_id for this order."""
        api = self._api()

        await api._send_order_set_light_status(
            printer=self._printer(), project=None, light_on=True
        )

        assert "project_id" not in api.cloud_calls[0]
        assert api.cloud_calls[0]["order_id"] == "1233"


class TestOrderRequestsExposeTheirParts:
    def test_a_bare_request_has_no_payload_or_project(self):
        request = AnycubicPrinterQueryOrderRequest(
            order_id=AnycubicOrderID.QUERY_PERIPHERALS, printer_id=1
        )

        assert request.order_id == AnycubicOrderID.QUERY_PERIPHERALS
        assert request.order_data is None
        assert request.project_id is None

    def test_a_printer_order_exposes_its_payload(self):
        request = AnycubicPrinterOrderRequest(
            order_id=AnycubicOrderID.MOVE_AXLE,
            printer_id=1,
            order_data={"axis": 3, "move_type": 2, "distance": 0},
        )

        assert request.order_data == {"axis": 3, "move_type": 2, "distance": 0}

    def test_a_project_order_exposes_both(self):
        request = AnycubicProjectOrderRequest(
            order_id=AnycubicOrderID.PRINT_SETTINGS,
            printer_id=1,
            project_id=5,
            order_data={"settings": {}},
        )

        assert request.project_id == 5
        assert request.order_data == {"settings": {}}


class TestTheCapabilityPollAsksAtAll:
    """Both of these were renamed when they became bare printer-level polls,
    and this caller kept the old private names -- so every MQTT subscribe
    raised AttributeError instead of asking the printer anything."""

    def test_the_methods_it_calls_exist(self):
        assert hasattr(AnycubicAPIFunctions, "send_order_query_peripherals")
        assert hasattr(AnycubicAPIFunctions, "send_order_get_light_status")
        assert not hasattr(AnycubicAPIFunctions, "_send_order_query_peripherals")

    def test_it_asks_for_both_without_a_print_job(self):
        """An idle printer is exactly when someone reaches for the light."""
        import inspect

        source = inspect.getsource(AnycubicAPIFunctions.query_printer_options)

        assert "self.send_order_query_peripherals" in source
        assert "self.send_order_get_light_status" in source
        assert "return None" not in source.split("send_order_query_peripherals")[1]
