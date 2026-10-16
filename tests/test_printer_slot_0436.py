"""The printer's own loaded slot, and logs safe to paste (0.4.36).

From a Kobra X printing from slot 4 (#34): the sensor flipped to 2 mid-print
with no message from the printer. Each cloud poll rebuilt the box from the
cloud's record, whose loaded slot was stale. The printer also names the
feeding slot itself in its extfilbox report, and its PrintStart report put
the printer's cn_code into the debug log.
"""

import pytest
from test_filament_change_0435 import (
    KOBRA_S1,
    KOBRA_X,
    box,
    make_printer,
    message,
    topic,
)

from anycubic_cloud_api.helpers.helpers import redact_for_log


def cloud_info(boxes, machine_type=KOBRA_X):
    return {
        "id": 1, "name": "Printer", "key": "k", "machine_type": machine_type, "model": "Printer",
        "img": "", "device_status": 1, "is_printing": 2, "type_function_ids": [], "version": None,
        "multi_color_box": boxes,
    }


def stale_box(box_id, loaded_slot):
    b = box(box_id)
    b["loaded_slot"] = loaded_slot
    return b


def loaded(printer):
    return [b.loaded_slot for b in printer.multi_color_box]


class TestCloudPollKeepsThePrintersSlot:
    def test_a_slot_the_printer_reported_survives_a_cloud_poll(self):
        printer = make_printer([box(0)])
        printer.multi_color_box[0].set_slot_loaded(3)

        printer.update_from_info_json(cloud_info([stale_box(0, 1)]))

        assert loaded(printer) == [3]

    def test_without_a_printer_report_the_cloud_value_is_used(self):
        printer = make_printer([box(0)])

        printer.update_from_info_json(cloud_info([stale_box(0, 1)]))

        assert loaded(printer) == [1]

    def test_the_next_printer_report_still_wins(self):
        printer = make_printer([box(0)])
        printer.multi_color_box[0].set_slot_loaded(3)
        printer.update_from_info_json(cloud_info([stale_box(0, 1)]))

        printer.multi_color_box[0].set_slot_loaded(0)

        assert loaded(printer) == [0]

    def test_each_box_keeps_its_own(self):
        printer = make_printer([box(0), box(1)], machine_type=KOBRA_S1)
        printer.multi_color_box[1].set_slot_loaded(2)

        printer.update_from_info_json(cloud_info([stale_box(0, 1), stale_box(1, 0)], machine_type=KOBRA_S1))

        assert loaded(printer) == [1, 2]

    def test_other_cloud_fields_still_update(self):
        printer = make_printer([box(0)])
        printer.multi_color_box[0].set_slot_loaded(3)
        refreshed = stale_box(0, 1)
        refreshed["temp"] = 33

        printer.update_from_info_json(cloud_info([refreshed]))

        assert printer.multi_color_box[0].current_temperature == 33


def extfilbox(printer, current_filament, machine_type=KOBRA_X):
    printer.process_mqtt_update(
        topic(machine_type, "extfilbox"),
        message("extfilbox", "auto", "done", {"current_filament": current_filament}),
    )


class TestCurrentFilament:
    @pytest.mark.parametrize(("reading", "slot"), [("0-3", 3), ("0-0", 0)])
    def test_one_box_follows_the_printer(self, reading, slot):
        printer = make_printer([box(0)])

        extfilbox(printer, reading)

        assert loaded(printer) == [slot]

    @pytest.mark.parametrize("reading", ["", None, "0-9", "1-2", "x", "0-", "-1"])
    def test_a_retract_or_unknown_reading_keeps_the_slot(self, reading):
        printer = make_printer([box(0)])
        printer.multi_color_box[0].set_slot_loaded(3)

        extfilbox(printer, reading)

        assert loaded(printer) == [3]

    def test_with_two_boxes_nothing_is_guessed(self):
        printer = make_printer([box(0), box(1)])

        extfilbox(printer, "0-3")

        assert loaded(printer) == [-1, -1]

    def test_it_survives_the_next_cloud_poll(self):
        printer = make_printer([box(0)])
        extfilbox(printer, "0-3")

        printer.update_from_info_json(cloud_info([stale_box(0, 1)]))

        assert loaded(printer) == [3]


class TestRedactForLog:
    def test_printer_identifiers_are_redacted_wherever_they_are(self):
        payload = {"type": "buried", "data": {"cn_code": "CN123", "nested": [{"machine_mac": "AA:BB"}], "ip": "10.0.0.2"}}

        assert redact_for_log(payload) == {
            "type": "buried",
            "data": {"cn_code": "**REDACTED**", "nested": [{"machine_mac": "**REDACTED**"}], "ip": "**REDACTED**"},
        }

    @pytest.mark.parametrize("key", ["token", "casdoor_user_token", "rtc_token", "app_secret", "password"])
    def test_credentials_are_redacted(self, key):
        assert redact_for_log({key: "secret-value"}) == {key: "**REDACTED**"}

    def test_ordinary_fields_and_empty_values_pass_through(self):
        payload = {"progress": 42, "taskid": "131448158", "cn_code": "", "state": "printing", "slots": [1, 2]}

        assert redact_for_log(payload) == payload

    def test_the_input_is_not_changed(self):
        payload = {"data": {"cn_code": "CN123"}}

        redact_for_log(payload)

        assert payload == {"data": {"cn_code": "CN123"}}
