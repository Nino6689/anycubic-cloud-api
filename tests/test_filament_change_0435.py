"""Filament-change reports and the ACE 2 Pro's drying report (0.4.35).

From a Kobra X with an ACE 2 Pro (#33). Each step of a filament change
arrives as a print ``start`` naming ``channel_no``, counted from 1 within
its box, plus ``unit_no`` when the feed comes from an ACE. These were
dropped as unhandled. The ACE 2 Pro's periodic drying report has no
``temp``, and reading it raised every six minutes.
"""

from unittest.mock import MagicMock

import pytest

from anycubic_cloud_api.data_models.consumable import AnycubicConsumableData
from anycubic_cloud_api.data_models.printer import AnycubicPrinter

KOBRA_X = 20030
KOBRA_S1 = 20025


def slot(index):
    return {"index": index, "sku": "", "type": "PLA", "color": [1, 2, 3], "status": 5, "edit_status": 1}


def box(box_id, slots=4):
    return {"id": box_id, "loaded_slot": -1, "temp": 21, "slots": [slot(i) for i in range(slots)]}


def make_printer(boxes, machine_type=KOBRA_X):
    return AnycubicPrinter(
        api_parent=MagicMock(),
        machine_type=machine_type,
        machine_name="Printer",
        id=1,
        multi_color_box=boxes,
        ignore_init_errors=True,
    )


def message(msg_type, action, state, data):
    return AnycubicConsumableData({
        "type": msg_type, "action": action, "state": state,
        "code": 200, "msg": "done", "msgid": "m", "timestamp": 1, "data": data,
    })


def topic(machine_type, kind):
    return f"anycubic/anycubicCloud/v1/printer/public/{machine_type}/key/{kind}/report"


def feed(printer, state, channel_no, unit_no=None, machine_type=KOBRA_X):
    data = {"channel_no": channel_no, "taskid": "t"}
    if unit_no is not None:
        data["unit_no"] = unit_no
    printer.process_mqtt_update(topic(machine_type, "print"), message("print", "start", state, data))


def loaded(printer):
    return [b.loaded_slot for b in printer.multi_color_box]


class TestFilamentChange:
    @pytest.mark.parametrize(("state", "unit_no"), [
        ("extfilbox_filament_feeding", None),
        ("ace_filament_feeding", 1),
    ])
    def test_one_box_follows_the_feed(self, state, unit_no):
        printer = make_printer([box(0)])

        feed(printer, state, 3, unit_no)

        assert loaded(printer) == [2]

    @pytest.mark.parametrize("state", [
        "extfilbox_filament_unfeeding", "ace_filament_unfeeding", "nozzle_purging",
    ])
    def test_other_steps_are_read_but_change_nothing(self, state):
        """Consumed, so not logged as unhandled; only a feed says what is loaded."""
        printer = make_printer([box(0)])
        printer.multi_color_box[0].set_slot_loaded(1)

        feed(printer, state, 3, 1)

        assert loaded(printer) == [1]

    @pytest.mark.parametrize(("unit_no", "expected"), [(1, [1, -1]), (2, [-1, 1])])
    def test_an_ace_unit_picks_its_box_on_a_printer_of_aces(self, unit_no, expected):
        """A Kobra S1 has no feeder of its own: unit 1 is the first ACE."""
        printer = make_printer([box(0), box(1)], machine_type=KOBRA_S1)

        feed(printer, "ace_filament_feeding", 2, unit_no, machine_type=KOBRA_S1)

        assert loaded(printer) == expected

    @pytest.mark.parametrize(("state", "unit_no"), [
        ("extfilbox_filament_feeding", None),
        ("ace_filament_feeding", 1),
    ])
    def test_a_kobra_x_with_an_ace_guesses_nothing(self, state, unit_no):
        """Which list entry is the Kobra X's own feeder is unconfirmed (#33)."""
        printer = make_printer([box(0), box(1)])

        feed(printer, state, 1, unit_no)

        assert loaded(printer) == [-1, -1]

    @pytest.mark.parametrize(("channel_no", "unit_no"), [(5, 1), (0, 1), (2, 3), ("x", 1), (2, None)])
    def test_a_channel_or_unit_that_fits_no_box_changes_nothing(self, channel_no, unit_no):
        printer = make_printer([box(0), box(1)], machine_type=KOBRA_S1)

        feed(printer, "ace_filament_feeding", channel_no, unit_no, machine_type=KOBRA_S1)

        assert loaded(printer) == [-1, -1]


class TestAce2ProDryingReport:
    REPORT = {"multi_color_box": [{
        "drying_status": {"duration": 14400, "humidity": 28, "remain_time": 162, "status": 1, "target_temp": 50},
        "id": 0,
    }]}

    def test_a_report_without_temp_still_updates_drying(self):
        printer = make_printer([box(0)])

        printer.process_mqtt_update(
            topic(KOBRA_X, "multiColorBox"),
            message("multiColorBox", "autoUpdateDryStatus", "success", self.REPORT),
        )

        ace = printer.multi_color_box[0]
        assert ace.drying_status.is_drying
        assert ace.drying_status.target_temperature == 50
        assert ace.current_temperature == 21  # the last reading is kept
