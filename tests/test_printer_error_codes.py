"""Tests for the printer's error codes.

Requested in hass-anycubic issue #21: a Kobra X owner wanted the code the
printer puts on its own screen -- 11858 when slot 4 runs out -- available to
automate on.

The maintainer's first answer was that the envelope's `code` is always 200 and
publishing it would give a sensor stuck at 200 forever. That was wrong, and the
reporter said so: 200 is what it reads *while nothing is wrong*. A fault puts a
real code there. These tests pin the corrected behaviour.
"""

from unittest.mock import MagicMock

import pytest

from anycubic_cloud_api.const.error_codes import (
    PRINTER_ERROR_CODES,
    describe_printer_code,
)
from anycubic_cloud_api.data_models.consumable import AnycubicConsumableData
from anycubic_cloud_api.data_models.printer import AnycubicPrinter


class TestTheCodeTable:
    def test_anycubics_own_wording_is_used(self):
        """Straight from wiki.anycubic.com, so a search for it finds the page."""
        assert describe_printer_code(10107) == "Filament broken"

    def test_an_unpublished_code_is_reported_as_itself(self):
        """11858 is the reporter's own code and is not on the wiki.

        A number they can search beats a label that might be wrong.
        """
        assert 11858 not in PRINTER_ERROR_CODES
        assert describe_printer_code(11858) == "Unknown error code 11858"


class TestRecordingTheCode:
    def _printer(self):
        return AnycubicPrinter(
            api_parent=MagicMock(), machine_type=20025, machine_name="x",
            id=1, ignore_init_errors=True,
        )

    def _msg(self, **over):
        return AnycubicConsumableData({
            "type": "event", "action": "report", "state": "done", **over,
        })

    def test_a_healthy_printer_records_nothing(self):
        """The whole objection to the original request: 200 is not a fault."""
        printer = self._printer()

        printer.process_mqtt_update("a/b/c/d/e/f/g/event/report", self._msg(code=200))

        assert printer.latest_error_code is None
        assert printer.latest_error_description is None

    @pytest.mark.parametrize("ok_code", [0, 200])
    def test_neither_of_the_ok_codes_counts(self, ok_code):
        printer = self._printer()

        printer.process_mqtt_update("a/b/c/d/e/f/g/event/report", self._msg(code=ok_code))

        assert printer.latest_error_code is None

    def test_a_fault_is_kept_with_anycubics_wording(self):
        printer = self._printer()

        printer.process_mqtt_update(
            "a/b/c/d/e/f/g/event/report", self._msg(code=10107, msg="filament")
        )

        assert printer.latest_error_code == 10107
        assert printer.latest_error_description == "Filament broken"
        assert printer.latest_error_message == "filament"

    def test_the_reporters_own_code_survives_unnamed(self):
        printer = self._printer()

        printer.process_mqtt_update("a/b/c/d/e/f/g/event/report", self._msg(code=11858))

        assert printer.latest_error_code == 11858
        assert printer.latest_error_description == "Unknown error code 11858"

    def test_a_later_healthy_message_does_not_erase_the_fault(self):
        """Faults are announced once. Losing it on the next heartbeat would
        make the entity useless for automating on."""
        printer = self._printer()

        printer.process_mqtt_update("a/b/c/d/e/f/g/event/report", self._msg(code=10107))
        printer.process_mqtt_update("a/b/c/d/e/f/g/event/report", self._msg(code=200))

        assert printer.latest_error_code == 10107

    def test_a_code_survives_a_message_that_cannot_be_parsed(self):
        """The case that decides where the code is read.

        A fault is exactly when an unfamiliar payload turns up, and a handler
        that cannot make sense of its message raises -- so anything read after
        the dispatch never runs. Here the print handler rejects the message
        outright, and the code still has to have been kept.
        """
        from anycubic_cloud_api.exceptions.exceptions import (
            AnycubicMQTTUnknownUpdate,
        )

        printer = self._printer()

        with pytest.raises(AnycubicMQTTUnknownUpdate):
            printer.process_mqtt_update(
                "a/b/c/d/e/f/g/print/report",
                AnycubicConsumableData({
                    "type": "print", "action": "update",
                    "state": "failed", "code": 10111,
                }),
            )

        assert printer.latest_error_code == 10111
        assert printer.latest_error_description == "Task abnormally ended"

    def test_a_non_numeric_code_is_ignored(self):
        printer = self._printer()

        printer.process_mqtt_update("a/b/c/d/e/f/g/event/report", self._msg(code="oops"))

        assert printer.latest_error_code is None


class TestEventMessagesAreUnderstood:
    """Before this, `type: event` hit the dispatcher's else branch, raised
    AnycubicMQTTUnknownUpdate, and the entire message was discarded with only a
    "Message not understood" line in the debug log. That is where the Kobra X's
    run-out was going."""

    def _printer(self):
        return AnycubicPrinter(
            api_parent=MagicMock(), machine_type=20025, machine_name="x",
            id=1, ignore_init_errors=True,
        )

    @pytest.mark.parametrize("type_name", ["event", "printerevent", "printer_event"])
    def test_an_event_message_no_longer_raises(self, type_name):
        printer = self._printer()

        printer.process_mqtt_update(
            "a/b/c/d/e/f/g/event/report",
            AnycubicConsumableData({
                "type": type_name, "action": "report", "state": "done", "code": 10107,
            }),
        )

        assert printer.latest_error_code == 10107

    def test_the_payload_is_fully_consumed(self):
        """Anything left behind raises AnycubicMQTTUnhandledData at the end of
        dispatch -- which is how the real payload shape gets learned."""
        printer = self._printer()
        payload = AnycubicConsumableData({
            "type": "event", "action": "report", "state": "done", "code": 10107,
            "data": {"code": 10107, "msg": "x", "msgid": "1", "state": "s", "action": "a"},
        })

        printer.process_mqtt_update("a/b/c/d/e/f/g/event/report", payload)

        assert payload.is_empty, f"left behind: {payload.remaining_data}"
