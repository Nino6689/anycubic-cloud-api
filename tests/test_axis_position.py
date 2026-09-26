"""Tests for the axis-position query.

Order 1214 is undocumented -- found by sweeping the gaps in AnycubicOrderID
against real hardware -- so these pin the reply shape it actually returns.
"""

from unittest.mock import MagicMock

import pytest

from anycubic_cloud_api import AnycubicAxisPosition
from anycubic_cloud_api.data_models.consumable import AnycubicConsumableData
from anycubic_cloud_api.data_models.printer import AnycubicPrinter


class TestParsing:
    def test_the_real_reply_shape(self):
        """Captured verbatim from a Kobra S1."""
        pos = AnycubicAxisPosition.from_json(
            {"coordinates": {"x": 47, "y": 276, "z": 3.8152532726237904}}
        )

        assert (pos.x, pos.y) == (47.0, 276.0)
        assert pos.z == pytest.approx(3.815, abs=0.001)

    def test_a_bare_dict_also_parses(self):
        assert AnycubicAxisPosition.from_json({"x": 1, "y": 2, "z": 3}).x == 1.0

    @pytest.mark.parametrize(
        "junk",
        [None, {}, {"coordinates": {}}, {"coordinates": {"x": 1}}, {"coordinates": "nope"}],
    )
    def test_unusable_input_yields_none(self, junk):
        """Better no reading than a wrong one."""
        assert AnycubicAxisPosition.from_json(junk) is None


class TestMqttDispatch:
    def _printer(self):
        return AnycubicPrinter(
            api_parent=MagicMock(), machine_type=20025, machine_name="x",
            id=1, ignore_init_errors=True,
        )

    def _msg(self, **over):
        return AnycubicConsumableData({
            "type": "axis", "action": "query", "state": "done",
            "data": {"coordinates": {"x": 47, "y": 276, "z": 3.8}},
            **over,
        })

    def test_a_reply_updates_the_printer(self):
        printer = self._printer()
        assert printer.axis_position is None

        printer.process_mqtt_update("a/b/c/d/e/f/g/axis/report", self._msg())

        assert printer.axis_position.x == 47.0

    def test_the_payload_is_fully_consumed(self):
        """Nested payloads are only released once emptied; anything left behind
        raises AnycubicMQTTUnhandledData at the end of dispatch. This caught a
        real bug where `coordinates` was read but never released."""
        printer = self._printer()
        payload = self._msg()

        printer.process_mqtt_update("a/b/c/d/e/f/g/axis/report", payload)

        assert payload.is_empty, f"left behind: {payload.remaining_data}"

    def test_a_reply_without_coordinates_is_harmless(self):
        """A Kobra X answers the query with no coordinates mid-print (#38)."""
        printer = self._printer()
        payload = self._msg(data={})

        printer.process_mqtt_update("a/b/c/d/e/f/g/axis/report", payload)

        assert printer.axis_position is None

    def test_an_unexpected_action_is_reported(self):
        from anycubic_cloud_api import AnycubicMQTTUnknownUpdate

        printer = self._printer()

        with pytest.raises(AnycubicMQTTUnknownUpdate):
            printer.process_mqtt_update(
                "a/b/c/d/e/f/g/axis/report", self._msg(action="somethingelse")
            )

    def test_a_move_report_marks_the_motion_finished(self):
        """The only completion signal a jog or a home ever gives.

        It carries no coordinates -- `data` is null -- so a position still
        has to be asked for separately.
        """
        printer = self._printer()
        # A real move report carries no data at all.
        payload = self._msg(action="move", data=None)

        printer.process_mqtt_update("a/b/c/d/e/f/g/axis/report", payload)

        assert printer.axis_move_state == "done"
        assert printer.axis_is_moving is False
        assert payload.is_empty, f"left behind: {payload.remaining_data}"


class TestCloudFileSummary:
    """The summary consumers see for a cloud file.

    It previously carried only name and size, so there was no way to preview a
    file or judge what printing it would cost — despite all of it already being
    in the payload.
    """

    def _file(self, **over):
        from anycubic_cloud_api.data_models.files import AnycubicCloudFile

        base = dict(
            id=78443457, user_id=1, post_id=1, filename="x.3mf", time=0, size=1_311_364,
            status=1, ip="", old_filename="cup.gcode.3mf", img_status=1, device_type=1,
            file_type=1, url="https://example/x.3mf",
            thumbnail="https://example/preview.png", is_delete=0, update_time=0, uuid="u",
            size_x=100.0, size_y=80.0, size_z=42.5, estimate=13338,
            material_name="PETG", layer_height=0.2, supplies_usage=20773,
        )
        base.update(over)
        return AnycubicCloudFile(**base)

    def test_the_summary_carries_what_a_picker_needs(self):
        d = self._file().data_object

        assert d["name"] == "cup.gcode.3mf"
        assert d["thumbnail"] == "https://example/preview.png"
        assert d["estimate_seconds"] == 13338
        assert d["material"] == "PETG"
        assert d["layer_height"] == 0.2
        assert d["filament_mm"] == 20773
        assert d["dimensions"] == {"x": 100.0, "y": 80.0, "z": 42.5}

    def test_size_is_still_reported_in_mb(self):
        assert self._file().data_object["size_mb"] == pytest.approx(1.311, abs=0.001)

    def test_a_file_without_a_preview_reports_none(self):
        """An empty string would render as a broken image."""
        assert self._file(thumbnail="").data_object["thumbnail"] is None

    def test_missing_dimensions_report_none_not_a_partial_box(self):
        assert self._file(size_x=None).data_object["dimensions"] is None


class TestAceParsingTolerance:
    """An ACE that reports fewer keys must still be detected.

    Reported on a Kobra 3 V2 with an external ACE Pro (issue #3): the printer
    advertised MULTI_COLOR_BOX yet no ACE device appeared. The parser demanded
    nine keys, and one missing key raised — which the printer setup swallowed,
    leaving an empty ACE list indistinguishable from a printer with no ACE.
    """

    SLOTS = [{"index": 0, "sku": "", "type": "PLA", "color": [1, 2, 3],
              "status": 5, "edit_status": 1}]

    def _printer(self, box, logs=None):
        from unittest.mock import MagicMock

        from anycubic_cloud_api.data_models.printer import AnycubicPrinter

        parent = MagicMock()
        if logs is not None:
            parent._log_to_warn = logs.append
        return AnycubicPrinter(
            api_parent=parent, machine_type=20027, machine_name="x", id=7,
            multi_color_box=box, ignore_init_errors=True,
        )

    def test_a_full_payload_still_parses(self):
        """The shape a Kobra S1 sends, unchanged."""
        box = [{
            "id": 1, "status": 1, "temp": 33, "humidity": 0.0, "model_id": 40001,
            "auto_feed": 1, "loaded_slot": -1,
            "feed_status": {"code": 200, "type": -1, "current_status": -1, "slot_index": -1},
            "drying_status": {"status": 0, "duration": 0, "target_temp": 0, "remain_time": 0},
            "slots": self.SLOTS,
        }]

        assert self._printer(box).connected_ace_units == 1

    def test_only_id_and_slots_are_required(self):
        """Everything else is reported inconsistently across models."""
        printer = self._printer([{"id": 0, "slots": self.SLOTS}])

        assert printer.connected_ace_units == 1
        assert printer.primary_multi_color_box_spool_info_object[0]["material_type"] == "PLA"

    def test_no_ace_is_still_no_ace(self):
        assert self._printer(None).connected_ace_units == 0

    def test_an_unparseable_payload_says_so(self):
        """Silence here reads as 'no ACE attached' and wastes everyone's time."""
        logs: list = []
        printer = self._printer([{"no_id_at_all": True}], logs=logs)

        assert printer.connected_ace_units == 0
        assert logs, "a payload that cannot be parsed must leave a trace"
        assert "multi_color_box" in logs[0]
