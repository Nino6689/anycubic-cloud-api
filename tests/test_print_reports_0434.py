"""Print and ACE reports that were being dropped or misread (0.4.34).

From a Kobra X (#34) and a Kobra S1 with two ACE Pro units (#42): the active
filament channel arrived in print updates nobody read, progress-only updates
were logged as unhandled, a refused dry cycle passed silently, and a LAN job
had no speed presets for the speed select to offer (discussion #37).
"""

from unittest.mock import MagicMock

import pytest

from anycubic_cloud_api.data_models.consumable import AnycubicConsumableData
from anycubic_cloud_api.data_models.printer import AnycubicPrinter
from anycubic_cloud_api.data_models.project import AnycubicProject
from anycubic_cloud_api.exceptions.exceptions import AnycubicMQTTUnknownUpdate


def slot(index):
    return {
        "index": index,
        "sku": "",
        "type": "PLA",
        "color": [1, 2, 3],
        "status": 5,
        "edit_status": 1,
    }


def box(box_id, slots=4):
    return {
        "id": box_id,
        "loaded_slot": -1,
        "slots": [slot(i) for i in range(slots)],
    }


def make_printer(boxes, parent=None):
    return AnycubicPrinter(
        api_parent=parent or MagicMock(),
        machine_type=20030,
        machine_name="Kobra X",
        id=1,
        multi_color_box=boxes,
        ignore_init_errors=True,
    )


def message(msg_type, action, state, data, **envelope):
    return AnycubicConsumableData({
        "type": msg_type,
        "action": action,
        "state": state,
        "msgid": "m",
        "timestamp": 1,
        "data": data,
        **envelope,
    })


def lan_job(task_id=42, **fields):
    return {
        "task_id": task_id,
        "filename": "cube.gcode.3mf",
        "progress": 0,
        "print_status": 1,
        **fields,
    }


TOPIC = "anycubic/anycubicCloud/v1/printer/public/20030/key/print/report"
ACE_TOPIC = "anycubic/anycubicCloud/v1/printer/public/20030/key/multiColorBox/report"


class TestActiveChannel:
    def _channel(self, printer, channel_no):
        printer.process_mqtt_update(
            TOPIC,
            message(
                "print", "update", "updated",
                {"channel_no": channel_no, "settings": {"light": 0}},
            ),
        )

    @pytest.mark.parametrize(("channel_no", "slot_index"), [(1, 0), (3, 2), (4, 3)])
    def test_a_channel_change_moves_the_loaded_slot(self, channel_no, slot_index):
        printer = make_printer([box(0)])

        self._channel(printer, channel_no)

        assert printer.primary_multi_color_box_loaded_slot == slot_index

    def test_channels_beyond_the_first_box_land_in_the_next(self):
        """Channel 5 with four slots in the first box is the second box's first."""
        printer = make_printer([box(0), box(1)])

        self._channel(printer, 5)

        assert printer.secondary_multi_color_box_loaded_slot == 0

    @pytest.mark.parametrize("channel_no", [0, -1, 9, None, "x"])
    def test_a_channel_with_no_slot_changes_nothing(self, channel_no):
        printer = make_printer([box(0)])
        printer._multi_color_box[0].set_slot_loaded(1)

        self._channel(printer, channel_no)

        assert printer.primary_multi_color_box_loaded_slot == 1

    def test_a_printer_with_no_ace_ignores_it(self):
        printer = make_printer(None)

        self._channel(printer, 2)

        assert printer.connected_ace_units == 0


class TestProgressUpdates:
    PROGRESS = {
        "curr_layer": 23,
        "file_root_path": "cube.gcode.3mf",
        "filename": "cube.gcode.3mf",
        "filetype": 0,
        "print_time": 7,
        "progress": 10,
        "remain_time": 66,
        "settings": {"light": 0},
        "supplies_usage": 1074,
        "total_layers": 263,
    }

    def test_progress_without_a_task_id_reaches_the_job(self):
        printer = make_printer([box(0)])
        printer._apply_lan_project(AnycubicConsumableData(lan_job()))

        printer.process_mqtt_update(
            TOPIC, message("print", "update", "updated", dict(self.PROGRESS))
        )

        project = printer.latest_project
        assert project is not None
        assert project.progress_percentage == 10
        assert project.print_time_remaining_minutes == 66

    def test_progress_with_no_job_is_dropped_quietly(self):
        printer = make_printer([box(0)])

        printer.process_mqtt_update(
            TOPIC, message("print", "update", "updated", dict(self.PROGRESS))
        )

        assert printer.latest_project is None

    def test_progress_for_another_job_is_not_applied(self):
        printer = make_printer([box(0)])
        printer._apply_lan_project(AnycubicConsumableData(lan_job(task_id=42)))

        printer.process_mqtt_update(
            TOPIC,
            message("print", "update", "updated", {"taskid": 7, **self.PROGRESS}),
        )

        assert printer.latest_project.progress_percentage == 0

    def test_the_s1_file_fields_are_not_left_over(self):
        """These four were reported as unhandled every 30-60 s (#42)."""
        printer = make_printer([box(0)])
        printer._apply_lan_project(AnycubicConsumableData(lan_job()))

        printer.process_mqtt_update(
            TOPIC,
            message(
                "print", "update", "updated",
                {
                    "display_filename": "cube",
                    "origin3mf": "cube.3mf",
                    "source_info": "slicer",
                    "temp_gcode": "/tmp/x",
                    "progress": 50,
                },
            ),
        )

        assert printer.latest_project.progress_percentage == 50

    def test_a_print_start_with_file_fields_is_handled(self):
        printer = make_printer([box(0)])
        printer._apply_lan_project(AnycubicConsumableData(lan_job()))

        printer.process_mqtt_update(
            TOPIC,
            message(
                "print", "start", "printing",
                {"file_root_path": "cube.gcode.3mf", "filetype": 0},
            ),
        )


class TestRefusedDrying:
    def _printer(self):
        parent = MagicMock()
        logs: list[str] = []
        parent._log_to_warn = logs.append
        return make_printer([box(0), box(1)], parent), logs

    def test_a_refusal_code_is_reported_and_kept(self):
        printer, logs = self._printer()

        printer.process_mqtt_update(
            ACE_TOPIC,
            message("multiColorBox", "setDry", "failed", {}, code=11505, msg="fail"),
        )

        assert len(logs) == 1
        assert "11505" in logs[0]
        assert "target temperature" in logs[0]
        assert printer.latest_error_code == 11505

    def test_a_code_inside_the_data_counts_too(self):
        printer, logs = self._printer()

        printer.process_mqtt_update(
            ACE_TOPIC,
            message("multiColorBox", "setDry", "done", {"code": 11505}, code=200),
        )

        assert "11505" in logs[0]
        assert printer.latest_error_code == 11505

    def test_a_failed_state_without_a_code_is_still_reported(self):
        printer, logs = self._printer()

        printer.process_mqtt_update(
            ACE_TOPIC,
            message("multiColorBox", "setDry", "failed", None, code=200, msg="busy"),
        )

        assert logs == ["The printer refused to start drying on the ACE (busy)."]

    def test_an_unfamiliar_reply_is_not_called_a_refusal(self):
        printer, logs = self._printer()

        with pytest.raises(AnycubicMQTTUnknownUpdate):
            printer.process_mqtt_update(
                ACE_TOPIC,
                message("multiColorBox", "setDry", "doing", {}, code=200),
            )

        assert logs == []


class TestLanSpeedModes:
    def test_a_lan_job_offers_the_standard_presets(self):
        project = AnycubicProject.from_lan_project(MagicMock(), 1, lan_job())

        assert project is not None
        assert [m.mode for m in project.available_print_speed_modes] == [1, 2, 3]
        project.validate_print_speed_mode(3)

    def test_a_list_the_printer_sends_is_used_instead(self):
        project = AnycubicProject.from_lan_project(
            MagicMock(),
            1,
            lan_job(print_speed_model_des=[{"title": "Ludicrous", "print_speed_mode": 4}]),
        )

        assert project is not None
        assert [m.title for m in project.available_print_speed_modes] == ["Ludicrous"]
