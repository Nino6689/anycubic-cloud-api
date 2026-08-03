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


class TestAvailabilityFromLocalReports:
    """With no cloud, nothing else sets the fields availability is read from."""

    def test_a_report_marks_the_printer_online(self):
        printer = make_printer()

        apply(printer, INFO_REPORT)

        assert printer.printer_online is True

    def test_free_reads_as_available_and_not_busy(self):
        printer = make_printer()

        apply(printer, INFO_REPORT)

        assert printer.is_available is True
        assert printer.is_busy is False

    def test_busy_reads_as_busy(self):
        printer = make_printer()
        report = {**INFO_REPORT, "data": {**INFO_REPORT["data"], "state": "busy"}}

        apply(printer, report)

        assert printer.is_busy is True

    def test_an_unknown_state_leaves_it_alone(self):
        printer = make_printer()
        report = {**INFO_REPORT, "data": {**INFO_REPORT["data"], "state": "wat"}}

        apply(printer, report)

        assert printer.printer_online is True


class TestTemperaturesWithoutTheCloud:
    """The cloud builds the temperature holder; a local-only printer has none."""

    def test_an_info_report_creates_it(self):
        printer = make_printer()

        apply(printer, INFO_REPORT)

        assert printer.parameter is not None
        assert printer.curr_nozzle_temp == 34
        assert printer.curr_hotbed_temp == 31

    def test_a_temperature_report_creates_it(self):
        printer = make_printer()

        apply(printer, TestQueryActionReplies.TEMPERATURE)

        assert printer.curr_nozzle_temp == 34

    def test_later_reports_update_it(self):
        printer = make_printer()
        apply(printer, INFO_REPORT)

        hotter = {**INFO_REPORT, "data": {**INFO_REPORT["data"]}}
        hotter["data"]["temp"] = {**hotter["data"]["temp"], "curr_nozzle_temp": 210}
        apply(printer, hotter)

        assert printer.curr_nozzle_temp == 210

    def test_a_report_without_temperatures_leaves_it_alone(self):
        printer = make_printer()
        report = {**INFO_REPORT, "data": {**INFO_REPORT["data"]}}
        del report["data"]["temp"]

        apply(printer, report)

        assert printer.parameter is None


class TestWhatTheCloudWouldHaveSaid:
    """Two facts only the cloud states, which entity filtering depends on.

    Without them every filament entity is filtered out as belonging to a
    different kind of machine, and every ACE entity as unsupported -- so a
    printer reached locally ends up with almost no entities at all.
    """

    def test_an_fdm_device_type_means_filament(self):
        printer = make_printer()

        printer.set_material_type_from_device_type("fdm")

        assert str(printer.material_type) == "Filament"

    @pytest.mark.parametrize("device_type", ["lcd", "dlp", "resin", "LCD"])
    def test_a_resin_device_type_means_resin(self, device_type):
        printer = make_printer()

        printer.set_material_type_from_device_type(device_type)

        assert str(printer.material_type) == "Resin"

    @pytest.mark.parametrize("device_type", [None, "", "something-new"])
    def test_an_unknown_device_type_leaves_it_unset(self, device_type):
        """Better unset than wrong -- a wrong guess hides the right entities."""
        printer = make_printer()

        printer.set_material_type_from_device_type(device_type)

        assert printer.material_type is None

    def test_the_cloud_wins_when_it_has_already_spoken(self):
        printer = AnycubicPrinter(
            api_parent=MagicMock(),
            machine_type=20025,
            machine_name="x",
            id=1,
            material_type="resin",
            ignore_init_errors=True,
        )

        printer.set_material_type_from_device_type("fdm")

        assert str(printer.material_type) == "Resin"

    def test_a_reported_box_means_the_printer_supports_one(self):
        """The cloud's function list is absent on a local connection."""
        printer = AnycubicPrinter(
            api_parent=MagicMock(),
            machine_type=20025,
            machine_name="x",
            id=1,
            multi_color_box=[{"id": 0, "box_id": 0, "slots": []}],
            ignore_init_errors=True,
        )

        assert printer.connected_ace_units == 1
        assert printer.supports_function_multi_color_box is True

    def test_no_box_means_no_support(self):
        printer = make_printer()

        assert printer.connected_ace_units == 0
        assert printer.supports_function_multi_color_box is False

    def test_the_cloud_function_list_still_counts_with_no_box_attached(self):
        """A supported-but-detached ACE must not read as unsupported."""
        printer = AnycubicPrinter(
            api_parent=MagicMock(),
            machine_type=20025,
            machine_name="x",
            id=1,
            type_function_ids=[2006],
            ignore_init_errors=True,
        )

        assert printer.supports_function_multi_color_box is True


class TestLevellingStatus:
    """Upstream issue #55: job state read 'unknown' while the printer levelled.

    The status enum stopped at 7, so code 9 fell through as unrecognised.
    """

    def test_levelling_is_a_known_status(self):
        from anycubic_cloud_api.const.enums import AnycubicPrintStatus

        assert AnycubicPrintStatus(9).name == "Levelling"

    def test_the_existing_statuses_are_unchanged(self):
        """Their numbers are on the wire; renumbering would break history."""
        from anycubic_cloud_api.const.enums import AnycubicPrintStatus

        assert [(s.name, s.value) for s in AnycubicPrintStatus] == [
            ("Printing", 1),
            ("Complete", 2),
            ("Cancelled", 3),
            ("Downloading", 4),
            ("Checking", 5),
            ("Preheating", 6),
            ("Slicing", 7),
            ("Levelling", 9),
        ]


class TestLevellingReadsAsLevelling:
    """The job state should say what the printer is doing, not "unknown"."""

    def _status(self, code, reported=None):
        from anycubic_cloud_api.data_models.project import AnycubicProject

        class Stub(AnycubicProject):
            """Only the two inputs print_status reads, so no full project."""

            __slots__ = ("_reported",)

            def __init__(self, code, reported):
                self._print_status = code
                self._reported = reported

            @property
            def print_is_paused(self):
                return False

            def _get_print_setting(self, key):
                return self._reported if key == "state" else None

        return Stub(code, reported).print_status

    def test_levelling(self):
        assert self._status(9) == "levelling"

    def test_printing_is_unaffected(self):
        assert self._status(1) == "printing"

    def test_an_unmapped_code_prefers_the_printers_own_words(self):
        assert self._status(99, reported="calibrating") == "calibrating"

    def test_an_unmapped_code_with_no_text_is_unknown(self):
        assert self._status(99) == "unknown"


class TestLoadedSlotFallback:
    """Some printers leave the box-level loaded_slot at -1 while printing.

    Observed live on a Kobra S1 feeding from slot 3: the box reported -1, but
    the slot's own status was 5 (loaded). Filament used by such a job could not
    be charged to any spool, because attribution falls back on this value when
    the job carries no per-slot breakdown.
    """

    def _printer(self, loaded_slot, statuses):
        from unittest.mock import MagicMock
        from anycubic_cloud_api.data_models.printer import AnycubicPrinter

        slots = [
            {
                "index": i,
                "sku": "",
                "type": "PLA",
                "color": [1, 2, 3],
                "status": st,
                "edit_status": 1,
            }
            for i, st in enumerate(statuses)
        ]
        return AnycubicPrinter(
            api_parent=MagicMock(),
            machine_type=20025,
            machine_name="Kobra S1",
            id=1,
            multi_color_box=[{"id": 0, "box_id": 0, "loaded_slot": loaded_slot, "slots": slots}],
            ignore_init_errors=True,
        )

    def test_the_box_level_field_is_preferred_when_it_is_set(self):
        printer = self._printer(1, [4, 5, 4, 4])

        assert printer.primary_multi_color_box_loaded_slot == 1

    def test_minus_one_falls_back_to_the_slot_marked_loaded(self):
        """The live case: box says -1, slot 2 says status 5."""
        printer = self._printer(-1, [4, 4, 5, 4])

        assert printer.primary_multi_color_box_loaded_slot == 2

    def test_nothing_loaded_still_reads_as_unknown(self):
        printer = self._printer(-1, [4, 4, 4, 4])

        assert printer.primary_multi_color_box_loaded_slot is None

    def test_a_box_with_no_slots_is_harmless(self):
        from unittest.mock import MagicMock
        from anycubic_cloud_api.data_models.printer import AnycubicPrinter

        printer = AnycubicPrinter(
            api_parent=MagicMock(), machine_type=20025, machine_name="x", id=1,
            multi_color_box=[{"id": 0, "box_id": 0, "loaded_slot": -1, "slots": []}],
            ignore_init_errors=True,
        )

        assert printer.primary_multi_color_box_loaded_slot is None
