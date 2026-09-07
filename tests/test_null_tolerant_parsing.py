"""Nulls in the cloud payload must not cost the caller the printer.

Reported as hass-anycubic #28: Anycubic firmware 2.0.1.9 began sending
`external_shelves` with `id` and `loaded` set to null. `int(None)` raised,
the whole printer failed to parse, and the config entry sat in setup_retry
with every entity unavailable -- on a response the cloud had answered
successfully, carrying complete telemetry.

The trap is worth stating plainly, because the code looked defended:

    data.get('loaded', False)

only supplies the default when the key is ABSENT. A key that is present and
null returns None, and the int() after it raises anyway. That is exactly how
this shipped.
"""

import pytest

from anycubic_cloud_api.data_models.printer_properties import (
    AnycubicDryingStatus,
    AnycubicFeedStatus,
    AnycubicMachineExternalShelves,
    AnycubicMachineToolInfo,
    AnycubicMultiColorBox,
)
from anycubic_cloud_api.helpers.helpers import as_int, as_int_list, as_str

# Verbatim from the issue, nulls and all.
SHELVES_2019 = {
    "brand_name": None,
    "color": [255, 255, 255],
    "current_status": 11,
    "id": None,
    "loaded": None,
    "material_name": None,
    "status_type": 2,
    "type": "",
}


# A shelf that is actually attached: it names itself and what is in it.
# Invented, because no real payload has been seen -- so it is deliberately
# minimal and every test that uses it says what it is relying on.
SHELF_PRESENT = {
    "brand_name": "Anycubic",
    "color": [240, 243, 245],
    "current_status": 11,
    "id": 1,
    "loaded": 1,
    "material_name": "PLA",
    "status_type": 2,
    "type": "PLA",
}


class TestTheReportedPayload:
    def test_firmware_2019_reports_no_shelf_rather_than_crashing(self):
        """The payload that took people's printers away.

        It parses now -- and the right answer is that there is no shelf. The
        reporter had an ACE 2 Pro, represented fully elsewhere in the same
        response, and no external shelf at all: 2.0.1.9 sends this field
        whether or not the accessory exists.
        """
        assert AnycubicMachineExternalShelves.from_json(SHELVES_2019) is None

    def test_it_does_not_raise(self):
        """Separate from the assertion above on purpose. The bug was a crash;
        returning None is the judgement. Both must hold, and a later change to
        the judgement must not be able to quietly reintroduce the crash."""
        try:
            AnycubicMachineExternalShelves.from_json(SHELVES_2019)
        except Exception as err:  # noqa: BLE001 - the whole point is that nothing escapes
            pytest.fail(f"the reported payload raised {err!r}")

    @pytest.mark.parametrize("field", sorted(SHELF_PRESENT))
    def test_a_present_shelf_survives_any_single_null(self, field):
        """Anycubic nulls fields without warning, so each is checked on its
        own rather than trusting the next firmware to pick the same two."""
        payload = dict(SHELF_PRESENT)
        payload[field] = None

        # Nulling any single field still leaves at least one of id, type or
        # loaded, so the shelf stays identifiable in every case here.
        assert AnycubicMachineExternalShelves.from_json(payload) is not None

    def test_a_shelf_known_only_by_its_material_still_counts(self):
        """Conservative on purpose: no real shelf payload has been seen, so
        any one of an id, a material or a loaded flag is enough."""
        payload = dict(SHELVES_2019, type="PLA")

        assert AnycubicMachineExternalShelves.from_json(payload) is not None

    def test_a_shelf_known_only_by_its_id_still_counts(self):
        payload = dict(SHELVES_2019, id=1)

        shelves = AnycubicMachineExternalShelves.from_json(payload)
        assert shelves is not None
        assert shelves.id == 1

    def test_a_null_inside_the_colour_list_is_survived(self):
        payload = dict(SHELF_PRESENT, color=[255, None, 255])

        assert AnycubicMachineExternalShelves.from_json(payload).color == [255, 255]

    def test_the_mqtt_update_path_is_coerced_too(self):
        """It wrote raw values onto the slots, so a null landed intact and
        the object's own properties raised on read instead of on parse."""
        shelves = AnycubicMachineExternalShelves.from_json(SHELF_PRESENT)

        shelves.update_with_mqtt_data(dict(SHELF_PRESENT, loaded=None, color=None))

        assert shelves.loaded is False
        assert shelves.color == []


class TestTheSiblingsWithTheSameShape:
    """Every constructor fed by `.get(key, <default>)` had the same hole."""

    def test_feed_status_survives_nulls(self):
        assert AnycubicFeedStatus.from_json(
            {"code": None, "type": None, "current_status": None, "slot_index": None}
        ) is not None

    def test_drying_status_survives_nulls(self):
        drying = AnycubicDryingStatus.from_json(
            {"status": None, "target_temp": None, "duration": None, "remain_time": None}
        )

        assert drying is not None
        assert drying.is_drying is False

    def test_a_multi_colour_box_survives_null_telemetry(self):
        box = AnycubicMultiColorBox.from_json({
            "id": 0, "status": None, "model_id": None, "auto_feed": None,
            "loaded_slot": None, "temp": None, "slots": [],
        })

        assert box is not None
        assert box.loaded_slot == -1

    def test_but_a_box_with_no_id_still_raises(self):
        """`id` is the ACE's identity and the printer dict is keyed by it.
        A box that cannot be placed must not be silently invented."""
        with pytest.raises((TypeError, ValueError, KeyError)):
            AnycubicMultiColorBox.from_json({"id": None, "slots": []})

    def test_machine_tool_info_survives_nulls(self):
        assert AnycubicMachineToolInfo.from_json(
            {k: None for k in (
                "id", "typd_id", "model_id", "type_function_id", "parent_id",
                "function_name", "function_des", "control", "param",
                "icon_url", "function_type", "status", "show_place",
            )}
        ) is not None


class TestTheCoercionHelpers:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [(None, 0), ("", 0), ("nonsense", 0), ([], 0), (7, 7), ("7", 7), (7.9, 7), (True, 1)],
    )
    def test_as_int(self, value, expected):
        assert as_int(value) == expected

    def test_as_int_uses_the_stated_fallback(self):
        assert as_int(None, -1) == -1

    def test_as_str_does_not_stringify_none(self):
        """str(None) is "None", which would read as a filament called None."""
        assert as_str(None) == ""
        assert as_str("PLA") == "PLA"

    @pytest.mark.parametrize(
        ("value", "expected"),
        [(None, []), ("nope", []), ([1, None, 3], [1, 3]), ([1, 2, 3], [1, 2, 3])],
    )
    def test_as_int_list(self, value, expected):
        assert as_int_list(value) == expected
