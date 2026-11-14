"""getSliceParam replies were rejected on every printer (#48).

MQTT payloads are wrapped in AnycubicConsumableData, which turns every nested
dict into another AnycubicConsumableData -- a UserDict, not a dict. The
project setters only accepted ``dict``, so a perfectly normal slice_param
raised "Unexpected data for project slice_param" with the dict in the message.
"""

from unittest.mock import MagicMock

import pytest

from anycubic_cloud_api.data_models.consumable import (
    AnycubicConsumableData,
    plain_data,
)
from anycubic_cloud_api.data_models.printer import AnycubicPrinter
from anycubic_cloud_api.data_models.project import AnycubicProject

TOPIC = "anycubic/anycubicCloud/v1/printer/public/20030/key/print/report"

SLICE_PARAM = {
    "bed_temperature": 60,
    "brim_type": "outer_only",
    "filament_retract_length": 0.8,
    "filament_type": ";PLA",
    "fill_density": 15.0,
    "layer_height": 0.2,
    "paint_infos": [
        {
            "filament_used": 7.5,
            "material_type": "PLA",
            "paint_color": [0, 53, 148],
            "paint_index": 1,
        }
    ],
    "printer_settings_id": "Anycubic Kobra 3",
    "remain_time": 23,
    "size_x": 41.14,
}


def make_printer():
    printer = AnycubicPrinter(
        api_parent=MagicMock(),
        machine_type=20030,
        machine_name="Kobra 3",
        id=1,
        ignore_init_errors=True,
    )
    project = AnycubicProject.from_lan_project(
        MagicMock(), 1, {"task_id": 135980792, "filename": "cube.gcode.3mf", "print_status": 1}
    )
    assert project is not None
    printer._latest_project = project
    return printer, project


def test_slice_param_from_mqtt_is_accepted():
    printer, project = make_printer()
    printer.process_mqtt_update(
        TOPIC,
        AnycubicConsumableData({
            "type": "print",
            "action": "getSliceParam",
            "state": "done",
            "code": 200,
            "msgid": "m",
            "timestamp": 1,
            "data": {
                "ams_settings": {"use_ams": True},
                "file_key": "25b94c6277dd27eebdf1d48631212ab5",
                "slice_param": SLICE_PARAM,
                "taskid": "135980792",
            },
        }),
    )

    assert project._slice_param["layer_height"] == 0.2
    # Unwrapped all the way down, so later code can rely on plain types.
    assert type(project._slice_param) is dict
    assert type(project._slice_param["paint_infos"][0]) is dict


@pytest.mark.parametrize("setter", ["set_slice_param", "set_slice_result"])
def test_setters_accept_any_mapping(setter):
    _, project = make_printer()
    getattr(project, setter)(AnycubicConsumableData({"a": {"b": 1}}))
    stored = project._slice_param if setter == "set_slice_param" else project._slice_result
    assert stored == {"a": {"b": 1}}
    assert type(stored["a"]) is dict


def test_plain_data_unwraps_and_consumes():
    wrapped = AnycubicConsumableData({"x": {"y": [{"z": 1}]}, "n": 2})
    assert plain_data(wrapped) == {"x": {"y": [{"z": 1}]}, "n": 2}
    # Everything was read, so nothing is left to be reported as unhandled.
    assert wrapped.is_empty
