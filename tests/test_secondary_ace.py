"""The second ACE unit, which the library parsed and then hid.

hass-anycubic #33: a Kobra S1 can take two ACE Pro units and a Kobra X up to
four. The boxes are parsed into a list of whatever the printer reports, and
connected_ace_units counts them correctly -- but only the first two have
accessors, and until now the second had no way to report which slot was
feeding.
"""

from unittest.mock import MagicMock

import pytest

from anycubic_cloud_api.data_models.printer import AnycubicPrinter


def _box(box_id: int, loaded_slot: int = -1) -> dict:
    return {
        "id": box_id, "status": 1, "model_id": 40002, "auto_feed": 0,
        "loaded_slot": loaded_slot, "temp": 25, "slots": [],
    }


def _printer(*boxes: dict) -> AnycubicPrinter:
    return AnycubicPrinter(
        api_parent=MagicMock(), machine_type=20025, machine_name="x", id=1,
        ignore_init_errors=True, multi_color_box=list(boxes) or None,
    )


class TestHowManyBoxesAreSeen:
    @pytest.mark.parametrize("count", [1, 2, 3, 4])
    def test_every_reported_box_is_counted(self, count):
        """Three and four are parsed even though only two are reachable --
        so the count is honest about hardware the accessors cannot reach."""
        printer = _printer(*[_box(i) for i in range(count)])

        assert printer.connected_ace_units == count

    def test_no_boxes_is_zero_not_an_error(self):
        assert _printer().connected_ace_units == 0

    @pytest.mark.parametrize("count", [3, 4])
    def test_more_than_two_boxes_does_not_break_the_accessors(self, count):
        """A four-unit printer must not raise; the extra boxes are merely
        invisible until the entity scheme is indexed rather than named."""
        printer = _printer(*[_box(i) for i in range(count)])

        assert printer.primary_multi_color_box is not None
        assert printer.secondary_multi_color_box is not None


class TestTheSecondBoxCanNameItsLoadedSlot:
    def test_it_reports_the_feeding_slot(self):
        printer = _printer(_box(0, loaded_slot=0), _box(1, loaded_slot=2))

        assert printer.primary_multi_color_box_loaded_slot == 0
        assert printer.secondary_multi_color_box_loaded_slot == 2

    def test_nothing_feeding_is_unknown_not_minus_one(self):
        """-1 is the printer's way of saying nothing is loaded. Reporting it
        as a slot number would put slot -1 on someone's dashboard."""
        printer = _printer(_box(0), _box(1, loaded_slot=-1))

        assert printer.secondary_multi_color_box_loaded_slot is None

    def test_a_single_box_printer_has_no_second_slot(self):
        printer = _printer(_box(0, loaded_slot=1))

        assert printer.secondary_multi_color_box_loaded_slot is None

    def test_no_ace_at_all_is_not_an_error(self):
        assert _printer().secondary_multi_color_box_loaded_slot is None


class TestStoppingTheDryer:
    """hass-anycubic #39: stopping the second ACE's dryer did nothing.

    The stop order named no box, and the sender numbers unnamed boxes by
    position, so every single-box stop went to box 0.
    """

    async def _sent_boxes(self, **kwargs):
        from unittest.mock import AsyncMock

        from anycubic_cloud_api.anycubic_api import AnycubicAPI

        api = AnycubicAPI(session=MagicMock(), cookie_jar=MagicMock())
        api._send_anycubic_order = AsyncMock(return_value="msgid")
        printer = _printer(_box(0), _box(1))

        await api.multi_color_box_drying_stop(printer, **kwargs)

        order = api._send_anycubic_order.await_args.kwargs["order_request"]
        return order.order_data["multi_color_box"]

    async def test_the_second_box_is_the_one_stopped(self):
        boxes = await self._sent_boxes(box_id=1)

        assert [box["id"] for box in boxes] == [1]
        assert boxes[0]["drying_status"]["status"] == 0

    async def test_the_first_box_is_still_stopped_by_name(self):
        boxes = await self._sent_boxes(box_id=0)

        assert [box["id"] for box in boxes] == [0]

    async def test_no_box_named_stops_every_box(self):
        boxes = await self._sent_boxes()

        assert [box["id"] for box in boxes] == [0, 1]
