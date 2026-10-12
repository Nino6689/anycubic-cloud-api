"""What a resin printer says and accepts over the local connection.

The payloads are captured from an Anycubic Photon P1 Max (model id 132,
device type "lcd") in LAN Mode. It answers almost none of the queries a
Kobra answers -- no info, temperature, fan or print report while idle -- and
sends four kinds of message a Kobra never does. The payload contract fails
loudly on any key left unread, so these double as a check that a real report
is handled completely.
"""

from copy import deepcopy
from unittest.mock import MagicMock

import pytest

from anycubic_cloud_api.const.enums import AnycubicOrderID
from anycubic_cloud_api.data_models.consumable import AnycubicConsumableData
from anycubic_cloud_api.data_models.printer import AnycubicPrinter
from anycubic_cloud_api.exceptions.exceptions import AnycubicMQTTUnknownUpdate
from anycubic_cloud_api.lan.client import LAN_QUERY_ACTIONS, AnycubicLANClient
from anycubic_cloud_api.lan.commands import lan_command_for_order
from anycubic_cloud_api.lan.handshake import AnycubicLANBroker

TOPIC = "anycubic/anycubicCloud/v1/printer/public/132/DEVICE/properties/report"

PROPERTIES_REPORT = {
    "type": "properties",
    "action": "report",
    "msgid": "5d0c0f4e-3a53-4f0c-9c0e-2f0f1f0c7a11",
    "state": "done",
    "timestamp": 1791800112173,
    "code": 200,
    "msg": "",
    "data": {"resin_temp": 24.389999},
}

RELEASE_FILM_REPORT = {
    "type": "releaseFilm",
    "action": "get",
    "msgid": "0b3f7a52-8a0e-4c58-9a51-0a8b8a2f9e02",
    "state": "done",
    "timestamp": 1791800175002,
    "code": 0,
    "msg": "",
    "data": {"times": 0, "layers": 0, "status": 0},
}

PERIPHERALS_REPORT = {
    "type": "peripherie",
    "action": "query",
    "msgid": "a1d7a2f0-33c1-4f6b-8a65-9a3a4d1b2c03",
    "state": "done",
    "timestamp": 1791800173511,
    "code": 200,
    "msg": "",
    "data": {"camera": 1, "udisk": 0, "smartResinVat": 1, "airpure": 0},
}

LIGHT_QUERY_REPORT = {
    "type": "light",
    "action": "query",
    "msgid": "c2b1e7d4-6f0a-4a57-bb0e-6f6d3f1a2b04",
    "state": "done",
    "code": 200,
    "timestamp": 1791800171217,
    "data": {"lights": [{"type": 3, "status": 0}]},
}

STATUS_REPORT = {
    "type": "status",
    "action": "workReport",
    "msgid": "d4c3b2a1-1f2e-4d3c-8b7a-6a5b4c3d2e05",
    "state": "free",
    "timestamp": 1791800177997,
    "code": 200,
    "msg": "",
    "data": None,
}


def video_report(action, state, code=200, msg=""):
    return {
        "type": "video",
        "action": action,
        "msgid": "e5f4a3b2-2a3b-4c4d-9e8f-7b6a5c4d3e06",
        "state": state,
        "timestamp": 1791800301000,
        "code": code,
        "msg": msg,
        "data": None,
    }


def make_printer():
    return AnycubicPrinter(
        api_parent=MagicMock(),
        machine_type=132,
        machine_name="Anycubic Photon P1 Max",
        id=1,
        ignore_init_errors=True,
    )


def apply(printer, report):
    printer.process_mqtt_update(TOPIC, AnycubicConsumableData(deepcopy(report)))


class TestWhatItReports:
    @pytest.mark.parametrize("report", [
        PROPERTIES_REPORT,
        RELEASE_FILM_REPORT,
        PERIPHERALS_REPORT,
        LIGHT_QUERY_REPORT,
        STATUS_REPORT,
    ])
    def test_every_real_report_is_fully_consumed(self, report):
        """Anything unread raises -- so this passing means nothing was missed."""
        apply(make_printer(), report)

    def test_the_resin_temperature_is_kept(self):
        printer = make_printer()

        apply(printer, PROPERTIES_REPORT)

        assert printer.resin_temperature == pytest.approx(24.39, abs=0.01)

    def test_a_printer_that_has_not_said_reports_no_resin_temperature(self):
        assert make_printer().resin_temperature is None

    def test_a_properties_report_without_data_is_harmless(self):
        printer = make_printer()

        apply(printer, {**PROPERTIES_REPORT, "data": None})

        assert printer.resin_temperature is None

    def test_the_release_film_counters_are_kept(self):
        printer = make_printer()

        apply(printer, {**RELEASE_FILM_REPORT, "data": {"times": 12, "layers": 3456, "status": 1}})

        assert printer.release_film_times == 12
        assert printer.release_film_layers == 3456
        assert printer.release_film_status == 1

    def test_an_unseen_release_film_reports_nothing(self):
        printer = make_printer()

        assert printer.release_film_times is None
        assert printer.release_film_layers is None
        assert printer.release_film_status is None

    def test_the_resin_peripherals_are_kept(self):
        printer = make_printer()

        apply(printer, PERIPHERALS_REPORT)

        assert printer.has_peripheral_camera is True
        assert printer.has_peripheral_udisk is False
        assert printer.has_peripheral_smart_resin_vat is True
        assert printer.has_peripheral_air_purifier is False
        assert printer.connected_peripherals["smart_resin_vat"] is True
        assert printer.connected_peripherals["air_purifier"] is False

    def test_a_filament_printer_does_not_grow_resin_peripherals(self):
        printer = make_printer()

        apply(printer, {**PERIPHERALS_REPORT, "data": {"camera": 1, "udisk": 0}})

        assert set(printer.connected_peripherals) == {"camera", "ace", "usb_disk"}

    def test_free_reads_as_not_printing(self):
        printer = make_printer()

        apply(printer, STATUS_REPORT)

        assert printer._is_printing == 1


class TestTheCamera:
    def test_a_started_capture_reads_as_streaming(self):
        printer = make_printer()

        apply(printer, video_report("startCapture", "initSuccess", msg="LanStream start success"))

        assert printer.camera_is_streaming is True

    @pytest.mark.parametrize("state, code, msg", [
        ("done", 200, "LanStream push ended"),
        ("done", 200, "LanStream stop success"),
        ("initSuccess", 1404, ""),
    ])
    def test_every_reply_to_a_stop_reads_as_not_streaming(self, state, code, msg):
        printer = make_printer()
        apply(printer, video_report("startCapture", "initSuccess"))

        apply(printer, video_report("stopCapture", state, code, msg))

        assert printer.camera_is_streaming is False

    def test_before_any_report_it_is_unknown(self):
        assert make_printer().camera_is_streaming is None

    def test_an_unfamiliar_video_action_is_not_swallowed(self):
        with pytest.raises(AnycubicMQTTUnknownUpdate):
            apply(make_printer(), video_report("somethingElse", "done"))

    def test_the_stream_address_can_be_filled_in_from_outside(self):
        printer = make_printer()

        printer.set_camera_stream_url("http://10.0.66.40:18088/flv")

        assert printer.camera_stream_url == "http://10.0.66.40:18088/flv"


BROKER = AnycubicLANBroker(
    host="10.0.66.40",
    port=8883,
    username="user",
    password="pass",
    device_id="DEVICE",
    model_id="132",
    device_type="lcd",
    client_id="given",
)


def make_client():
    client = AnycubicLANClient(BROKER, lambda topic, kind, payload: None)
    client._client = MagicMock()
    return client


class TestWhatItIsAsked:
    def test_status_is_polled(self):
        """No info report on this printer: status is the only free/busy signal."""
        assert LAN_QUERY_ACTIONS["status"] == "query"

    def test_the_release_film_is_asked_for_with_get(self):
        assert LAN_QUERY_ACTIONS["releaseFilm"] == "get"

    def test_the_cloud_release_film_order_has_a_local_form(self):
        command = lan_command_for_order(AnycubicOrderID.GET_RELEASE_FILM)

        assert (command.message_type, command.action) == ("releaseFilm", "get")

    def test_resetting_the_release_film_is_not_guessed_at(self):
        assert lan_command_for_order(AnycubicOrderID.RESET_RELEASE_FILM) is None

    def test_the_stream_address_is_built_from_the_host(self):
        assert make_client().camera_stream_url == "http://10.0.66.40:18088/flv"

    @pytest.mark.parametrize("method, action", [
        ("start_camera", "startCapture"),
        ("stop_camera", "stopCapture"),
    ])
    def test_the_camera_commands_go_out_on_the_video_topic(self, method, action):
        import json

        client = make_client()

        msgid = getattr(client, method)()

        topic, body = client._client.publish.call_args.args
        sent = json.loads(body)
        assert topic.endswith("/132/DEVICE/video")
        assert (sent["type"], sent["action"], sent["msgid"]) == ("video", action, msgid)
        assert isinstance(sent["timestamp"], int)
