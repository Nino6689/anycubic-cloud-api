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

    def test_an_unexpected_action_is_reported(self):
        from anycubic_cloud_api import AnycubicMQTTUnknownUpdate

        printer = self._printer()

        with pytest.raises(AnycubicMQTTUnknownUpdate):
            printer.process_mqtt_update(
                "a/b/c/d/e/f/g/axis/report", self._msg(action="move")
            )


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
