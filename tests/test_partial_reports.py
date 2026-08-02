"""Reports that carry only part of the picture.

Both cases here were losing data on hardware other than the development
machine: a second ACE unit vanishing, and a print update thrown away whole
because one temperature field was absent.
"""

from unittest.mock import MagicMock

import pytest

from anycubic_cloud_api.data_models.consumable import AnycubicConsumableData
from anycubic_cloud_api.data_models.printer import AnycubicPrinter


def slot(index=0):
    return {
        "index": index,
        "sku": "",
        "type": "PLA",
        "color": [1, 2, 3],
        "status": 5,
        "edit_status": 1,
    }


def box(box_id):
    return {"id": box_id, "box_id": box_id, "slots": [slot()]}


def make_printer(boxes):
    return AnycubicPrinter(
        api_parent=MagicMock(),
        machine_type=20025,
        machine_name="Kobra S1",
        id=1,
        multi_color_box=boxes,
        ignore_init_errors=True,
    )


class TestTwoAceUnits:
    def test_a_report_about_one_box_keeps_the_other(self):
        """Updates often name only the box that changed."""
        printer = make_printer([box(0), box(1)])

        printer._set_multi_color_box([box(0)])

        assert printer._multi_color_box is not None
        assert [b.box_id for b in printer._multi_color_box] == [0, 1]

    def test_the_reported_box_is_the_one_that_gets_updated(self):
        printer = make_printer([box(0), box(1)])
        changed = box(1)
        changed["slots"] = [{**slot(0), "type": "PETG"}]

        printer._set_multi_color_box([changed])

        assert printer._multi_color_box is not None
        by_id = {b.box_id: b for b in printer._multi_color_box}
        assert by_id[1].slots[0].material_type == "PETG"
        assert by_id[0].slots[0].material_type == "PLA"

    def test_a_full_report_still_replaces_the_list(self):
        printer = make_printer([box(0), box(1)])

        printer._set_multi_color_box([box(2), box(3)])

        assert printer._multi_color_box is not None
        assert [b.box_id for b in printer._multi_color_box] == [2, 3]

    def test_a_single_box_printer_is_unaffected(self):
        printer = make_printer([box(0)])

        printer._set_multi_color_box([box(0)])

        assert printer._multi_color_box is not None
        assert len(printer._multi_color_box) == 1

    def test_boxes_being_removed_entirely_is_still_honoured(self):
        printer = make_printer([box(0), box(1)])

        printer._set_multi_color_box(None)

        assert printer._multi_color_box is None


class TestPartialPrintUpdates:
    """A missing key used to lose the entire update."""

    def _printer(self):
        # __slots__ rules out patching the method, so record it in a subclass.
        class RecordingPrinter(AnycubicPrinter):
            __slots__ = ("target_temp_calls",)

            def _update_latest_project_target_temps(self, *args):
                self.target_temp_calls.append(args)

        printer = RecordingPrinter(
            api_parent=MagicMock(),
            machine_type=20025,
            machine_name="Kobra S1",
            id=1,
            multi_color_box=[box(0)],
            ignore_init_errors=True,
        )
        printer.target_temp_calls = []

        return printer

    def _update(self, printer, data):
        printer._process_mqtt_update_print(
            "update",
            "updated",
            AnycubicConsumableData({"data": {"taskid": 1, **data}}),
        )

    @pytest.mark.parametrize(
        "data",
        [
            {},
            {"settings": {}},
            {"curr_hotbed_temp": 60},
            {"settings": {"fan_speed_pct": 100}},
            {"settings": {"target_hotbed_temp": 60}},
            {"curr_hotbed_temp": 60, "curr_nozzle_temp": 210},
        ],
    )
    def test_a_partial_update_does_not_raise(self, data):
        self._update(self._printer(), data)

    def test_the_fields_that_are_present_are_still_applied(self):
        printer = self._printer()

        self._update(printer, {"settings": {"fan_speed_pct": 80}})

        assert printer._fan_speed == 80

    def test_target_temps_are_set_only_when_both_are_present(self):
        printer = self._printer()

        self._update(printer, {"settings": {"target_hotbed_temp": 60}})
        assert printer.target_temp_calls == []

        self._update(
            printer,
            {"settings": {"target_hotbed_temp": 60, "target_nozzle_temp": 210}},
        )
        assert len(printer.target_temp_calls) == 1
