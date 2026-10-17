"""A print on a resin printer over the local connection, start to stop.

Captured from an Anycubic Photon P1 Max (model id 132) in LAN Mode: a file on
its USB stick was started locally, the printer copied it, ran its pre-print
checks, stalled on them with code 1301 because the vat was empty, refused a
pause and a resume, and was stopped. One report of each kind it sent is kept
below, keyed "type/action/state". The slicer's source_info block is shortened
to three keys and the message and task ids are replaced by placeholders;
everything else is as it arrived. The payload contract fails
loudly on any key left unread, so these double as a check that a real report
is handled completely.
"""

import json
from copy import deepcopy
from unittest.mock import MagicMock

import pytest

from anycubic_cloud_api.const.enums import AnycubicOrderID
from anycubic_cloud_api.data_models.consumable import AnycubicConsumableData
from anycubic_cloud_api.data_models.printer import AnycubicPrinter
from anycubic_cloud_api.exceptions.exceptions import AnycubicMQTTUnknownUpdate
from anycubic_cloud_api.lan.commands import lan_command_for_order

TOPIC = "anycubic/anycubicCloud/v1/printer/public/132/DEVICE/print/report"

REPORTS = json.loads('''
{
 "autoOperation/reportStatus/done": {
  "type": "autoOperation",
  "action": "reportStatus",
  "msgid": "",
  "state": "done",
  "timestamp": 1791801759096,
  "code": 200,
  "msg": "",
  "data": {
   "currentStatus": [
    {
     "name": "FileVerification",
     "support": 1,
     "editable": 0,
     "status": 1
    },
    {
     "name": "autoTop",
     "support": 1,
     "editable": 1,
     "status": 0
    },
    {
     "name": "camera_timelapse",
     "support": 1,
     "editable": 1,
     "status": 0
    },
    {
     "name": "dynamicRelease",
     "support": 1,
     "editable": 1,
     "status": 0
    },
    {
     "name": "failDetection",
     "support": 1,
     "editable": 1,
     "status": 0
    },
    {
     "name": "levelling",
     "support": 1,
     "editable": 0,
     "status": 1
    },
    {
     "name": "model",
     "support": 1,
     "editable": 0,
     "status": 1
    },
    {
     "name": "offLightCompensation",
     "support": 1,
     "editable": 1,
     "status": 0
    },
    {
     "name": "platform",
     "support": 1,
     "editable": 0,
     "status": 0
    },
    {
     "name": "platformOffsetComp",
     "support": 1,
     "editable": 1,
     "status": 0
    },
    {
     "name": "residual",
     "support": 1,
     "editable": 0,
     "status": 1
    },
    {
     "name": "resin",
     "support": 1,
     "editable": 0,
     "status": 1
    },
    {
     "name": "resinAutoLoad",
     "support": 0,
     "editable": 0,
     "status": 1
    },
    {
     "name": "resinAutoUnload",
     "support": 0,
     "editable": 0,
     "status": 0
    },
    {
     "name": "resinCycle",
     "support": 0,
     "editable": 0,
     "status": 0
    },
    {
     "name": "resinCyclePrinting",
     "support": 0,
     "editable": 1,
     "status": 0
    },
    {
     "name": "resinHeat",
     "support": 1,
     "editable": 1,
     "status": 0
    },
    {
     "name": "smartSpeed",
     "support": 0,
     "editable": 0,
     "status": 0
    },
    {
     "name": "stirBeforePrint",
     "support": 1,
     "editable": 1,
     "status": 0
    }
   ]
  }
 },
 "print/monitor/monitoring": {
  "type": "print",
  "action": "monitor",
  "msgid": "00000000-0000-4000-8000-000000000001",
  "state": "monitoring",
  "timestamp": 1791801760079,
  "code": 0,
  "msg": "",
  "data": {
   "checkStatus": [
    {
     "name": "airCleanerDev",
     "status": -2
    },
    {
     "name": "camera",
     "status": 0
    },
    {
     "name": "four_leveling",
     "status": 0
    },
    {
     "name": "fpgaDev",
     "status": 0
    },
    {
     "name": "motor",
     "status": -2
    },
    {
     "name": "platformDev",
     "status": -2
    },
    {
     "name": "pullForce",
     "status": 0
    },
    {
     "name": "resiBoxDev",
     "status": -2
    },
    {
     "name": "resinInOutDev",
     "status": -2
    },
    {
     "name": "screen0",
     "status": -2
    },
    {
     "name": "screen1",
     "status": -2
    },
    {
     "name": "spiFlashDev",
     "status": -2
    },
    {
     "name": "usbDev",
     "status": -2
    },
    {
     "name": "uvBoard",
     "status": -2
    },
    {
     "name": "wifiDev",
     "status": 0
    }
   ],
   "taskid": "-1"
  }
 },
 "print/start/copying": {
  "type": "print",
  "action": "start",
  "msgid": "00000000-0000-4000-8000-000000000001",
  "timestamp": 1791801762202,
  "state": "copying",
  "data": {
   "taskid": "-1",
   "progress": 50
  }
 },
 "print/start/printing": {
  "type": "print",
  "action": "start",
  "msgid": "00000000-0000-4000-8000-000000000001",
  "state": "printing",
  "timestamp": 1791801765818,
  "code": 200,
  "msg": "",
  "data": {
   "taskid": "-1",
   "task_mode": 1,
   "dual_platform_mode_enable": 0,
   "localtask": "00000000-0000-4000-8000-000000000002",
   "filename": "TEST.pp1m",
   "remain_time": 115,
   "model_hight": 34.850002,
   "curr_layer": 0,
   "compensation_layers": "0",
   "total_layers": 697,
   "supplies_usage": 25.17914,
   "tensile_value": -860,
   "progress": 0,
   "z_thick": 0.05,
   "anti_count": 16,
   "print_time": 0,
   "slicer": "ANYCUBIC-PC",
   "source_info": {
    "file_id": -1,
    "plant_index": 0,
    "source_type": 1
   },
   "settings": {
    "on_time": 2.8,
    "off_time": 0,
    "bottom_time": 25,
    "bottom_layers": 1,
    "z_up_height": 9,
    "z_up_speed": 6,
    "z_down_speed": 6,
    "bottom_up_before_wait": 0,
    "normal_up_before_wait": 0,
    "bottom_up_after_wait": 0,
    "normal_up_after_wait": 0,
    "bottom_down_after_wait": 0
   },
   "settings_adv": {
    "z_up_height_b0": 4,
    "z_up_height_b1": 8,
    "z_up_speed_b0": 0.1,
    "z_up_speed_b1": 3,
    "z_down_speed_b0": 0.1,
    "z_down_speed_b1": 3,
    "z_up_height_n0": 4,
    "z_up_height_n1": 8,
    "z_up_speed_n0": 3,
    "z_up_speed_n1": 8,
    "z_down_speed_n0": 3,
    "z_down_speed_n1": 8,
    "trans_layers": 15
   },
   "stir_settings": {
    "status": 0,
    "stirTime": 10
   },
   "task_settings": {
    "dynamicRelease": 0,
    "offLightCompensation": 0,
    "autoTop": 0,
    "failDetection": 0,
    "resinHeat": 0,
    "camera_timelapse": 0,
    "ai_detect": 0,
    "platformOffsetComp": 0
   }
  }
 },
 "print/autoOperation/monitoring": {
  "type": "print",
  "action": "autoOperation",
  "msgid": "00000000-0000-4000-8000-000000000001",
  "state": "monitoring",
  "timestamp": 1791801766344,
  "code": 0,
  "msg": "",
  "data": {
   "checkStatus": [
    {
     "name": "FileVerification",
     "status": 0
    },
    {
     "name": "ai_detect",
     "status": -1
    },
    {
     "name": "autoTop",
     "status": -2
    },
    {
     "name": "camera_timelapse",
     "status": -1
    },
    {
     "name": "dynamicRelease",
     "status": -2
    },
    {
     "name": "failDetection",
     "status": -2
    },
    {
     "name": "levelling",
     "status": -1
    },
    {
     "name": "model",
     "status": -2
    },
    {
     "name": "offLightCompensation",
     "status": -2
    },
    {
     "name": "platform",
     "status": -1
    },
    {
     "name": "platformOffsetComp",
     "status": -1
    },
    {
     "name": "residual",
     "status": -1
    },
    {
     "name": "resin",
     "status": -1
    },
    {
     "name": "resinAutoLoad",
     "status": -2
    },
    {
     "name": "resinAutoUnload",
     "status": -2
    },
    {
     "name": "resinCycle",
     "status": -2
    },
    {
     "name": "resinCyclePrinting",
     "status": -2
    },
    {
     "name": "resinHeat",
     "status": -2
    },
    {
     "name": "smartSpeed",
     "status": -1
    },
    {
     "name": "stirBeforePrint",
     "status": 0
    }
   ],
   "taskid": "0"
  }
 },
 "print/pause/unablePause": {
  "type": "print",
  "action": "pause",
  "msgid": "00000000-0000-4000-8000-000000000001",
  "state": "unablePause",
  "timestamp": 1791801834691,
  "code": 9000,
  "msg": "",
  "data": {
   "taskid": "0",
   "task_mode": 1,
   "dual_platform_mode_enable": 0
  }
 },
 "print/resume/unable-resume": {
  "type": "print",
  "action": "resume",
  "msgid": "00000000-0000-4000-8000-000000000001",
  "state": "unable-resume",
  "timestamp": 1791801875296,
  "code": 102,
  "msg": "",
  "data": {
   "taskid": "",
   "task_mode": 1,
   "dual_platform_mode_enable": 0
  }
 },
 "print/start/waiting": {
  "type": "print",
  "action": "start",
  "msgid": "00000000-0000-4000-8000-000000000001",
  "state": "waiting",
  "timestamp": 1791801895202,
  "code": 1301,
  "msg": "",
  "data": {
   "taskid": "0",
   "task_mode": 1,
   "localtask": "00000000-0000-4000-8000-000000000002",
   "filename": "TEST.pp1m",
   "remain_time": 115,
   "model_hight": 34.850002,
   "curr_layer": 0,
   "compensation_layers": "0",
   "dual_platform_mode_enable": 0,
   "total_layers": 697,
   "supplies_usage": 25.17914,
   "progress": 0,
   "z_thick": 0.05,
   "anti_count": 16,
   "print_time": 2,
   "slicer": "ANYCUBIC-PC",
   "tensile_value": -873,
   "source_info": {
    "file_id": -1,
    "plant_index": 0,
    "source_type": 1
   },
   "settings": {
    "on_time": 2.8,
    "off_time": 2,
    "bottom_time": 25,
    "bottom_layers": 1,
    "z_up_height": 9,
    "z_up_speed": 6,
    "z_down_speed": 6,
    "bottom_up_before_wait": 0,
    "normal_up_before_wait": 0,
    "bottom_up_after_wait": 0,
    "normal_up_after_wait": 0,
    "bottom_down_after_wait": 150
   },
   "settings_adv": {
    "z_up_height_b0": 4,
    "z_up_height_b1": 8,
    "z_up_speed_b0": 0.1,
    "z_up_speed_b1": 3,
    "z_down_speed_b0": 0.1,
    "z_down_speed_b1": 3,
    "z_up_height_n0": 4,
    "z_up_height_n1": 8,
    "z_up_speed_n0": 3,
    "z_up_speed_n1": 8,
    "z_down_speed_n0": 3,
    "z_down_speed_n1": 8,
    "trans_layers": 15
   }
  }
 },
 "buried/PrintError/None": {
  "type": "buried",
  "action": "PrintError",
  "msgid": "00000000-0000-4000-8000-000000000001",
  "timestamp": 1791801895347,
  "data": {
   "task_id": "0",
   "error_code": 1301,
   "error_content": "",
   "layers": 0,
   "process": 0,
   "stage": "pre_print"
  }
 },
 "buried/PrintFinish/None": {
  "type": "buried",
  "action": "PrintFinish",
  "msgid": "00000000-0000-4000-8000-000000000001",
  "timestamp": 1791801917431,
  "data": {
   "task_id": "0",
   "Actual_duration": 2,
   "Actual_volume": null,
   "Actual_weight": null,
   "error_code": 601,
   "finish_type": "stop",
   "layers": 0,
   "process": 0,
   "stage": "print"
  }
 },
 "print/stop/stoped": {
  "type": "print",
  "action": "stop",
  "msgid": "00000000-0000-4000-8000-000000000001",
  "state": "stoped",
  "timestamp": 1791801917431,
  "code": 601,
  "msg": "",
  "data": {
   "taskid": "0",
   "task_mode": 1,
   "localtask": "00000000-0000-4000-8000-000000000002",
   "filename": "TEST.pp1m",
   "remain_time": 115,
   "model_hight": 34.850002,
   "curr_layer": 0,
   "compensation_layers": "0",
   "dual_platform_mode_enable": 0,
   "total_layers": 697,
   "supplies_usage": 25.17914,
   "progress": 0,
   "z_thick": 0.05,
   "anti_count": 16,
   "print_time": 2,
   "slicer": "ANYCUBIC-PC",
   "tensile_value": -886,
   "source_info": {
    "file_id": -1,
    "plant_index": 0,
    "source_type": 1
   },
   "settings": {
    "on_time": 2.8,
    "off_time": 2,
    "bottom_time": 25,
    "bottom_layers": 1,
    "z_up_height": 9,
    "z_up_speed": 6,
    "z_down_speed": 6,
    "bottom_up_before_wait": 0,
    "normal_up_before_wait": 0,
    "bottom_up_after_wait": 0,
    "normal_up_after_wait": 0,
    "bottom_down_after_wait": 150
   },
   "settings_adv": {
    "z_up_height_b0": 4,
    "z_up_height_b1": 8,
    "z_up_speed_b0": 0.1,
    "z_up_speed_b1": 3,
    "z_down_speed_b0": 0.1,
    "z_down_speed_b1": 3,
    "z_up_height_n0": 4,
    "z_up_height_n1": 8,
    "z_up_speed_n0": 3,
    "z_up_speed_n1": 8,
    "z_down_speed_n0": 3,
    "z_down_speed_n1": 8,
    "trans_layers": 15
   }
  }
 }
}
''')


def make_printer():
    return AnycubicPrinter(
        api_parent=MagicMock(),
        machine_type=132,
        machine_name="Anycubic Photon P1 Max",
        id=1,
        ignore_init_errors=True,
    )


def apply(printer, key, **changes):
    report = deepcopy(REPORTS[key])
    report.update(changes)
    printer.process_mqtt_update(TOPIC, AnycubicConsumableData(report))


class TestEveryReportOfThePrint:
    @pytest.mark.parametrize("key", sorted(REPORTS))
    def test_it_is_fully_consumed(self, key):
        """Anything unread raises -- so this passing means nothing was missed."""
        apply(make_printer(), key)

    def test_the_capture_covers_the_whole_run(self):
        assert {
            "print/start/copying",
            "print/start/printing",
            "print/start/waiting",
            "print/monitor/monitoring",
            "print/autoOperation/monitoring",
            "print/pause/unablePause",
            "print/resume/unable-resume",
            "print/stop/stoped",
            "autoOperation/reportStatus/done",
            "buried/PrintError/None",
            "buried/PrintFinish/None",
        } <= set(REPORTS)


class TestWhatThePrintLooksLike:
    def test_copying_from_the_stick_reads_as_busy_with_progress(self):
        printer = make_printer()

        apply(printer, "print/start/copying")

        assert printer._is_printing == 2
        assert printer._job_download_progress == 50

    def test_a_job_stalled_on_its_checks_is_still_a_job(self):
        printer = make_printer()

        apply(printer, "print/start/waiting")

        assert printer._is_printing == 2

    def test_the_stall_leaves_its_code_behind(self):
        printer = make_printer()

        apply(printer, "print/start/waiting")

        assert REPORTS["print/start/waiting"]["code"] == 1301
        assert printer.latest_error_code == 1301

    @pytest.mark.parametrize("key", ["print/pause/unablePause", "print/resume/unable-resume"])
    def test_a_refused_pause_or_resume_changes_nothing(self, key):
        printer = make_printer()
        apply(printer, "print/start/printing")

        apply(printer, key)

        assert printer._is_printing == 2

    def test_a_stop_reads_as_free_again(self):
        printer = make_printer()
        apply(printer, "print/start/printing")

        apply(printer, "print/stop/stoped")

        assert printer._is_printing == 1

    def test_the_pre_print_steps_are_kept_by_name(self):
        printer = make_printer()

        apply(printer, "print/autoOperation/monitoring")

        assert printer.print_self_check["FileVerification"] == 0
        assert printer.print_self_check["resin"] == -1

    def test_hardware_checks_and_pre_print_steps_are_kept_together(self):
        printer = make_printer()

        apply(printer, "print/monitor/monitoring")
        apply(printer, "print/autoOperation/monitoring")

        assert {"camera", "wifiDev", "levelling", "resin"} <= set(printer.print_self_check)

    def test_the_automatic_steps_are_kept_by_name(self):
        printer = make_printer()

        apply(printer, "autoOperation/reportStatus/done")

        assert printer.auto_operations["levelling"] == {"support": 1, "editable": 0, "status": 1}
        assert printer.auto_operations["resinAutoLoad"]["support"] == 0

    def test_an_unfamiliar_auto_operation_message_is_not_swallowed(self):
        with pytest.raises(AnycubicMQTTUnknownUpdate):
            apply(make_printer(), "autoOperation/reportStatus/done", action="somethingElse")

    def test_the_printers_own_account_of_the_stall_is_kept(self):
        printer = make_printer()

        apply(printer, "buried/PrintError/None")

        assert printer.last_print_error["error_code"] == 1301
        assert printer.last_print_error["stage"] == "pre_print"

    def test_the_printers_own_account_of_the_end_is_kept(self):
        printer = make_printer()

        apply(printer, "buried/PrintFinish/None")

        assert printer.last_print_finish["finish_type"] == "stop"
        assert printer.last_print_finish["error_code"] == 601

    def test_an_unfamiliar_log_entry_is_not_swallowed(self):
        with pytest.raises(AnycubicMQTTUnknownUpdate):
            apply(make_printer(), "buried/PrintFinish/None", action="SomethingElse")

    def test_before_any_print_there_is_nothing_to_report(self):
        printer = make_printer()

        assert printer.print_self_check is None
        assert printer.auto_operations is None
        assert printer.last_print_error is None
        assert printer.last_print_finish is None


class TestHowItIsStarted:
    def test_a_local_start_carries_the_no_task_yet_id(self):
        command = lan_command_for_order(AnycubicOrderID.START_PRINT)

        assert (command.message_type, command.action) == ("print", "start")
        assert command.default_data == {"taskid": "-1"}

    def test_the_usb_stick_is_listed_from_its_root(self):
        command = lan_command_for_order(AnycubicOrderID.LIST_UDISK_FILES)

        assert (command.message_type, command.action) == ("file", "listUdisk")
        assert command.default_data == {"path": "/"}
