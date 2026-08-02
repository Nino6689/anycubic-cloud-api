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
