"""Parsing the reports only the local connection sends.

The payloads here are captured verbatim from a Kobra S1 on firmware 2.7.2.7 in
LAN Mode. The payload contract fails loudly on any key left unread, so these
double as a check that nothing in a real report goes unhandled.
"""

from unittest.mock import MagicMock

import pytest

from anycubic_cloud_api.data_models.consumable import AnycubicConsumableData
from anycubic_cloud_api.data_models.printer import AnycubicPrinter

INFO_REPORT = {
    "type": "info",
    "action": "report",
    "timestamp": 244516,
    "msgid": "b85ca099-9792-4e2d-83df-cdd6f1a7296d",
    "state": "done",
    "code": 200,
    "msg": "done",
    "data": {
        "printerName": "Anycubic Kobra S1",
        "urls": {
            "fileUploadurl": "http://10.0.66.28:18910/gcode_upload?s=SIGNED",
            "rtspUrl": "http://10.0.66.28:18088/flv",
        },
        "project": None,
        "last_project": None,
        "model": "Anycubic Kobra S1",
        "ip": "10.0.66.28",
        "version": "2.7.2.7",
        "state": "free",
        "temp": {
            "curr_hotbed_temp": 31,
            "curr_nozzle_temp": 34,
            "target_hotbed_temp": 0,
            "target_nozzle_temp": 0,
        },
        "print_speed_mode": 2,
        "fan_speed_pct": 0,
        "aux_fan_speed_pct": 0,
        "box_fan_level": 0,
        "features": {
            "auto_leveling_support": True,
            "vibration_compensation_support": True,
            "flow_calibration_support": True,
            "drying_first_support": True,
            "camera_timelapse_support": True,
            "gcode_3mf_support": True,
            "delete_batch_support": True,
            "preheating_support": True,
            "fod_support": True,
            "shengwang_rtc_support": True,
            "pre_cancel_support": True,
            "shengwang_rdt_support": True,
        },
    },
}

AI_SETTINGS_REPORT = {
    "type": "aiSettings",
    "action": "query",
    "timestamp": 248130,
    "msgid": "21af7a88-0205-421f-8f21-3a355bd7e9ff",
    "state": "done",
    "code": 200,
    "msg": "done",
    "data": {
        "ai_settings": {
            "status": 0,
            "type": 2,
            "count": 60,
            "notice_type": [0, 1],
            "sensitivity_level": [1, 1],
        }
    },
}

TOPIC = "anycubic/anycubicCloud/v1/printer/public/20025/DEVICE/info"


def make_printer():
    return AnycubicPrinter(
        api_parent=MagicMock(),
        machine_type=20025,
        machine_name="Anycubic Kobra S1",
        id=1,
        ignore_init_errors=True,
    )


def apply(printer, report):
    printer.process_mqtt_update(TOPIC, AnycubicConsumableData(report))


class TestInfoReport:
    def test_the_real_report_is_fully_consumed(self):
        """Anything unread raises -- so this passing means nothing was missed."""
        apply(make_printer(), INFO_REPORT)

    def test_the_camera_url_is_picked_up(self):
        printer = make_printer()

        apply(printer, INFO_REPORT)

        assert printer.camera_stream_url == "http://10.0.66.28:18088/flv"

    def test_the_upload_endpoint_is_picked_up(self):
        printer = make_printer()

        apply(printer, INFO_REPORT)

        assert printer.file_upload_url.endswith("/gcode_upload?s=SIGNED")

    def test_the_capability_map_is_kept(self):
        """The most reliable way to tell models apart without owning one."""
        printer = make_printer()

        apply(printer, INFO_REPORT)

        assert printer.features["fod_support"] is True
        assert printer.features["camera_timelapse_support"] is True
        assert len(printer.features) == 12

    def test_the_firmware_version_is_kept(self):
        printer = make_printer()

        apply(printer, INFO_REPORT)

        assert printer.local_firmware_version == "2.7.2.7"

    def test_fan_and_speed_are_applied(self):
        printer = make_printer()

        apply(printer, INFO_REPORT)

        assert printer._fan_speed == 0
        assert printer._print_speed_mode == 2

    def test_a_chamberless_printer_reports_nothing_for_it(self):
        """A Kobra S1 has no chamber sensor and simply omits the fields."""
        printer = make_printer()

        apply(printer, INFO_REPORT)

        assert printer.chamber_temperature is None

    def test_a_chamber_reading_is_kept_when_present(self):
        printer = make_printer()
        report = {**INFO_REPORT, "data": {**INFO_REPORT["data"]}}
        report["data"]["temp"] = {**report["data"]["temp"], "curr_chamber_temp": 41}

        apply(printer, report)

        assert printer.chamber_temperature == 41

    @pytest.mark.parametrize(
        "missing", ["urls", "features", "temp", "version", "print_speed_mode"]
    )
    def test_a_report_missing_a_block_still_parses(self, missing):
        """Other models will not send all of these."""
        report = {**INFO_REPORT, "data": {**INFO_REPORT["data"]}}
        del report["data"][missing]

        apply(make_printer(), report)

    def test_an_empty_report_is_harmless(self):
        apply(make_printer(), {**INFO_REPORT, "data": {}})

    def test_a_later_report_without_features_keeps_the_known_ones(self):
        printer = make_printer()
        apply(printer, INFO_REPORT)

        stripped = {**INFO_REPORT, "data": {**INFO_REPORT["data"]}}
        del stripped["data"]["features"]
        apply(printer, stripped)

        assert len(printer.features) == 12


class TestAiSettings:
    def test_the_real_report_is_fully_consumed(self):
        apply(make_printer(), AI_SETTINGS_REPORT)

    def test_the_settings_are_kept(self):
        printer = make_printer()

        apply(printer, AI_SETTINGS_REPORT)

        assert printer.ai_settings["count"] == 60
        assert printer.ai_settings["sensitivity_level"] == [1, 1]

    def test_detection_off_reads_false_not_none(self):
        printer = make_printer()

        apply(printer, AI_SETTINGS_REPORT)

        assert printer.ai_detection_enabled is False

    def test_detection_on_reads_true(self):
        printer = make_printer()
        report = {"data": {"ai_settings": {"status": 1}}, **{
            k: v for k, v in AI_SETTINGS_REPORT.items() if k != "data"
        }}

        apply(printer, report)

        assert printer.ai_detection_enabled is True

    def test_an_unseen_printer_reports_nothing(self):
        assert make_printer().ai_detection_enabled is None
        assert make_printer().ai_settings == {}


class TestQueryActionReplies:
    """The cloud pushes these unprompted; locally they answer a query.

    The body is identical either way, so refusing 'query' meant fan and
    temperature reports were discarded over the local connection.
    """

    FAN = {
        "type": "fan",
        "action": "query",
        "state": "done",
        "data": {"aux_fan_speed_pct": 0, "box_fan_level": 0, "fan_speed_pct": 55},
    }
    TEMPERATURE = {
        "type": "tempature",
        "action": "query",
        "state": "done",
        "data": {
            "curr_hotbed_temp": 31,
            "curr_nozzle_temp": 34,
            "curr_chamber_temp": 0,
            "target_hotbed_temp": 0,
            "target_nozzle_temp": 0,
            "target_chamber_temp": 0,
        },
    }

    def test_a_queried_fan_report_is_applied(self):
        printer = make_printer()

        apply(printer, self.FAN)

        assert printer._fan_speed == 55

    def test_a_pushed_fan_report_still_works(self):
        printer = make_printer()

        apply(printer, {**self.FAN, "action": "auto"})

        assert printer._fan_speed == 55

    def test_a_fan_report_without_the_main_speed_does_not_raise(self):
        """Not every model reports all three."""
        apply(make_printer(), {**self.FAN, "data": {"box_fan_level": 2}})

    def test_a_queried_temperature_report_is_applied(self):
        apply(make_printer(), self.TEMPERATURE)
