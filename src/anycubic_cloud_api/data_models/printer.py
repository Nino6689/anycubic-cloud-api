from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from ..const.enums import (
    AnycubicFunctionID,
    AnycubicPrinterMaterialType,
    AnycubicPrintStatus,
)
from ..const.error_codes import (
    PRINTER_OK_CODES,
    describe_printer_code,
)
from ..exceptions.error_strings import (
    ErrorsDataParsing,
    ErrorsGeneral,
    ErrorsMQTTUpdate,
)
from ..exceptions.exceptions import (
    AnycubicAPIError,
    AnycubicDataParsingError,
    AnycubicMQTTUnhandledData,
    AnycubicMQTTUnknownUpdate,
)
from ..helpers.helpers import (
    get_part_from_mqtt_topic,
    time_duration_string_to_delta,
    timedelta_to_dhm_string,
    timedelta_to_total_hours,
)
from .consumable import AnycubicConsumableData
from .files import AnycubicFile
from .printer_properties import (
    AnycubicAxisPosition,
    AnycubicMachineColorInfo,
    AnycubicMachineData,
    AnycubicMachineExternalShelves,
    AnycubicMachineFirmwareInfo,
    AnycubicMachineParameter,
    AnycubicMachineToolInfo,
    AnycubicMaterialColor,
    AnycubicMultiColorBox,
)
from .printing_settings import AnycubicPrintingSettings
from .project import AnycubicProject

if TYPE_CHECKING:
    from datetime import timedelta

    from ..anycubic_api import AnycubicAPI
    from .print_response import AnycubicPrintResponse
    from .printer_properties import AnycubicDryingStatus, AnycubicMaterialMapping


def _drain(consumable: Any) -> dict[str, Any]:
    """Read every remaining key, returning them as a plain dict.

    Reading is what marks a key consumed, and the payload contract fails loudly
    on anything left behind -- so blocks whose keys vary by model are taken
    wholesale rather than named one by one.

    ⚠ It has to reach all the way down. A nested payload only counts as read
    once it is itself empty, so reading the key holding one leaves both behind.
    That was latent for a long time: ``last_project`` is null until a print
    finishes, and the moment one did it arrived carrying a nested block, failed
    the contract, and took the whole report with it -- every local reading
    frozen from the end of the first print onwards.
    """
    if not consumable:
        return {}

    drained = dict(consumable.remaining_data)

    for key, value in list(drained.items()):
        if hasattr(value, 'remaining_data'):
            _drain(value)

        consumable.get(key)

    return drained


class AnycubicPrinter:
    __slots__ = (
        # The last code the printer reported that was not "all fine", and the
        # message that came with it. Kept rather than consumed and dropped:
        # this is the only place a fault like a filament run-out is named.
        "_latest_error_code",
        "_latest_error_message",
        "_camera_stream_url",
        "_file_upload_url",
        "_features",
        "_ai_settings",
        "_chamber_temp",
        "_target_chamber_temp",
        # What the hotend and bed are aiming for. Normally carried on the
        # print job, which only the cloud supplies -- so a printer reached
        # locally reported no setpoint at all, however hot it was getting.
        "_target_nozzle_temp",
        "_target_hotbed_temp",
        "_local_firmware_version",
        "_local_ip",
        "_ignore_init_errors",
        "_initialisation_error",
        "_api_parent",
        "_machine_type",
        "_machine_name",
        "_machine_img",
        "_net_function_ids",
        "_net_default_function",
        "_id",
        "_user_id",
        "_name",
        "_nonce",
        "_key",
        "_user_img",
        "_description",
        "_printer_type",
        "_device_status",
        "_ready_status",
        "_is_printing",
        "_reason",
        "_video_taskid",
        "_msg",
        "_material_used",
        "_total_print_time",
        "_total_print_time_delta",
        "_total_print_time_hrs",
        "_total_print_time_dhm_str",
        "_print_count",
        "_status",
        "_machine_mac",
        "_delete",
        "_create_time",
        "_delete_time",
        "_last_update_time",
        "_machine_data",
        "_type_function_ids",
        "_material_type",
        "_parameter",
        "_fw_version",
        "_available",
        "_color",
        "_advance",
        "_tools",
        "_multi_color_box_fw_version",
        "_external_shelves",
        "_axis_move_state",
        "_axis_position",
        "_multi_color_box",
        "_latest_project",
        "_lan_last_job",
        "_fan_speed",
        "_aux_fan_speed",
        "_box_fan_level",
        "_print_speed_pct",
        "_print_speed_mode",
        "_local_file_list",
        "_udisk_file_list",
        "_has_peripheral_camera",
        "_has_peripheral_multi_color_box",
        "_has_peripheral_udisk",
        "_is_bound_to_user",
        "_job_download_progress",
        "_lights",
    )

    def __init__(
        self,
        api_parent: AnycubicAPI,
        machine_type: int,
        machine_name: str,
        machine_img: str | None = None,
        net_function_ids: list[int] | None = None,
        net_default_function: int | None = None,
        id: int | None = None,
        user_id: int | None = None,
        name: str | None = None,
        nonce: str | int | None = None,
        key: str | None = None,
        user_img: str | None = None,
        description: str | None = None,
        printer_type: str | None = None,
        device_status: int | None = None,
        ready_status: int | None = None,
        is_printing: int | None = None,
        reason: str | None = None,
        video_taskid: int | None = None,
        msg: str | None = None,
        material_used: str | None = None,
        print_totaltime: str | None = None,
        print_count: int | None = None,
        status: int | None = None,
        machine_mac: str | None = None,
        delete: int | None = None,
        create_time: int | None = None,
        delete_time: int | None = None,
        last_update_time: int | None = None,
        machine_data: dict[str, Any] | None = None,
        type_function_ids: list[int] | None = None,
        material_type: str | None = None,
        parameter: dict[str, Any] | None = None,
        fw_version: dict[str, Any] | None = None,
        available: int | None = None,
        color: list[list[int]] | None = None,
        advance: list[Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        multi_color_box_fw_version: list[dict[str, Any]] | None = None,
        external_shelves: dict[str, Any] | None = None,
        multi_color_box: list[dict[str, Any]] | dict[str, Any] | None = None,
        ignore_init_errors: bool = False,
        # base_info=None,
    ) -> None:
        self._ignore_init_errors: bool = ignore_init_errors
        self._initialisation_error: bool = False

        self._api_parent: AnycubicAPI = api_parent
        self._machine_type = machine_type
        self._machine_name = machine_name
        self._machine_img = machine_img
        self._net_function_ids = net_function_ids
        self._net_default_function = net_default_function
        self._id = id
        self._user_id = user_id
        self._name = name
        self._nonce = nonce
        self._key = key
        self._user_img = user_img
        self._description = description
        self._printer_type = printer_type
        self._device_status = device_status
        self._ready_status = ready_status
        self._is_printing: int = int(is_printing) if is_printing is not None else 1
        self._reason = reason
        self._video_taskid = video_taskid
        self._msg = msg
        self._material_used = material_used
        self._set_total_print_time(print_totaltime)
        self._print_count = print_count
        self._status = status
        self._machine_mac = machine_mac
        self._delete = delete
        self._create_time = create_time
        self._delete_time = delete_time
        self._last_update_time = last_update_time
        self._set_machine_data(machine_data)
        self._set_type_function_ids(type_function_ids)
        self._set_material_type(material_type)
        self._set_parameter(parameter)
        self._set_fw_version(fw_version)
        self._available = available
        self._set_color(color)
        self._advance = advance
        self._set_tools(tools)
        self._set_multi_color_box_fw_version(multi_color_box_fw_version)
        self._set_external_shelves(external_shelves)
        self._axis_position: AnycubicAxisPosition | None = None
        self._latest_error_code: int | None = None
        self._latest_error_message: str | None = None
        self._set_multi_color_box(multi_color_box)

        self._latest_project: AnycubicProject | None = None
        # The printer's own record of the job that finished last, from the
        # local info report. Kept because the running job is cleared the moment
        # the printer goes idle, and without this a finished LAN print could
        # never be charged to its spool (hass-anycubic G1).
        self._lan_last_job: dict[str, Any] | None = None
        # None until the printer says so. It used to default to 0, which
        # is indistinguishable from a fan that is genuinely stopped.
        self._fan_speed: int | None = None
        # None, not 0, because 0 is a speed mode a printer can actually be in
        # and "never told us" is a different answer from "mode zero".
        self._print_speed_pct: int | None = None
        self._print_speed_mode: int | None = None
        self._local_file_list: list[AnycubicFile] | None = None
        self._udisk_file_list: list[AnycubicFile] | None = None
        # None until the printer has answered the peripherals poll. "No
        # camera" and "never asked" are different answers and something that
        # decides whether to offer a camera entity has to tell them apart.
        self._has_peripheral_camera: bool | None = None
        self._has_peripheral_multi_color_box: bool | None = None
        self._has_peripheral_udisk: bool | None = None
        self._is_bound_to_user: bool = True
        self._job_download_progress: int = 0
        self._aux_fan_speed: int | None = None
        self._box_fan_level: int | None = None
        # Keyed by the light `type` the printer reports (Kobra S1 uses 2).
        self._lights: dict[int, dict[str, int]] = dict()

        self._ignore_init_errors = False

    def _set_job_download_progress(self, job_download_progress: int | None) -> None:
        self._job_download_progress = int(job_download_progress) if job_download_progress is not None else 0

    def _set_total_print_time(self, print_totaltime: str | None) -> None:
        self._total_print_time: str | None = print_totaltime
        self._total_print_time_delta: timedelta = time_duration_string_to_delta(print_totaltime)
        self._total_print_time_hrs: int = int(timedelta_to_total_hours(self._total_print_time_delta))
        self._total_print_time_dhm_str: str = timedelta_to_dhm_string(self._total_print_time_delta)

    def set_has_peripheral_camera(self, has_peripheral: bool) -> None:
        self._has_peripheral_camera = bool(has_peripheral)

    def set_has_peripheral_multi_color_box(self, has_peripheral: bool) -> None:
        self._has_peripheral_multi_color_box = bool(has_peripheral)

    def set_has_peripheral_udisk(self, has_peripheral: bool) -> None:
        self._has_peripheral_udisk = bool(has_peripheral)

    def _set_type_function_ids(self, type_function_ids: list[int] | None) -> None:
        if isinstance(type_function_ids, list):
            self._type_function_ids = type_function_ids
        else:
            self._type_function_ids = list()

    def set_material_type_from_device_type(self, device_type: str | None) -> None:
        """Infer what the printer prints from what kind of machine it says it is.

        The cloud states this outright. A printer reached over its own network
        does not, but its discovery document names a device type -- and `fdm`
        means filament as surely as the cloud saying so. Without it every
        filament entity is filtered out as belonging to a different machine.
        """
        if self._material_type is not None or not device_type:
            return

        if str(device_type).lower() == "fdm":
            self._set_material_type("filament")
        elif str(device_type).lower() in ("lcd", "dlp", "resin"):
            self._set_material_type("resin")

    def _set_material_type(self, material_type: str | None) -> None:
        self._material_type: AnycubicPrinterMaterialType | str | None = None

        if material_type and isinstance(material_type, str):
            try:
                self._material_type = AnycubicPrinterMaterialType(material_type.title())

            except ValueError:
                self._material_type = material_type

    def _set_local_file_list(self, file_list: list[dict[str, Any]] | None) -> None:
        if file_list is None:
            return

        self._local_file_list = list()
        for x in file_list:
            file = AnycubicFile.from_json(x)
            if file:
                self._local_file_list.append(file)
            else:
                raise AnycubicDataParsingError(ErrorsDataParsing.local_file_list.format(file_list))

    def _set_udisk_file_list(self, file_list: list[dict[str, Any]] | None) -> None:
        if file_list is None:
            return

        self._udisk_file_list = list()
        for x in file_list:
            file = AnycubicFile.from_json(x)
            if file:
                self._udisk_file_list.append(file)
            else:
                raise AnycubicDataParsingError(ErrorsDataParsing.udisk_file_list.format(file_list))

    def _log_parse_failure(self, field: str, value: Any, error: Exception) -> None:
        """Record a payload section that could not be parsed.

        These are swallowed when ignore_init_errors is set, so without this the
        only symptom is a missing device.
        """
        logger = getattr(self._api_parent, "_log_to_warn", None)

        if logger is None:
            return

        logger(
            f"Could not parse '{field}' for printer {self._id}; "
            f"anything it provides will be missing. Error: {error}. "
            f"Payload: {value}"
        )

    def _set_multi_color_box(self, multi_color_box: list[dict[str, Any]] | dict[str, Any] | None) -> None:
        known_boxes = getattr(self, "_multi_color_box", None)
        self._multi_color_box: list[AnycubicMultiColorBox] | None = None
        try:
            if multi_color_box is None or isinstance(multi_color_box, list):
                multi_color_box_list = multi_color_box
            else:
                multi_color_box_list = list([multi_color_box])
            if multi_color_box_list is not None:
                self._multi_color_box = list()
                for x in multi_color_box_list:
                    ace = AnycubicMultiColorBox.from_json(x)
                    if ace:
                        self._multi_color_box.append(ace)
                    else:
                        raise AnycubicDataParsingError(ErrorsDataParsing.ace.format(multi_color_box))

                # A report about one box is not a statement that the others
                # have gone. With two ACE units attached, updates often carry
                # only the one that changed, and replacing the list wholesale
                # made the second unit disappear until the next full refresh.
                if (
                    known_boxes is not None
                    and len(known_boxes) > len(self._multi_color_box)
                ):
                    updated = {box.box_id: box for box in self._multi_color_box}
                    self._multi_color_box = list([
                        updated.get(box.box_id, box) for box in known_boxes
                    ])

        except Exception as e:
            self._initialisation_error = True
            # Swallowing this leaves the ACE list empty, which presents as
            # "no multi-colour box attached" with nothing in the log to explain
            # it -- indistinguishable from a printer that genuinely has none.
            self._log_parse_failure("multi_color_box", multi_color_box, e)
            if not self._ignore_init_errors:
                raise e

    def _set_machine_data(
        self,
        machine_data: dict[str, Any] | None,
    ) -> None:
        try:
            self._machine_data = AnycubicMachineData.from_json(machine_data)
        except Exception as e:
            self._initialisation_error = True
            if not self._ignore_init_errors:
                raise e

    def _apply_current_temps(self, hotbed: Any, nozzle: Any) -> None:
        """Record the live temperatures, creating the holder if need be.

        The cloud builds this object when the printer is first fetched. With
        only a local connection there is no such fetch, so it has to be made
        from the first report that carries temperatures -- otherwise every
        temperature entity reads unavailable on a working printer.
        """
        if hotbed is None or nozzle is None:
            return

        if self._parameter is None:
            self._set_parameter({
                'curr_hotbed_temp': hotbed,
                'curr_nozzle_temp': nozzle,
            })
            return

        self._parameter.update_current_temps(hotbed, nozzle)

    def _set_lan_last_job(self, data: dict[str, Any]) -> None:
        if not data:
            return

        def as_int(value: Any) -> int | None:
            try:
                return int(value)
            except (TypeError, ValueError):
                return None

        def as_float(value: Any) -> float | None:
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        self._lan_last_job = {
            'task_id': as_int(data.get('task_id')),
            # Millimetres of filament the printer says it extruded.
            'supplies_usage_mm': as_float(data.get('supplies_usage')),
            'print_status': as_int(data.get('print_status')),
            'state': data.get('state') if isinstance(data.get('state'), str) else None,
            'filename': data.get('filename') if isinstance(data.get('filename'), str) else None,
        }

    @property
    def lan_last_job(self) -> dict[str, Any] | None:
        """The last finished job as the printer reported it locally, if any."""
        return self._lan_last_job

    def _apply_lan_project(self, project: Any) -> None:
        """Track the running job from the printer's own report of it.

        Only the local connection sends this. Over the cloud the job comes
        from the account's project list, which a printer in LAN Mode is no
        longer part of -- so without this a print could be visibly running
        while every job sensor read unavailable, and pause and cancel refused
        for want of an id to name the job by.

        The block is read wholesale because its keys vary with what the
        printer is doing; the fields that are not modelled would otherwise
        fail the payload contract.
        """
        data = _drain(project)

        if not data:
            # Idle printers send null here. Holding on to the last job would
            # leave a finished print looking like a running one.
            self._latest_project = None
            return

        task_id = data.get('task_id')

        if (
            self._latest_project is None
            or task_id is None
            or int(task_id) != self._latest_project.id
        ):
            self._latest_project = AnycubicProject.from_lan_project(
                self._api_parent, self._id, data
            )

        if self._latest_project is None:
            return

        # A Kobra X sends print_status 0 mid-print, and 0 is not a status.
        # Raising on it threw away the whole info report -- temperatures,
        # progress, layers -- 20 times in two minutes (#38). An unrecognised
        # status now leaves the job's status as it was and applies the rest.
        try:
            print_status: AnycubicPrintStatus | None = AnycubicPrintStatus(
                int(data.get('print_status'))  # type: ignore[arg-type]
            )
        except (TypeError, ValueError):
            print_status = None

        self._latest_project.update_with_mqtt_print_status_data(
            print_status,
            data,
            paused=data.get('pause'),
        )
        self._latest_project.set_local_print_setting(
            'supplies_usage', data.get('supplies_usage')
        )

    def _apply_target_temps(self, hotbed: Any, nozzle: Any) -> None:
        """Remember what the printer is aiming for.

        These normally live on the print job, because over the cloud that is
        the only thing that ever sets them. Locally there is no job -- the
        cloud has dropped the printer entirely -- yet the printer still has a
        setpoint and still reports it, so it is kept here as well. Without
        this, preheating a printer over the local connection worked and looked
        like it had not: the nozzle climbed while the target read unknown.
        """
        if hotbed is not None:
            self._target_hotbed_temp = int(hotbed)

        if nozzle is not None:
            self._target_nozzle_temp = int(nozzle)

    def _set_parameter(
        self,
        parameter: dict[str, Any] | None,
    ) -> None:
        try:
            self._parameter = AnycubicMachineParameter.from_json(parameter)
        except Exception as e:
            self._initialisation_error = True
            if not self._ignore_init_errors:
                raise e

    def _set_fw_version(
        self,
        fw_version: dict[str, Any] | None,
    ) -> None:
        try:
            self._fw_version = AnycubicMachineFirmwareInfo.from_json(fw_version)
        except Exception as e:
            self._initialisation_error = True
            if not self._ignore_init_errors:
                raise e

    def _set_color(
        self,
        color: list[list[int]] | None,
    ) -> None:
        try:
            self._color = AnycubicMachineColorInfo.from_json(color)
        except Exception as e:
            self._initialisation_error = True
            if not self._ignore_init_errors:
                raise e

    def _set_tools(
        self,
        tools: list[dict[str, Any]] | None,
    ) -> None:
        self._tools: list[AnycubicMachineToolInfo] | None = None
        try:
            if tools is not None:
                self._tools = list()
                for x in tools:
                    tool = AnycubicMachineToolInfo.from_json(x)
                    if tool:
                        self._tools.append(tool)
                    else:
                        raise AnycubicDataParsingError(ErrorsDataParsing.tools.format(tools))
        except Exception as e:
            self._initialisation_error = True
            if not self._ignore_init_errors:
                raise e

    def _set_multi_color_box_fw_version(
        self,
        multi_color_box_fw_version: list[dict[str, Any]] | None,
    ) -> None:
        self._multi_color_box_fw_version: list[AnycubicMachineFirmwareInfo] | None = None
        try:
            if multi_color_box_fw_version is not None:
                self._multi_color_box_fw_version = list()
                for x in multi_color_box_fw_version:
                    ace = AnycubicMachineFirmwareInfo.from_json(x)
                    if ace:
                        self._multi_color_box_fw_version.append(ace)
                    else:
                        raise AnycubicDataParsingError(
                            ErrorsDataParsing.ace_fw_version.format(multi_color_box_fw_version)
                        )
        except Exception as e:
            self._initialisation_error = True
            if not self._ignore_init_errors:
                raise e

    def _set_external_shelves(
        self,
        external_shelves: dict[str, Any] | None,
    ) -> None:
        try:
            self._external_shelves = AnycubicMachineExternalShelves.from_json(external_shelves)
        except Exception as e:
            self._initialisation_error = True
            if not self._ignore_init_errors:
                raise e

    def _update_fw_version_from_json(
        self,
        fw_version: dict[str, Any] | None,
    ) -> None:
        if fw_version is None:
            return

        if self._fw_version:
            self._fw_version.update_from_json(fw_version)
        else:
            self._set_fw_version(fw_version)

    def _update_multi_color_box_fw_version_from_json(
        self,
        multi_color_box_fw_version: list[dict[str, Any]] | None,
    ) -> None:
        if (
            multi_color_box_fw_version is None or
            not isinstance(multi_color_box_fw_version, list) or
            len(multi_color_box_fw_version) < 1
        ):
            return

        if self._multi_color_box_fw_version and len(self._multi_color_box_fw_version) > 0:
            for x, fwver in enumerate(self._multi_color_box_fw_version):
                if fwver and len(multi_color_box_fw_version) >= x + 1:
                    fwver.update_from_json(multi_color_box_fw_version[x])
        else:
            self._set_multi_color_box_fw_version(multi_color_box_fw_version)

    @classmethod
    def from_basic_json(
        cls,
        api_parent: AnycubicAPI,
        data: dict[str, Any],
    ) -> AnycubicPrinter:
        return cls(
            api_parent=api_parent,
            machine_type=data['machine_type'],
            machine_name=data['name'],
            machine_img=data['img'],
            net_function_ids=data['net_function_ids'],
            net_default_function=data['net_default_function'],
        )

    @classmethod
    def from_status_json(
        cls,
        api_parent: AnycubicAPI,
        data: dict[str, Any],
        ignore_init_errors: bool = False,
    ) -> AnycubicPrinter:
        return cls(
            api_parent=api_parent,
            id=data['id'],
            user_id=data['user_id'],
            name=data['name'],
            nonce=data['nonce'],
            key=data['key'],
            machine_type=data['machine_type'],
            machine_name=data['model'],
            user_img=data.get('img'),
            description=data.get('description'),
            printer_type=data['type'],
            device_status=data['device_status'],
            ready_status=data['ready_status'],
            is_printing=data['is_printing'],
            reason=data.get('reason'),
            video_taskid=data.get('video_taskid'),
            msg=data.get('msg'),
            material_used=data.get('material_used'),
            print_totaltime=data.get('print_totaltime'),
            status=data['status'],
            machine_mac=data.get('machine_mac'),
            delete=data['delete'],
            create_time=data.get('create_time'),
            delete_time=data['delete_time'],
            last_update_time=data['last_update_time'],
            machine_data=data['machine_data'],
            type_function_ids=data['type_function_ids'],
            material_type=data.get('material_type'),
            parameter=data.get('parameter'),
            fw_version=data['version'],
            available=data.get('available'),
            color=data.get('color'),
            ignore_init_errors=ignore_init_errors,
        )

    @classmethod
    def from_info_json(
        cls,
        api_parent: AnycubicAPI,
        data: dict[str, Any],
        ignore_init_errors: bool = False,
    ) -> AnycubicPrinter:
        try:
            extra_data = data.get('base', {})
            return cls(
                api_parent=api_parent,
                id=data['id'],
                name=data['name'],
                key=data['key'],
                machine_type=data['machine_type'],
                machine_name=data['model'],
                user_img=data.get('img'),
                description=extra_data.get('description'),
                device_status=data['device_status'],
                is_printing=data['is_printing'],
                material_used=extra_data.get('material_used'),
                print_totaltime=extra_data.get('print_totaltime'),
                print_count=extra_data.get('print_count'),
                machine_mac=extra_data.get('machine_mac'),
                create_time=extra_data.get('create_time'),
                machine_data=data.get('machine_data'),
                type_function_ids=data['type_function_ids'],
                material_type=extra_data.get('material_type'),
                parameter=data.get('parameter'),
                fw_version=data['version'],
                tools=data.get('tools'),
                multi_color_box_fw_version=data.get('multi_color_box_version'),
                external_shelves=data.get('external_shelves'),
                multi_color_box=data.get('multi_color_box'),
                ignore_init_errors=ignore_init_errors,
            )
        except Exception as e:
            print(data)
            raise e

    def update_from_info_json(self, data: dict[str, Any] | None) -> None:
        if data is None:
            return

        if str(self._id) != str(data['id']):
            return

        extra_data = data.get('base', {})

        self._name = data['name']
        self._key = data['key']
        self._machine_type = data['machine_type']
        self._machine_name = data['model']
        self._user_img = data['img']
        self._description = extra_data.get('description')
        self._device_status = data['device_status']
        self._is_printing = data['is_printing']
        self._material_used = extra_data.get('material_used')
        self._set_total_print_time(extra_data.get('print_totaltime'))
        self._print_count = extra_data.get('print_count')
        self._machine_mac = extra_data.get('machine_mac')
        self._create_time = extra_data.get('create_time')
        self._set_machine_data(data.get('machine_data'))
        self._set_type_function_ids(data['type_function_ids'])
        self._set_material_type(extra_data.get('material_type'))
        self._set_parameter(data.get('parameter'))
        self._update_fw_version_from_json(data['version'])
        self._set_tools(data.get('tools'))
        self._update_multi_color_box_fw_version_from_json(data.get('multi_color_box_version'))
        self._set_external_shelves(data.get('external_shelves'))
        self._set_multi_color_box(data.get('multi_color_box'))

    def _check_latest_project_id_valid(
        self,
        incoming_project_id: int,
    ) -> bool:
        try:
            project_id = int(incoming_project_id)
        except Exception:
            project_id = -1

        return (
            self._latest_project is not None
            and (
                project_id < 0
                or project_id == self._latest_project.id
            )
        )

    def _update_latest_project_with_mqtt_print_status_data(
        self,
        incoming_project_id: int,
        print_status: AnycubicPrintStatus,
        mqtt_data: AnycubicConsumableData | None = None,
        paused: int | None = None,
        reason: str | None = None,
    ) -> bool:
        self._set_job_download_progress(0)

        if self._check_latest_project_id_valid(incoming_project_id):
            assert self._latest_project
            self._latest_project.update_with_mqtt_print_status_data(
                print_status,
                mqtt_data,
                paused=paused,
                reason=reason,
            )

            return True

        elif mqtt_data:
            mqtt_data.force_empty()

        return False

    def _update_latest_project_with_mqtt_download_status_data(
        self,
        incoming_project_id: int,
        mqtt_data: AnycubicConsumableData,
    ) -> bool:
        self._set_job_download_progress(int(mqtt_data['progress']))

        if self._check_latest_project_id_valid(incoming_project_id):
            assert self._latest_project
            self._latest_project.update_with_mqtt_download_status_data(
                mqtt_data,
            )

            return True

        return False

    def _update_latest_project_with_mqtt_checking_status_data(
        self,
        incoming_project_id: int,
    ) -> bool:
        self._set_job_download_progress(0)

        if self._check_latest_project_id_valid(incoming_project_id):
            assert self._latest_project
            self._latest_project.update_with_mqtt_checking_status_data()

            return True

        return False

    def _update_latest_project_slice_param(
        self,
        incoming_project_id: int,
        new_slice_param: str | dict[str, Any] | None,
    ) -> bool:
        if self._check_latest_project_id_valid(incoming_project_id):
            assert self._latest_project
            self._latest_project.set_slice_param(
                new_slice_param,
            )

            return True

        return False

    def _update_latest_project_target_temps(
        self,
        incoming_project_id: int,
        new_target_hotbed_temp: int,
        new_target_nozzle_temp: int,
    ) -> bool:
        if self._check_latest_project_id_valid(incoming_project_id):
            assert self._latest_project
            self._latest_project.update_target_temps(
                new_target_hotbed_temp,
                new_target_nozzle_temp,
            )

            return True

        return False

    def _process_mqtt_update_lastwill(
        self,
        action: str,
        state: str,
        payload: AnycubicConsumableData,
    ) -> None:
        if action == 'onlineReport' and state == 'online':
            self._device_status = 1
            return
        elif action == 'onlineReport' and state == 'offline':
            self._device_status = 2
            return
        else:
            raise AnycubicMQTTUnknownUpdate(ErrorsMQTTUpdate.lastwill)

    def _process_mqtt_update_user(
        self,
        action: str,
        state: str,
        payload: AnycubicConsumableData,
    ) -> None:
        if action == 'bindQuery' and state == 'done':
            self._is_bound_to_user = True
            return
        elif action == 'unbind' and state == 'done':
            self._is_bound_to_user = False
            return
        else:
            raise AnycubicMQTTUnknownUpdate(ErrorsMQTTUpdate.user)

    def _process_mqtt_update_status(
        self,
        action: str,
        state: str,
        payload: AnycubicConsumableData,
    ) -> None:
        if action == 'workReport' and state == 'free':
            self._is_printing = 1
            return
        elif action == 'workReport' and state == 'busy':
            self._is_printing = 2
            return
        else:
            raise AnycubicMQTTUnknownUpdate(ErrorsMQTTUpdate.printer_status)

    def _process_mqtt_update_ota_multicolorbox(
        self,
        action: str,
        state: str,
        payload: AnycubicConsumableData,
        box_id: int,
    ) -> None:
        data = payload.get('data', {})
        if (
            self.multi_color_box_fw_version is None or
            len(self.multi_color_box_fw_version) < (box_id + 1)
        ):
            return

        if action == 'update' and state == 'start':
            self.multi_color_box_fw_version[box_id].set_is_updating(True)
            return
        elif action == 'update' and state in ['update-success', 'updateSuccessProcessed']:
            # Not needed
            return
        elif action == 'reportVersion' and state == 'done':
            data.get('device_unionid')
            data.get('machine_version')
            data.get('peripheral_version')
            data.get('model_id')
            self.multi_color_box_fw_version[box_id].update_version(data['firmware_version'])
            return
        elif action == 'update' and state == 'downloading':
            self.multi_color_box_fw_version[box_id].set_is_updating(True)
            self.multi_color_box_fw_version[box_id].set_is_downloading(True)
            self.multi_color_box_fw_version[box_id].set_download_progress(data['progress'])
            return
        elif action == 'update' and state == 'updating':
            self.multi_color_box_fw_version[box_id].set_is_updating(True)
            self.multi_color_box_fw_version[box_id].set_is_downloading(False)
            self.multi_color_box_fw_version[box_id].set_update_progress(data['current_progress'])
            return
        else:
            raise AnycubicMQTTUnknownUpdate(ErrorsMQTTUpdate.ota_ace)

    def _process_mqtt_update_ota_printer(
        self,
        action: str,
        state: str,
        payload: AnycubicConsumableData,
    ) -> None:
        data = payload.get('data', {})

        if action == 'reportVersion' and state == 'done':
            data.get('device_unionid')
            data.get('machine_version')
            data.get('peripheral_version')
            data.get('model_id')
            if self.fw_version is not None:
                self.fw_version.update_version(data['firmware_version'])
            return
        elif action == 'update' and state == 'start':
            if self.fw_version is not None:
                self.fw_version.set_is_updating(True)
            return
        elif action == 'update' and state == 'downloading':
            if self.fw_version is not None:
                self.fw_version.set_is_updating(True)
                self.fw_version.set_is_downloading(True)
                self.fw_version.set_download_progress(data['progress'])
            return
        elif action == 'update' and state == 'updating':
            if self.fw_version is not None:
                self.fw_version.set_is_updating(True)
                self.fw_version.set_is_downloading(False)
                self.fw_version.set_update_progress(data['current_progress'])
            return
        else:
            raise AnycubicMQTTUnknownUpdate(ErrorsMQTTUpdate.ota_printer)

    def _record_error_code(
        self,
        code: Any,
        message: Any,
    ) -> None:
        """Keep a code that means something is wrong, ignore one that does not."""
        if not isinstance(code, int) or isinstance(code, bool):
            return

        if code in PRINTER_OK_CODES:
            return

        self._latest_error_code = code
        self._latest_error_message = str(message) if message else None

    def _process_mqtt_update_event(
        self,
        action: str,
        state: str,
        payload: AnycubicConsumableData,
    ) -> None:
        """A printer event -- how a fault announces itself.

        The code itself rides on the envelope and is picked up for every
        message type, so there is nothing to read out here. What this does is
        stop the message being unknown: without a branch it raised
        AnycubicMQTTUnknownUpdate, the whole payload was thrown away, and the
        only trace was a "Message not understood" line in the debug log --
        which is exactly where a Kobra X's filament run-out was going (#21).

        The shape of the nested data is not yet known from a real capture, so
        nothing is claimed about it. Anything in there that is not consumed
        surfaces through the usual unhandled-data warning, which is how the
        shape gets learned rather than guessed.
        """
        data = payload.get('data')

        if data:
            data.get('code')
            data.get('msg')
            data.get('msgid')
            data.get('state')
            data.get('action')

    def _process_mqtt_update_axis(
        self,
        action: str,
        state: str,
        payload: AnycubicConsumableData,
    ) -> None:
        if action == 'query' and state == 'done':
            data = payload['data']
            # A Kobra X answers the query without coordinates at all during a
            # print. No reading is better than a raise that loses the report.
            coords = data.get('coordinates')

            if coords:
                self._axis_position = AnycubicAxisPosition(
                    x=coords['x'],
                    y=coords['y'],
                    z=coords['z'],
                )

            # Nested payloads are only released once emptied, and anything left
            # behind raises AnycubicMQTTUnhandledData at the end of dispatch.
            data.get('coordinates')

            return

        if action == 'move':
            # Sent for a jog and for a home alike -- the printer does not
            # distinguish them. `state` goes to 'done' when the motion has
            # finished, which is the only completion signal there is: no
            # position comes with it, so anything wanting coordinates has to
            # ask for them afterwards with QUERY_AXIS_POSITION.
            self._axis_move_state = str(state)

            # Real move reports carry `data: null`, but drain anything nested
            # if a firmware ever does send some -- unread keys raise at the
            # end of dispatch.
            data = payload['data']
            if isinstance(data, dict):
                for nested in list(data):
                    data.get(nested)

            return

        raise AnycubicMQTTUnknownUpdate(ErrorsMQTTUpdate.axis)

    def _process_mqtt_update_temperature(
        self,
        action: str,
        state: str,
        payload: AnycubicConsumableData,
    ) -> None:
        # 'auto' over the cloud, 'query' when asked for locally -- same body.
        if action in ('auto', 'query') and state == 'done':
            data = payload['data']

            # Read every field first: reading is what marks it consumed, and
            # anything left behind raises at the end of dispatch -- so these
            # must not sit inside the conditionals below.
            curr_hotbed = data.get('curr_hotbed_temp')
            curr_nozzle = data.get('curr_nozzle_temp')
            target_hotbed = data.get('target_hotbed_temp')
            target_nozzle = data.get('target_nozzle_temp')

            # Asked for locally, an enclosed printer also answers with the
            # chamber. A Kobra S1 sends zeroes because it has no sensor, so
            # these are kept raw rather than turned into an always-zero entity.
            self._chamber_temp = data.get('curr_chamber_temp')
            self._target_chamber_temp = data.get('target_chamber_temp')

            self._apply_current_temps(curr_hotbed, curr_nozzle)
            self._apply_target_temps(target_hotbed, target_nozzle)

            if self._latest_project:
                self._latest_project.update_target_temps(target_hotbed, target_nozzle)

            return
        else:
            raise AnycubicMQTTUnknownUpdate(ErrorsMQTTUpdate.temperature)

    def _process_mqtt_update_fan(
        self,
        action: str,
        state: str,
        payload: AnycubicConsumableData,
    ) -> None:
        # The cloud pushes these unprompted as action 'auto'; asked for over
        # the local connection the same body comes back as 'query'.
        if action in ('auto', 'query') and state == 'done':
            data = payload['data']

            if 'fan_speed_pct' in data:
                self._fan_speed = int(data['fan_speed_pct'])

            # The Kobra S1 also reports the auxiliary part fan and the ACE box
            # fan here. Both were previously discarded as unhandled data.
            if 'aux_fan_speed_pct' in data:
                self._aux_fan_speed = int(data['aux_fan_speed_pct'])

            if 'box_fan_level' in data:
                self._box_fan_level = int(data['box_fan_level'])

            return
        else:
            raise AnycubicMQTTUnknownUpdate(ErrorsMQTTUpdate.fan)

    def _process_mqtt_update_print(
        self,
        action: str,
        state: str,
        payload: AnycubicConsumableData,
    ) -> None:
        # `or {}` rather than a plain default: a present-but-null `data`
        # hands back None from .get and the chained .get then raises
        # AttributeError. Same trap as the null coercions, different shape.
        project_id = (payload.get('data') or {}).get('taskid', -1)
        if action == 'start' and state == 'printing':
            data = payload['data']
            self._is_printing = 2
            self._update_latest_project_with_mqtt_print_status_data(
                project_id,
                AnycubicPrintStatus.Printing,
                data,
            )
            return
        elif action == 'start' and state == 'downloading':
            data = payload['data']
            self._is_printing = 2
            self._update_latest_project_with_mqtt_download_status_data(
                project_id,
                data,
            )
            return
        elif action == 'start' and state == 'checking':
            self._is_printing = 2
            self._update_latest_project_with_mqtt_checking_status_data(
                project_id,
            )
            return
        elif action == 'start' and state == 'preheating':
            data = payload['data']
            self._is_printing = 2
            self._update_latest_project_with_mqtt_print_status_data(
                project_id,
                AnycubicPrintStatus.Preheating,
                data,
            )
            return
        elif action == 'start' and state == 'finished':
            data = payload['data']
            self._is_printing = 1
            self._update_latest_project_with_mqtt_print_status_data(
                project_id,
                AnycubicPrintStatus.Complete,
                data,
            )
            return
        elif action == 'pause' and state in ['pausing', 'paused']:
            data = payload['data']
            self._is_printing = 2
            self._update_latest_project_with_mqtt_print_status_data(
                project_id,
                AnycubicPrintStatus.Printing,
                data,
                paused=1,
            )
            return
        elif action == 'resume' and state in ['resuming', 'resumed']:
            data = payload['data']
            self._is_printing = 2
            self._update_latest_project_with_mqtt_print_status_data(
                project_id,
                AnycubicPrintStatus.Printing,
                data,
                paused=0 if state == 'resumed' else 1,
            )
            return
        elif action in ['start', 'stop'] and state in ['stoped', 'stopping']:
            data = payload['data']
            self._is_printing = 1
            self._update_latest_project_with_mqtt_print_status_data(
                project_id,
                AnycubicPrintStatus.Cancelled,
                data,
            )
            return
        elif action == 'getSliceParam' and state == 'done':
            data = payload['data']['slice_param']
            self._update_latest_project_slice_param(
                project_id,
                data,
            )
            return
        elif action in ['start', 'update'] and state == 'updated':
            data = payload['data']
            # Not every printer sends every field. An open-frame machine has no
            # chamber, a progress-only update carries no temperatures at all,
            # and one missing key used to throw away the whole update -- so
            # each is applied only if it is actually there.
            settings = data.get('settings') or {}

            if 'curr_hotbed_temp' in data and 'curr_nozzle_temp' in data:
                self._apply_current_temps(
                    data['curr_hotbed_temp'],
                    data['curr_nozzle_temp'],
                )
            if 'fan_speed_pct' in settings:
                self._fan_speed = int(settings['fan_speed_pct'])
            if 'print_speed_pct' in settings:
                self._print_speed_pct = int(settings['print_speed_pct'])
            if 'print_speed_mode' in settings:
                self._print_speed_mode = int(settings['print_speed_mode'])
            if 'target_hotbed_temp' in settings and 'target_nozzle_temp' in settings:
                self._update_latest_project_target_temps(
                    project_id,
                    settings['target_hotbed_temp'],
                    settings['target_nozzle_temp'],
                )
            return
        elif action in ['start', 'stop'] and state in ['failed']:
            err_msg = payload.get('msg')
            self._is_printing = 1
            self._update_latest_project_with_mqtt_print_status_data(
                project_id,
                AnycubicPrintStatus.Cancelled,
                reason=err_msg,
            )
            raise AnycubicAPIError(ErrorsGeneral.print_failed.format(err_msg))
        else:
            raise AnycubicMQTTUnknownUpdate(ErrorsMQTTUpdate.job_status)

    def _process_mqtt_update_multicolorbox(
        self,
        action: str,
        state: str,
        payload: AnycubicConsumableData,
    ) -> None:
        if action == 'getInfo' and state == 'success':
            # Consume the tool-head model so it stops being reported as
            # unhandled data. Not currently surfaced anywhere.
            payload['data'].get('head_tools_model')
            data = payload['data']['multi_color_box']
            self._set_multi_color_box(data)
            return
        elif action in ['setInfo', 'refresh'] and state == 'success':
            data = payload['data']['multi_color_box']
            for box in data:
                box_id = int(box['id'])
                if self.connected_ace_units < box_id + 1:
                    continue
                assert self._multi_color_box
                self._multi_color_box[box_id].update_slots_with_mqtt_data(box['slots'])
            return

        elif action == 'autoUpdateInfo' and state == 'done':
            data = payload['data']
            box_id = int(data['id'])
            loaded_slot = int(data['loaded_slot'])
            if self.connected_ace_units < box_id + 1:
                return

            assert self._multi_color_box
            self._multi_color_box[box_id].set_slot_loaded(loaded_slot)
            return
        elif action in ['autoUpdateDryStatus', 'setDry'] and state == 'success':
            data = payload['data']['multi_color_box']
            for box in data:
                box_id = int(box['id'])
                if self.connected_ace_units < box_id + 1:
                    continue

                assert self._multi_color_box
                self._multi_color_box[box_id].set_current_temperature(box['temp'])
                self._multi_color_box[box_id].set_drying_status(box['drying_status'])
            return
        elif action == 'feedFilament' and state == 'done':
            data = payload['data']['multi_color_box']
            for box in data:
                box_id = int(box['id'])
                if self.connected_ace_units < box_id + 1:
                    continue

                loaded_slot = int(box['loaded_slot'])

                assert self._multi_color_box
                self._multi_color_box[box_id].set_slot_loaded(loaded_slot)
                self._multi_color_box[box_id].set_feed_status(box['feed_status'])
            return
        elif action == 'setAutoFeed' and state == 'done':
            data = payload['data']['multi_color_box']
            for box in data:
                box_id = int(box['id'])
                if self.connected_ace_units < box_id + 1:
                    continue

                assert self._multi_color_box
                self._multi_color_box[box_id].set_auto_feed(box['auto_feed'])
            return
        else:
            raise AnycubicMQTTUnknownUpdate(ErrorsMQTTUpdate.ace)

    def _process_mqtt_update_shelves(
        self,
        action: str,
        state: str,
        payload: AnycubicConsumableData,
    ) -> None:
        if action == 'reportInfo' and state == 'success':
            data = payload['data']
            if self.external_shelves:
                self.external_shelves.update_with_mqtt_data(data)
            return
        else:
            raise AnycubicMQTTUnknownUpdate(ErrorsMQTTUpdate.shelves)

    def _process_mqtt_update_file(
        self,
        action: str,
        state: str,
        payload: AnycubicConsumableData,
    ) -> None:
        if action == 'listLocal' and state == 'done':
            data = payload['data']['records']
            self._set_local_file_list(data)
            return
        elif action == 'deleteLocal' and state == 'success':
            # Not Yet Needed
            return
        elif action == 'listUdisk' and state == 'done':
            data = payload['data']['records']
            self._set_udisk_file_list(data)
            return
        elif action == 'deleteUdisk' and state == 'success':
            # Not Yet Needed
            return
        elif action == 'cloudRecommendList' and state == 'done':
            # Not Yet Needed
            payload.force_empty()
            return
        else:
            raise AnycubicMQTTUnknownUpdate(ErrorsMQTTUpdate.file)

    def _process_mqtt_update_peripherals(
        self,
        action: str,
        state: str,
        payload: AnycubicConsumableData,
    ) -> None:
        if action == 'query' and state == 'done':
            data = payload['data']

            if 'camera' in data:
                self.set_has_peripheral_camera(data['camera'])

            if 'multiColorBox' in data:
                self.set_has_peripheral_multi_color_box(data['multiColorBox'])

            if 'udisk' in data:
                self.set_has_peripheral_udisk(data['udisk'])

            return
        else:
            raise AnycubicMQTTUnknownUpdate(ErrorsMQTTUpdate.peripherals)

    def _process_mqtt_update_light(
        self,
        action: str,
        state: str,
        payload: AnycubicConsumableData,
    ) -> None:
        # Two shapes, depending on the action:
        #   query   -> {'data': {'lights': [{'type': 2, 'status': 1, 'brightness': 100}]}}
        #   control -> {'data': {'type': 2, 'status': 1, 'brightness': 100}}
        if state != 'done':
            raise AnycubicMQTTUnknownUpdate(ErrorsMQTTUpdate.unknown.format('light'))

        data = payload['data']

        if not data:
            return

        if 'lights' in data:
            reported = data['lights']
        elif 'type' in data:
            reported = [{
                'type': data['type'],
                'status': data.get('status'),
                'brightness': data.get('brightness'),
            }]
        else:
            return

        for light in reported:
            light_type = light.get('type')

            if light_type is None:
                continue

            self._lights[int(light_type)] = {
                'status': int(light.get('status') or 0),
                'brightness': int(light.get('brightness') or 0),
            }


    def _process_mqtt_update_info(
        self,
        action: str,
        state: str,
        payload: AnycubicConsumableData,
    ) -> None:
        """A whole-printer snapshot.

        Only the local connection sends this; over the cloud the same ground is
        covered by the separate status, temperature and fan reports. It is the
        only place the printer names its own stream and upload endpoints, and
        the only place it lists which features it physically has.
        """
        data = payload['data']

        if not data:
            return

        urls = data.get('urls')

        if urls:
            self._camera_stream_url = urls.get('rtspUrl')
            self._file_upload_url = urls.get('fileUploadurl')

        self._features = _drain(data.get('features')) or self.features

        temp = data.get('temp')

        if temp:
            self._apply_current_temps(
                temp.get('curr_hotbed_temp'),
                temp.get('curr_nozzle_temp'),
            )
            self._apply_target_temps(
                temp.get('target_hotbed_temp'),
                temp.get('target_nozzle_temp'),
            )
            # A Kobra S1 reports chamber temperatures of zero because it has no
            # chamber sensor, so they are kept raw rather than turned into an
            # always-zero entity.
            self._chamber_temp = temp.get('curr_chamber_temp')
            self._target_chamber_temp = temp.get('target_chamber_temp')
            _drain(temp)

        # All three fans, on the same footing. The fan report carries them too,
        # but this snapshot is the first thing a local connection asks for and
        # the first to answer -- reading only the part fan here left the other
        # two empty until a separate reply arrived.
        if 'fan_speed_pct' in data:
            self._fan_speed = int(data['fan_speed_pct'])
        if 'aux_fan_speed_pct' in data:
            self._aux_fan_speed = int(data['aux_fan_speed_pct'])
        if 'box_fan_level' in data:
            self._box_fan_level = int(data['box_fan_level'])
        if 'print_speed_mode' in data:
            self._print_speed_mode = int(data['print_speed_mode'])

        self._local_firmware_version = data.get('version')
        self._local_ip = data.get('ip')

        # A report arriving at all means the printer is reachable, and the
        # cloud fields that normally drive availability are never set when
        # there is no cloud. Without this every entity reads unavailable on a
        # working local connection.
        self._device_status = 1

        printer_state = data.get('state')

        if printer_state == 'busy':
            self._is_printing = 2
        elif printer_state == 'free':
            self._is_printing = 1

        # Consumed but not modelled: the printer's own name and model strings
        # duplicate what the device already carries, and the project blocks are
        # covered by the print report.
        data.get('printerName')
        data.get('model')
        self._apply_lan_project(data.get('project'))

        # The job that finished last. Null until one has, and then it stays --
        # so a null here never clears what is already known.
        self._set_lan_last_job(_drain(data.get('last_project')))
        _drain(data)

    def _process_mqtt_update_ai_settings(
        self,
        action: str,
        state: str,
        payload: AnycubicConsumableData,
    ) -> None:
        """Foreign-object and first-layer detection settings."""
        data = payload['data']

        if not data:
            return

        self._ai_settings = _drain(data.get('ai_settings')) or self.ai_settings

        _drain(data)


    @property
    def axis_move_state(self) -> str | None:
        """How the last axis move is getting on: 'doing', 'done', or None."""
        return getattr(self, '_axis_move_state', None)

    @property
    def axis_is_moving(self) -> bool:
        """Whether the printer is mid-move or mid-home.

        A refused move reports 'failed', which is finished, not moving.
        """
        return self.axis_move_state not in (None, 'done', 'failed')

    @property
    def axis_move_failed(self) -> bool:
        """Whether the last move was refused.

        The usual cause is an axis that has not been homed: Z in particular
        is not covered by the home-all, and every Z move is refused until it
        has been homed on its own.
        """
        return self.axis_move_state == 'failed'

    @property
    def camera_stream_url(self) -> str | None:
        """Where the printer serves its camera, when it says.

        Only reported over the local connection.
        """
        return getattr(self, '_camera_stream_url', None)

    @property
    def file_upload_url(self) -> str | None:
        """Signed endpoint for uploading gcode straight to the printer."""
        return getattr(self, '_file_upload_url', None)

    @property
    def features(self) -> dict[str, Any]:
        """What this model says it can physically do.

        Reported only over the local connection, and the most reliable way to
        tell models apart without owning one.
        """
        return dict(getattr(self, '_features', {}) or {})

    @property
    def ai_settings(self) -> dict[str, Any]:
        """Foreign-object / first-layer detection settings."""
        return dict(getattr(self, '_ai_settings', {}) or {})

    @property
    def ai_detection_enabled(self) -> bool | None:
        settings = self.ai_settings
        return bool(settings['status']) if 'status' in settings else None

    @property
    def local_firmware_version(self) -> str | None:
        return getattr(self, '_local_firmware_version', None)

    @property
    def chamber_temperature(self) -> float | None:
        """Chamber temperature, where the printer has a sensor for it.

        An open-frame or unsensored machine reports zero here, which is why
        this is not turned into an entity without checking it first.
        """
        return getattr(self, '_chamber_temp', None)

    @property
    def target_chamber_temperature(self) -> float | None:
        return getattr(self, '_target_chamber_temp', None)

    def process_mqtt_update(
        self,
        topic: str,
        payload: AnycubicConsumableData,
    ) -> None:
        msg_type = payload['type']
        action = payload['action']
        state = payload.get('state')
        multi_color_topic = bool('multiColorBox' in topic)

        # Before anything is dispatched, and deliberately.
        #
        # Every message carries a result code, and in normal running it is 200
        # -- "processed", not a fault. It used to be read at the end of this
        # method purely to empty the payload, then dropped, so a printer
        # announcing a real problem was the one thing nothing kept.
        #
        # Reading it here rather than at the end matters: a handler that
        # cannot parse its message raises, and everything after the dispatch
        # never runs. A fault is exactly when an unfamiliar payload turns up,
        # so recording afterwards would lose the codes that matter most.
        #
        # Peeked from the remaining data instead of consumed, so the normal
        # consumption at the end of dispatch is left to work as it always has.
        self._record_error_code(
            payload.remaining_data.get('code'),
            payload.remaining_data.get('msg'),
        )

        if msg_type == 'lastWill':
            self._process_mqtt_update_lastwill(action, state, payload)

        elif msg_type == 'user':
            self._process_mqtt_update_user(action, state, payload)

        elif msg_type == 'status':
            self._process_mqtt_update_status(action, state, payload)

        elif msg_type == 'ota' and multi_color_topic:
            box_id_str = get_part_from_mqtt_topic(topic, 9)
            box_id = int(box_id_str) if box_id_str and box_id_str.isdigit() else 0
            self._process_mqtt_update_ota_multicolorbox(action, state, payload, box_id)

        elif msg_type == 'ota':
            self._process_mqtt_update_ota_printer(action, state, payload)

        elif msg_type == 'tempature':
            self._process_mqtt_update_temperature(action, state, payload)

        elif msg_type == 'fan':
            self._process_mqtt_update_fan(action, state, payload)

        elif msg_type == 'print':
            self._process_mqtt_update_print(action, state, payload)

        elif msg_type == 'multiColorBox':
            self._process_mqtt_update_multicolorbox(action, state, payload)

        elif msg_type == 'axis':
            self._process_mqtt_update_axis(action, state, payload)

        elif msg_type == 'extfilbox':
            self._process_mqtt_update_shelves(action, state, payload)

        elif msg_type == 'file':
            self._process_mqtt_update_file(action, state, payload)

        elif msg_type == 'peripherie':
            self._process_mqtt_update_peripherals(action, state, payload)

        elif msg_type == 'light':
            self._process_mqtt_update_light(action, state, payload)

        elif msg_type == 'info':
            self._process_mqtt_update_info(action, state, payload)

        elif msg_type == 'aiSettings':
            self._process_mqtt_update_ai_settings(action, state, payload)

        elif msg_type in ('event', 'printerevent', 'printer_event'):
            self._process_mqtt_update_event(action, state, payload)

        else:
            raise AnycubicMQTTUnknownUpdate(ErrorsMQTTUpdate.unknown.format(msg_type))

        remaining_data: AnycubicConsumableData | None = payload.get('data')

        if remaining_data:
            remaining_data.get('taskid')
            remaining_data.get('localtask')

        payload.get('data')
        payload.get('msg')
        payload.get('timestamp')
        payload.get('msgid')
        payload.get('code')

        if not payload.is_empty:
            raise AnycubicMQTTUnhandledData(
                "process_mqtt_update",
                unhandled_mqtt_data=payload.remaining_data,
                unhandled_mqtt_type=msg_type,
                unhandled_mqtt_action=action,
                unhandled_mqtt_state=state,
            )

    @property
    def initialisation_error(self) -> bool:
        return self._initialisation_error

    @property
    def machine_type(self) -> int:
        return self._machine_type

    @property
    def model(self) -> str:
        return self._machine_name

    @property
    def machine_name(self) -> str:
        return self._machine_name

    @property
    def latest_error_code(self) -> int | None:
        """The last code the printer reported that was not "all fine"."""
        return self._latest_error_code

    @property
    def latest_error_message(self) -> str | None:
        """Whatever the printer said alongside that code, if anything."""
        return self._latest_error_message

    @property
    def latest_error_description(self) -> str | None:
        """Anycubic's own wording for the last error, or the bare number."""
        if self._latest_error_code is None:
            return None

        return describe_printer_code(self._latest_error_code)

    @property
    def machine_img(self) -> str | None:
        return self._machine_img

    @property
    def net_function_ids(self) -> list[int] | None:
        return self._net_function_ids

    @property
    def net_default_function(self) -> int | None:
        return self._net_default_function

    @property
    def id(self) -> int:
        if self._id is None:
            raise AnycubicAPIError(ErrorsGeneral.noid_printer)
        return self._id

    @property
    def user_id(self) -> int | None:
        return self._user_id

    @property
    def name(self) -> str | None:
        return self._name

    @property
    def nonce(self) -> str | int | None:
        return self._nonce

    @property
    def key(self) -> str | None:
        return self._key

    @property
    def user_img(self) -> str | None:
        return self._user_img

    @property
    def description(self) -> str | None:
        return self._description

    @property
    def printer_type(self) -> str | None:
        return self._printer_type

    @property
    def device_status(self) -> int | None:
        return self._device_status

    @property
    def printer_online(self) -> bool:
        return self._device_status == 1

    @property
    def ready_status(self) -> int | None:
        return self._ready_status

    @property
    def is_printing(self) -> int:
        return self._is_printing

    @property
    def is_available(self) -> bool:
        return self._is_printing == 1

    @property
    def is_busy(self) -> bool:
        return self._is_printing == 2

    @property
    def reason(self) -> str | None:
        return self._reason

    @property
    def current_status(self) -> str:
        if self.is_busy:
            return "busy"
        elif self.is_available:
            return "available"
        else:
            return "unknown"

    @property
    def video_taskid(self) -> int | None:
        return self._video_taskid

    @property
    def msg(self) -> str | None:
        return self._msg

    @property
    def material_used(self) -> str | None:
        return self._material_used

    @property
    def material_used_kg(self) -> float | None:
        """Lifetime filament use as a number. The API reports e.g. '18.01kg'."""
        if not self._material_used:
            return None

        match = re.match(r"\s*([0-9]*\.?[0-9]+)\s*kg", str(self._material_used), re.I)

        if not match:
            return None

        return float(match.group(1))

    @property
    def total_print_time(self) -> str | None:
        return self._total_print_time

    @property
    def total_print_time_delta(self) -> timedelta:
        return self._total_print_time_delta

    @property
    def total_print_time_hrs(self) -> int:
        return self._total_print_time_hrs

    @property
    def total_print_time_dhm_str(self) -> str:
        return self._total_print_time_dhm_str

    @property
    def print_count(self) -> int | None:
        return self._print_count

    @property
    def status(self) -> int | None:
        return self._status

    @property
    def machine_mac(self) -> str | None:
        return self._machine_mac

    @property
    def delete(self) -> int | None:
        return self._delete

    @property
    def create_time(self) -> int | None:
        return self._create_time

    @property
    def delete_time(self) -> int | None:
        return self._delete_time

    @property
    def last_update_time(self) -> int | None:
        return self._last_update_time

    @property
    def machine_data(self) -> AnycubicMachineData | None:
        return self._machine_data

    @property
    def type_function_ids(self) -> list[int]:
        return self._type_function_ids

    @property
    def supports_function_axle_movement(self) -> bool:
        return AnycubicFunctionID.AXLE_MOVEMENT in self._type_function_ids

    @property
    def supports_function_file_manager(self) -> bool:
        return AnycubicFunctionID.FILE_MANAGER in self._type_function_ids

    @property
    def supports_function_exposure_test(self) -> bool:
        return AnycubicFunctionID.EXPOSURE_TEST in self._type_function_ids

    @property
    def supports_function_lcd_peer_video(self) -> bool:
        return AnycubicFunctionID.LCD_PEER_VIDEO in self._type_function_ids

    @property
    def supports_function_fdm_axis_move(self) -> bool:
        return AnycubicFunctionID.FDM_AXIS_MOVE in self._type_function_ids

    @property
    def supports_function_fdm_peer_video(self) -> bool:
        return AnycubicFunctionID.FDM_PEER_VIDEO in self._type_function_ids

    @property
    def supports_function_device_startup_self_test(self) -> bool:
        return AnycubicFunctionID.DEVICE_STARTUP_SELF_TEST in self._type_function_ids

    @property
    def supports_function_print_startup_self_test(self) -> bool:
        return AnycubicFunctionID.PRINT_STARTUP_SELF_TEST in self._type_function_ids

    @property
    def supports_function_automatic_operation(self) -> bool:
        return AnycubicFunctionID.AUTOMATIC_OPERATION in self._type_function_ids

    @property
    def supports_function_residue_clean(self) -> bool:
        return AnycubicFunctionID.RESIDUE_CLEAN in self._type_function_ids

    @property
    def supports_function_novice_guide(self) -> bool:
        return AnycubicFunctionID.NOVICE_GUIDE in self._type_function_ids

    @property
    def supports_function_release_film(self) -> bool:
        return AnycubicFunctionID.RELEASE_FILM in self._type_function_ids

    @property
    def supports_function_task_mode(self) -> bool:
        return AnycubicFunctionID.TASK_MODE in self._type_function_ids

    @property
    def supports_function_lcd_intelligent_materials_box(self) -> bool:
        return AnycubicFunctionID.LCD_INTELLIGENT_MATERIALS_BOX in self._type_function_ids

    @property
    def supports_function_lcd_auto_out_in_materials(self) -> bool:
        return AnycubicFunctionID.LCD_AUTO_OUT_IN_MATERIALS in self._type_function_ids

    @property
    def supports_function_m7pro_automatic_operation(self) -> bool:
        return AnycubicFunctionID.M7PRO_AUTOMATIC_OPERATION in self._type_function_ids

    @property
    def supports_function_multi_color_box(self) -> bool:
        if AnycubicFunctionID.MULTI_COLOR_BOX in self._type_function_ids:
            return True

        # The function list comes from the cloud, and a printer reached only
        # over its own network has none. One that is reporting a box plainly
        # supports one, whatever any list says.
        return self.connected_ace_units > 0

    @property
    def supports_function_ai_detection(self) -> bool:
        return AnycubicFunctionID.AI_DETECTION in self._type_function_ids

    @property
    def supports_function_auto_leveler(self) -> bool:
        return AnycubicFunctionID.AUTO_LEVELER in self._type_function_ids

    @property
    def supports_function_vibration_compensation(self) -> bool:
        return AnycubicFunctionID.VIBRATION_COMPENSATION in self._type_function_ids

    @property
    def supports_function_time_lapse(self) -> bool:
        return AnycubicFunctionID.TIME_LAPSE in self._type_function_ids

    @property
    def supports_function_video_light(self) -> bool:
        return AnycubicFunctionID.VIDEO_LIGHT in self._type_function_ids

    @property
    def supports_function_box_light(self) -> bool:
        return AnycubicFunctionID.BOX_LIGHT in self._type_function_ids

    @property
    def supported_function_strings(self) -> list[str]:
        func_ids = list()
        for func_int in self._type_function_ids:
            try:
                func_ids.append(AnycubicFunctionID(int(func_int)))
            except ValueError:
                pass

        return list([
            func_id.name for func_id in func_ids
        ])

    @property
    def fan_speed_pct(self) -> int | None:
        """The model fan as the PRINTER reports it.

        Not the same as the sliced job's setting, which is what the project
        carries and which reads 0 on an idle printer -- the fan entity showed
        a confident 0% for exactly that reason. Parsed from MQTT since
        forever, but never exposed, so nothing could read it.
        """
        return self._fan_speed

    @property
    def aux_fan_speed_pct(self) -> int | None:
        return self._aux_fan_speed

    @property
    def print_speed_pct(self) -> int | None:
        """The print speed as the PRINTER reports it.

        The same story as the model fan: parsed out of the MQTT settings blob
        and the local info snapshot since forever, and never exposed, so
        nothing could read it. Everything asking for a print speed was asking
        the sliced job instead -- which a printer reached over its own network
        has none of, so a Kobra X printing happily reported nothing at all.
        """
        return self._print_speed_pct

    @property
    def print_speed_mode(self) -> int | None:
        """The speed mode the printer says it is in, as its own integer.

        The mode's *name* only ever comes from the cloud, which publishes the
        list of modes a machine offers. A local connection has no such list,
        so the number is all there is -- and it is still enough to automate on.
        """
        return self._print_speed_mode

    @property
    def box_fan_level(self) -> int | None:
        return self._box_fan_level

    @property
    def light_type(self) -> int | None:
        """The light `type` this printer reports. Kobra S1 uses 2, not 1."""
        if not self._lights:
            return None

        return sorted(self._lights.keys())[0]

    @property
    def has_controllable_light(self) -> bool:
        return bool(self._lights)

    @property
    def light_is_on(self) -> bool:
        light_type = self.light_type

        if light_type is None:
            return False

        return bool(self._lights[light_type]['status'])

    @property
    def light_brightness_pct(self) -> int | None:
        light_type = self.light_type

        if light_type is None:
            return None

        return self._lights[light_type]['brightness']

    @property
    def has_peripheral_camera(self) -> bool | None:
        return self._has_peripheral_camera

    @property
    def has_peripheral_multi_color_box(self) -> bool | None:
        return self._has_peripheral_multi_color_box

    @property
    def has_peripheral_udisk(self) -> bool | None:
        return self._has_peripheral_udisk

    @property
    def connected_peripherals(self) -> dict[str, bool | None]:
        return {
            "camera": self.has_peripheral_camera,
            "ace": self.has_peripheral_multi_color_box,
            "usb_disk": self.has_peripheral_udisk,
        }

    @property
    def material_type(self) -> AnycubicPrinterMaterialType | str | None:
        return self._material_type

    @property
    def parameter(self) -> AnycubicMachineParameter | None:
        if not self._parameter:
            return None

        return self._parameter

    @property
    def fw_version(self) -> AnycubicMachineFirmwareInfo | None:
        return self._fw_version

    @property
    def available(self) -> int | None:
        return self._available

    @property
    def color(self) -> AnycubicMachineColorInfo | None:
        return self._color

    @property
    def advance(self) -> list[Any] | None:
        return self._advance

    @property
    def tools(self) -> list[AnycubicMachineToolInfo] | None:
        return self._tools

    @property
    def multi_color_box_fw_version(self) -> list[AnycubicMachineFirmwareInfo] | None:
        return self._multi_color_box_fw_version

    @property
    def axis_position(self) -> AnycubicAxisPosition | None:
        """Last reported head position. None until request_axis_position runs."""
        return self._axis_position

    @property
    def external_shelves(self) -> AnycubicMachineExternalShelves | None:
        return self._external_shelves

    @property
    def multi_color_box(self) -> list[AnycubicMultiColorBox] | None:
        return self._multi_color_box

    @property
    def connected_ace_units(self) -> int:
        if self._multi_color_box is None:
            return 0

        return len(self._multi_color_box)

    @property
    def primary_multi_color_box(self) -> AnycubicMultiColorBox | None:
        if self.connected_ace_units > 0:
            assert self._multi_color_box
            return self._multi_color_box[0]

        return None

    @property
    def secondary_multi_color_box(self) -> AnycubicMultiColorBox | None:
        if self.connected_ace_units > 1:
            assert self._multi_color_box
            return self._multi_color_box[1]

        return None

    @property
    def primary_drying_status(self) -> AnycubicDryingStatus | None:
        if self.primary_multi_color_box is None:
            return None

        return self.primary_multi_color_box.drying_status

    @property
    def secondary_drying_status(self) -> AnycubicDryingStatus | None:
        if self.secondary_multi_color_box is None:
            return None

        return self.secondary_multi_color_box.drying_status

    @property
    def latest_project(self) -> AnycubicProject | None:
        return self._latest_project

    @property
    def local_file_list_object(self) -> list[dict[str, str | float]] | None:
        if not self._local_file_list or len(self._local_file_list) < 1:
            return None

        file_list = list([
            file.data_object for file in self._local_file_list
        ])
        return file_list

    @property
    def udisk_file_list_object(self) -> list[dict[str, str | float]] | None:
        if not self._udisk_file_list or len(self._udisk_file_list) < 1:
            return None

        file_list = list([
            file.data_object for file in self._udisk_file_list
        ])
        return file_list

    @property
    def primary_multi_color_box_fw_firmware_version(self) -> str | None:
        if (
            self.multi_color_box_fw_version and
            len(self.multi_color_box_fw_version) > 0
        ):
            return self.multi_color_box_fw_version[0].firmware_version

        return None

    @property
    def primary_multi_color_box_fw_available_version(self) -> str | None:
        if (
            self.multi_color_box_fw_version and
            len(self.multi_color_box_fw_version) > 0
        ):
            return self.multi_color_box_fw_version[0].available_version

        return None

    @property
    def primary_multi_color_box_fw_total_progress(self) -> int | float | bool | None:
        if (
            self.multi_color_box_fw_version and
            len(self.multi_color_box_fw_version) > 0
        ):
            return self.multi_color_box_fw_version[0].total_progress

        return None

    @property
    def primary_multi_color_box_auto_feed(self) -> int | None:
        if self.primary_multi_color_box:
            return self.primary_multi_color_box.auto_feed

        return None

    @property
    def primary_multi_color_box_spool_info_object(self) -> list[dict[str, Any]] | None:
        if self.primary_multi_color_box:
            return self.primary_multi_color_box.spool_info_object

        return None

    @property
    def primary_multi_color_box_current_temperature(self) -> int:
        if self.primary_multi_color_box:
            return self.primary_multi_color_box.current_temperature

        return 0

    @property
    def primary_multi_color_box_info_object(self) -> dict[str, Any] | None:
        if self.primary_multi_color_box:
            return self.primary_multi_color_box.box_info_object

        return None

    @property
    def primary_multi_color_box_loaded_slot(self) -> int | None:
        box = self.primary_multi_color_box

        if not box:
            return None

        slot = box.loaded_slot

        # -1 means nothing is loaded; surface that as unknown rather than a
        # slot number that doesn't exist.
        if slot is not None and slot >= 0:
            return slot

        # Some printers leave the box-level field at -1 even mid-print, while
        # still marking the feeding slot's own status as loaded. Observed on a
        # Kobra S1 printing from slot 3. Without this the filament used by such
        # a job cannot be charged to any spool.
        for spool in box.slots or []:
            if spool is not None and spool.spool_loaded:
                return int(spool.slot_index)

        return None

    @property
    def primary_drying_status_is_drying(self) -> bool | None:
        if self.primary_drying_status:
            return self.primary_drying_status.is_drying

        return None

    @property
    def primary_drying_status_raw_status_code(self) -> int | None:
        if self.primary_drying_status:
            return self.primary_drying_status.raw_status_code

        return None

    @property
    def primary_drying_status_target_temperature(self) -> int:
        if self.primary_drying_status:
            return self.primary_drying_status.target_temperature

        return 0

    @property
    def primary_drying_status_total_duration(self) -> int:
        if self.primary_drying_status:
            return self.primary_drying_status.total_duration

        return 0

    @property
    def primary_drying_status_remaining_time(self) -> int:
        if self.primary_drying_status:
            return self.primary_drying_status.remaining_time

        return 0

    @property
    def secondary_multi_color_box_fw_firmware_version(self) -> str | None:
        if (
            self.multi_color_box_fw_version and
            len(self.multi_color_box_fw_version) > 1
        ):
            return self.multi_color_box_fw_version[1].firmware_version

        return None

    @property
    def secondary_multi_color_box_fw_available_version(self) -> str | None:
        if (
            self.multi_color_box_fw_version and
            len(self.multi_color_box_fw_version) > 1
        ):
            return self.multi_color_box_fw_version[1].available_version

        return None

    @property
    def secondary_multi_color_box_fw_total_progress(self) -> int | float | bool | None:
        if (
            self.multi_color_box_fw_version and
            len(self.multi_color_box_fw_version) > 1
        ):
            return self.multi_color_box_fw_version[1].total_progress

        return None

    @property
    def secondary_multi_color_box_auto_feed(self) -> int | None:
        if self.secondary_multi_color_box:
            return self.secondary_multi_color_box.auto_feed

        return None

    @property
    def secondary_multi_color_box_spool_info_object(self) -> list[dict[str, Any]] | None:
        if self.secondary_multi_color_box:
            return self.secondary_multi_color_box.spool_info_object

        return None

    @property
    def secondary_multi_color_box_loaded_slot(self) -> int | None:
        """Which slot is feeding on the second ACE, or None.

        Mirrors primary_multi_color_box_loaded_slot. A printer with two boxes
        reported this all along -- it was parsed and then had no accessor, so
        the only way to know which slot the second unit was feeding from was
        to not know (hass-anycubic #33).
        """
        box = self.secondary_multi_color_box

        if not box:
            return None

        slot = box.loaded_slot

        # -1 means nothing is loaded; surface that as unknown rather than a
        # slot number that doesn't exist.
        if slot is not None and slot >= 0:
            return slot

        return None

    @property
    def secondary_multi_color_box_current_temperature(self) -> int:
        if self.secondary_multi_color_box:
            return self.secondary_multi_color_box.current_temperature

        return 0

    @property
    def secondary_drying_status_is_drying(self) -> bool | None:
        if self.secondary_drying_status:
            return self.secondary_drying_status.is_drying

        return None

    @property
    def secondary_drying_status_raw_status_code(self) -> int | None:
        if self.secondary_drying_status:
            return self.secondary_drying_status.raw_status_code

        return None

    @property
    def secondary_drying_status_target_temperature(self) -> int:
        if self.secondary_drying_status:
            return self.secondary_drying_status.target_temperature

        return 0

    @property
    def secondary_drying_status_total_duration(self) -> int:
        if self.secondary_drying_status:
            return self.secondary_drying_status.total_duration

        return 0

    @property
    def secondary_drying_status_remaining_time(self) -> int:
        if self.secondary_drying_status:
            return self.secondary_drying_status.remaining_time

        return 0

    @property
    def latest_project_name(self) -> str | None:
        if self.latest_project:
            return self.latest_project.name

        return None

    @property
    def latest_project_image_url(self) -> str | None:
        if self.latest_project:
            return self.latest_project.image_url

        return None

    @property
    def latest_project_progress_percentage(self) -> int | None:
        if self.latest_project:
            return self.latest_project.progress_percentage

        return None

    @property
    def latest_project_created_timestamp(self) -> int | None:
        if self.latest_project:
            return self.latest_project.created_timestamp

        return None

    @property
    def latest_project_finished_timestamp(self) -> int | None:
        if self.latest_project:
            return self.latest_project.finished_timestamp

        return None

    @property
    def latest_project_print_time_elapsed_minutes(self) -> int | None:
        if self.latest_project:
            return self.latest_project.print_time_elapsed_minutes

        return None

    @property
    def latest_project_print_time_remaining_minutes(self) -> int | None:
        if self.latest_project:
            return self.latest_project.print_time_remaining_minutes

        return None

    @property
    def latest_project_print_status_message(self) -> str | None:
        if self.latest_project:
            return self.latest_project.print_status_message

        return None

    @property
    def latest_project_print_total_time(self) -> str | None:
        if self.latest_project:
            return self.latest_project.print_total_time

        return None

    @property
    def latest_project_print_total_time_delta(self) -> timedelta | None:
        if self.latest_project:
            return self.latest_project.print_total_time_delta

        return None

    @property
    def latest_project_print_total_time_minutes(self) -> int | None:
        if self.latest_project:
            return self.latest_project.print_total_time_minutes

        return None

    @property
    def latest_project_print_total_time_dhm_str(self) -> str | None:
        if self.latest_project:
            return self.latest_project.print_total_time_dhm_str

        return None

    @property
    def latest_project_print_in_progress(self) -> bool | None:
        if self.latest_project:
            return self.latest_project.print_in_progress

        return None

    @property
    def latest_project_print_complete(self) -> bool | None:
        if self.latest_project:
            return self.latest_project.print_complete

        return None

    @property
    def latest_project_print_failed(self) -> bool | None:
        if self.latest_project:
            return self.latest_project.print_failed

        return None

    @property
    def latest_project_print_is_paused(self) -> bool | None:
        if self.latest_project:
            return self.latest_project.print_is_paused

        return None

    @property
    def latest_project_print_status(self) -> str | None:
        if self.latest_project:
            return self.latest_project.print_status

        return None

    @property
    def latest_project_print_approximate_completion_time(self) -> int | None:
        if self.latest_project:
            return self.latest_project.print_approximate_completion_time

        return None

    @property
    def latest_project_print_current_layer(self) -> int | None:
        if self.latest_project:
            return self.latest_project.print_current_layer

        return None

    @property
    def latest_project_job_details(self) -> dict[str, Any] | None:
        if self.latest_project:
            return self.latest_project.job_details_object

        return None

    @property
    def latest_project_supplies_usage(self) -> int | None:
        """Filament consumed by the current job, as reported by the printer."""
        if self.latest_project:
            return self.latest_project.print_supplies_usage

        return None

    @property
    def latest_project_print_supplies_usage(self) -> int | None:
        if self.latest_project:
            return self.latest_project.print_supplies_usage

        return None

    @property
    def latest_project_print_total_layers(self) -> int | None:
        if self.latest_project:
            return self.latest_project.print_total_layers

        return None

    @property
    def latest_project_target_nozzle_temp(self) -> int | None:
        if self.latest_project:
            from_project = self.latest_project.target_nozzle_temp

            if from_project is not None:
                return from_project

        # The printer reports its setpoint whether or not a job knows it. A
        # job built from the printer's own report carries no temperatures, so
        # without this a local print showed no target while visibly heating.
        return getattr(self, '_target_nozzle_temp', None)

    @property
    def latest_project_temp_min_nozzle(self) -> int | None:
        if self.latest_project:
            return self.latest_project.temp_min_nozzle

        return None

    @property
    def latest_project_temp_max_nozzle(self) -> int | None:
        if self.latest_project:
            return self.latest_project.temp_max_nozzle

        return None

    @property
    def latest_project_target_hotbed_temp(self) -> int | None:
        if self.latest_project:
            from_project = self.latest_project.target_hotbed_temp

            if from_project is not None:
                return from_project

        return getattr(self, '_target_hotbed_temp', None)

    @property
    def latest_project_temp_min_hotbed(self) -> int | None:
        if self.latest_project:
            return self.latest_project.temp_min_hotbed

        return None

    @property
    def latest_project_temp_max_hotbed(self) -> int | None:
        if self.latest_project:
            return self.latest_project.temp_max_hotbed

        return None

    @property
    def latest_project_print_speed_mode(self) -> int | None:
        if self.latest_project:
            return self.latest_project.print_speed_mode

        return None

    @property
    def latest_project_print_speed_mode_string(self) -> str | None:
        if self.latest_project:
            return self.latest_project.print_speed_mode_string

        return None

    @property
    def latest_project_print_speed_pct(self) -> int | None:
        if self.latest_project:
            return self.latest_project.print_speed_pct

        return None

    @property
    def latest_project_z_thick(self) -> float | None:
        if self.latest_project:
            return self.latest_project.z_thick

        return None

    @property
    def latest_project_fan_speed_pct(self) -> int | None:
        if self.latest_project:
            return self.latest_project.fan_speed_pct

        return None

    @property
    def latest_project_raw_print_status(self) -> int | None:
        if self.latest_project:
            return self.latest_project.raw_print_status

        return None

    @property
    def latest_project_available_print_speed_modes_data_object(self) -> list[dict[str, str | int]] | None:
        if self.latest_project:
            return self.latest_project.available_print_speed_modes_data_object

        return None

    @property
    def latest_project_print_model_height(self) -> float | None:
        if self.latest_project:
            return self.latest_project.print_model_height

        return None

    @property
    def latest_project_print_anti_alias_count(self) -> int | None:
        if self.latest_project:
            return self.latest_project.print_anti_alias_count

        return None

    @property
    def latest_project_print_on_time(self) -> float | None:
        if self.latest_project:
            return self.latest_project.print_on_time

        return None

    @property
    def latest_project_print_off_time(self) -> float | None:
        if self.latest_project:
            return self.latest_project.print_off_time

        return None

    @property
    def latest_project_print_bottom_time(self) -> float | None:
        if self.latest_project:
            return self.latest_project.print_bottom_time

        return None

    @property
    def latest_project_print_bottom_layers(self) -> int | None:
        if self.latest_project:
            return self.latest_project.print_bottom_layers

        return None

    @property
    def latest_project_print_z_up_height(self) -> float | None:
        if self.latest_project:
            return self.latest_project.print_z_up_height

        return None

    @property
    def latest_project_print_z_up_speed(self) -> int | None:
        if self.latest_project:
            return self.latest_project.print_z_up_speed

        return None

    @property
    def latest_project_print_z_down_speed(self) -> int | None:
        if self.latest_project:
            return self.latest_project.print_z_down_speed

        return None

    @property
    def latest_project_download_progress_percentage(self) -> int:
        if self._job_download_progress:
            return self._job_download_progress
        elif self.latest_project:
            return self.latest_project.download_progress_percentage

        return 0

    @property
    def curr_nozzle_temp(self) -> int | None:
        if self.parameter:
            return self.parameter.curr_nozzle_temp

        return None

    @property
    def curr_hotbed_temp(self) -> int | None:
        if self.parameter:
            return self.parameter.curr_hotbed_temp

        return None

    def build_mapping_for_material_list(
        self,
        slot_index_list: list[int],
        material_list: list[dict[str, Any]],
    ) -> list[AnycubicMaterialMapping]:
        if not self._multi_color_box:
            return list()

        highest_box = max(slot_index_list) // 4

        if self.connected_ace_units < highest_box + 1:
            raise AnycubicAPIError(ErrorsGeneral.insufficent_ace_units.format(
                highest_box + 1
            ))

        ams_box_mapping = list()

        for mcb in self._multi_color_box:

            ams_box_mapping.extend(
                mcb.build_mapping_for_material_list(
                    slot_index_list=slot_index_list,
                    material_list=material_list,
                )
            )

        return sorted(ams_box_mapping, key=lambda x: x.paint_index)

    async def update_info_from_api(
        self,
        with_project: bool = True,
    ) -> None:
        if self._id is None:
            raise AnycubicAPIError(ErrorsGeneral.noid_update_info_from_api)

        await self._api_parent.printer_info_for_id(self._id, self)

        if with_project:
            self._latest_project = await self._api_parent.get_latest_project(
                printer_id=self.id,
                project_to_update=self._latest_project
            )

    async def request_local_file_list(
        self,
    ) -> str | None:

        return await self._api_parent._send_order_list_local_files(
            self,
        )

    async def request_udisk_file_list(
        self,
    ) -> str | None:

        return await self._api_parent._send_order_list_udisk_files(
            self,
        )

    async def delete_local_file(
        self,
        file_name: str,
    ) -> str | None:

        return await self._api_parent._send_order_delete_local_file(
            self,
            file_name=file_name,
        )

    async def delete_udisk_file(
        self,
        file_name: str,
    ) -> str | None:

        return await self._api_parent._send_order_delete_udisk_file(
            self,
            file_name=file_name,
        )

    async def multi_color_box_drying_start(
        self,
        duration: int,
        target_temp: int,
        box_id: int = 0,
    ) -> str | None:
        if self.primary_multi_color_box is None:
            return None

        return await self._api_parent.multi_color_box_drying_start(
            self,
            duration=duration,
            target_temp=target_temp,
            box_id=box_id,
        )

    async def multi_color_box_drying_stop(
        self,
        box_id: int = -1,
    ) -> str | None:
        if self.primary_multi_color_box is None:
            return None

        return await self._api_parent.multi_color_box_drying_stop(
            self,
            box_id=box_id,
        )

    async def multi_color_box_set_auto_feed(
        self,
        enabled: bool,
        box_id: int = -1,
    ) -> str | None:
        if self.primary_multi_color_box is None:
            return None

        return await self._api_parent.multi_color_box_set_auto_feed(
            self,
            enabled=enabled,
            box_id=box_id,
        )

    async def multi_color_box_toggle_auto_feed(
        self,
        box_id: int = -1,
    ) -> str | None:
        if self.primary_multi_color_box is None:
            return None

        return await self._api_parent.multi_color_box_toggle_auto_feed(
            self,
            box_id=box_id,
        )

    async def multi_color_box_get_info(self) -> None:
        return await self._api_parent.multi_color_box_get_info(self)

    async def set_light(
        self,
        light_on: bool,
        brightness: int | None = None,
    ) -> None:
        return await self._api_parent.set_printer_light(
            self,
            light_on=light_on,
            brightness=brightness,
        )

    async def multi_color_box_switch_on_auto_feed(
        self,
        box_id: int = -1,
    ) -> str | None:
        if self.primary_multi_color_box is None:
            return None

        return await self._api_parent.multi_color_box_switch_on_auto_feed(
            self,
            box_id=box_id,
        )

    async def multi_color_box_switch_off_auto_feed(
        self,
        box_id: int = -1,
    ) -> str | None:
        if self.primary_multi_color_box is None:
            return None

        return await self._api_parent.multi_color_box_switch_off_auto_feed(
            self,
            box_id=box_id,
        )

    async def multi_color_box_set_slot(
        self,
        slot_index: int,
        slot_color: AnycubicMaterialColor | None = None,
        slot_material_type: str = "PLA",
        slot_color_red: int | None = None,
        slot_color_green: int | None = None,
        slot_color_blue: int | None = None,
        box_id: int = 0,
    ) -> str | None:
        return await self._api_parent.multi_color_box_set_slot(
            printer=self,
            slot_index=slot_index,
            slot_color=slot_color,
            slot_material_type=slot_material_type,
            slot_color_red=slot_color_red,
            slot_color_green=slot_color_green,
            slot_color_blue=slot_color_blue,
            box_id=box_id,
        )

    async def multi_color_box_set_pla_slot(
        self,
        slot_index: int,
        slot_color: AnycubicMaterialColor,
        box_id: int = 0,
    ) -> str | None:

        return await self._api_parent.multi_color_box_set_pla_slot(
            printer=self,
            slot_index=slot_index,
            slot_color=slot_color,
            box_id=box_id,
        )

    async def multi_color_box_set_petg_slot(
        self,
        slot_index: int,
        slot_color: AnycubicMaterialColor,
        box_id: int = 0,
    ) -> str | None:

        return await self._api_parent.multi_color_box_set_petg_slot(
            printer=self,
            slot_index=slot_index,
            slot_color=slot_color,
            box_id=box_id,
        )

    async def multi_color_box_set_abs_slot(
        self,
        slot_index: int,
        slot_color: AnycubicMaterialColor,
        box_id: int = 0,
    ) -> str | None:

        return await self._api_parent.multi_color_box_set_abs_slot(
            printer=self,
            slot_index=slot_index,
            slot_color=slot_color,
            box_id=box_id,
        )

    async def multi_color_box_set_pacf_slot(
        self,
        slot_index: int,
        slot_color: AnycubicMaterialColor,
        box_id: int = 0,
    ) -> str | None:

        return await self._api_parent.multi_color_box_set_pacf_slot(
            printer=self,
            slot_index=slot_index,
            slot_color=slot_color,
            box_id=box_id,
        )

    async def multi_color_box_set_pc_slot(
        self,
        slot_index: int,
        slot_color: AnycubicMaterialColor,
        box_id: int = 0,
    ) -> str | None:

        return await self._api_parent.multi_color_box_set_pc_slot(
            printer=self,
            slot_index=slot_index,
            slot_color=slot_color,
            box_id=box_id,
        )

    async def multi_color_box_set_asa_slot(
        self,
        slot_index: int,
        slot_color: AnycubicMaterialColor,
        box_id: int = 0,
    ) -> str | None:

        return await self._api_parent.multi_color_box_set_asa_slot(
            printer=self,
            slot_index=slot_index,
            slot_color=slot_color,
            box_id=box_id,
        )

    async def multi_color_box_set_hips_slot(
        self,
        slot_index: int,
        slot_color: AnycubicMaterialColor,
        box_id: int = 0,
    ) -> str | None:

        return await self._api_parent.multi_color_box_set_hips_slot(
            printer=self,
            slot_index=slot_index,
            slot_color=slot_color,
            box_id=box_id,
        )

    async def multi_color_box_set_pa_slot(
        self,
        slot_index: int,
        slot_color: AnycubicMaterialColor,
        box_id: int = 0,
    ) -> str | None:

        return await self._api_parent.multi_color_box_set_pa_slot(
            printer=self,
            slot_index=slot_index,
            slot_color=slot_color,
            box_id=box_id,
        )

    async def multi_color_box_set_pla_se_slot(
        self,
        slot_index: int,
        slot_color: AnycubicMaterialColor,
        box_id: int = 0,
    ) -> str | None:

        return await self._api_parent.multi_color_box_set_pla_se_slot(
            printer=self,
            slot_index=slot_index,
            slot_color=slot_color,
            box_id=box_id,
        )

    async def pause_print(
        self,
        project: AnycubicProject | None = None,
    ) -> str | None:

        return await self._api_parent.pause_print(
            self,
            project=project,
        )

    async def resume_print(
        self,
        project: AnycubicProject | None = None,
    ) -> str | None:

        return await self._api_parent.resume_print(
            self,
            project=project,
        )

    async def cancel_print(
        self,
        project: AnycubicProject | None = None,
    ) -> str | None:

        return await self._api_parent.cancel_print(
            self,
            project=project,
        )

    async def multi_color_box_feed_filament(
        self,
        slot_index: int,
        box_id: int = -1,
        finish: bool = False,
    ) -> str | None:

        return await self._api_parent.multi_color_box_feed_filament(
            self,
            slot_index=slot_index,
            box_id=box_id,
            finish=finish,
        )

    async def multi_color_box_retract_filament(
        self,
        box_id: int = -1,
    ) -> str | None:

        return await self._api_parent.multi_color_box_retract_filament(
            self,
            box_id=box_id,
        )

    async def update_printer_firmware(
        self,
    ) -> str | None:

        return await self._api_parent.update_printer_firmware(
            self,
        )

    async def update_printer_multi_color_box_firmware(
        self,
        box_id: int = -1,
    ) -> str | None:

        return await self._api_parent.update_printer_multi_color_box_firmware(
            self,
            box_id=box_id,
        )

    async def update_printer_all_multi_color_box_firmware(
        self,
    ) -> list[str | None] | None:

        return await self._api_parent.update_printer_all_multi_color_box_firmware(
            self,
        )

    async def print_with_cloud_file_id(
        self,
        cloud_file_id: int,
        ams_box_mapping: list[AnycubicMaterialMapping] | None = None,
        temp_file: bool = False,
    ) -> str | None:
        return await self._api_parent.print_with_cloud_file_id(
            printer=self,
            cloud_file_id=cloud_file_id,
            ams_box_mapping=ams_box_mapping,
            temp_file=temp_file,
        )

    async def print_with_cloud_gcode_id(
        self,
        gcode_id: int,
        slot_index_list: list[int] | None = None,
    ) -> AnycubicPrintResponse:
        return await self._api_parent.print_with_cloud_gcode_id(
            printer=self,
            gcode_id=gcode_id,
            slot_index_list=slot_index_list,
        )

    async def print_local_file(
        self,
        file_name: str,
        file_path: str = "",
    ) -> str | None:
        """Print a file already stored on the printer.

        Unlike print_and_upload_*, nothing is transferred -- the file is one the
        printer already holds, as listed by request_local_file_list.
        """
        return await self._api_parent._send_order_print_local_file(
            printer=self,
            file_name=file_name,
            file_path=file_path,
        )

    async def print_and_upload_save_in_cloud(
        self,
        full_file_path: str | None = None,
        file_name: str | None = None,
        file_bytes: bytes | None = None,
        slot_index_list: list[int] | None = None,
    ) -> AnycubicPrintResponse:
        return await self._api_parent.print_and_upload_save_in_cloud(
            printer=self,
            full_file_path=full_file_path,
            file_name=file_name,
            file_bytes=file_bytes,
            slot_index_list=slot_index_list,
        )

    async def print_and_upload_no_cloud_save(
        self,
        full_file_path: str | None = None,
        file_name: str | None = None,
        file_bytes: bytes | None = None,
        slot_index_list: list[int] | None = None,
    ) -> AnycubicPrintResponse:
        return await self._api_parent.print_and_upload_no_cloud_save(
            printer=self,
            full_file_path=full_file_path,
            file_name=file_name,
            file_bytes=file_bytes,
            slot_index_list=slot_index_list,
        )

    async def set_target_temperature(
        self,
        target_nozzle_temp: int | None = None,
        target_hotbed_temp: int | None = None,
    ) -> str | None:
        """Heat the nozzle and/or bed, print job or not.

        Unlike change_print_setting_target_* this works on an idle printer --
        it is the order the slicer's One-Click Preheat uses.
        """
        return await self._api_parent._send_order_set_temperature(
            printer=self,
            target_nozzle_temp=target_nozzle_temp,
            target_hotbed_temp=target_hotbed_temp,
        )

    async def set_fan_speed(
        self,
        fan_speed_pct: int | None = None,
        aux_fan_speed_pct: int | None = None,
        box_fan_level: int | None = None,
    ) -> str | None:
        """Set one fan, print job or not."""
        return await self._api_parent._send_order_set_fan_speed(
            printer=self,
            fan_speed_pct=fan_speed_pct,
            aux_fan_speed_pct=aux_fan_speed_pct,
            box_fan_level=box_fan_level,
        )

    async def move_axis(
        self,
        axis: int,
        move_type: int,
        distance: int = 0,
    ) -> str | None:
        """Jog or home an axis. See _send_order_move_axis for the codes."""
        return await self._api_parent._send_order_move_axis(
            printer=self,
            axis=axis,
            move_type=move_type,
            distance=distance,
        )

    async def set_ai_detection(self, enabled: bool) -> str | None:
        """Turn AI print-failure detection on or off."""
        return await self._api_parent._send_order_set_ai_detection(
            printer=self, enabled=enabled,
        )

    async def disengage_motors(self) -> str | None:
        """Release the steppers so the gantry can be pushed by hand.

        The printer forgets where it is afterwards, so an axis has to be
        homed again before it will accept a move.
        """
        return await self._api_parent._send_order_disengage_motors(printer=self)

    async def home_axis(self, axis: int = 4) -> str | None:
        """Home an axis. Required before that axis will accept a jog.

        ⚠ axis=4 does NOT include Z. Verified on a Kobra S1: after a home-all
        every Z move came back 'failed' and the position did not change, and
        only a home with axis=3 made Z movable. The printer's own panel has a
        separate Z home button for exactly this reason.
        """
        return await self.move_axis(axis=axis, move_type=2, distance=0)

    async def change_print_setting_speed_mode(
        self,
        new_speed: int
    ) -> str | None:
        return await self._api_parent._send_order_change_print_settings(
            printer=self,
            print_settings=AnycubicPrintingSettings(
                print_speed_mode=new_speed,
            ),
        )

    async def change_print_setting_target_nozzle_temp(
        self,
        new_temperature: int
    ) -> str | None:
        return await self._api_parent._send_order_change_print_settings(
            printer=self,
            print_settings=AnycubicPrintingSettings(
                target_nozzle_temp=new_temperature,
            ),
        )

    async def change_print_setting_target_hotbed_temp(
        self,
        new_temperature: int
    ) -> str | None:
        return await self._api_parent._send_order_change_print_settings(
            printer=self,
            print_settings=AnycubicPrintingSettings(
                target_hotbed_temp=new_temperature,
            ),
        )

    async def change_print_setting_fan_speed_pct(
        self,
        new_pct: int
    ) -> str | None:
        return await self._api_parent._send_order_change_print_settings(
            printer=self,
            print_settings=AnycubicPrintingSettings(
                fan_speed_pct=new_pct,
            ),
        )

    async def change_print_setting_aux_fan_speed_pct(
        self,
        new_pct: int
    ) -> str | None:
        return await self._api_parent._send_order_change_print_settings(
            printer=self,
            print_settings=AnycubicPrintingSettings(
                aux_fan_speed_pct=new_pct,
            ),
        )

    async def change_print_setting_box_fan_level(
        self,
        new_level: int
    ) -> str | None:
        return await self._api_parent._send_order_change_print_settings(
            printer=self,
            print_settings=AnycubicPrintingSettings(
                box_fan_level=new_level,
            ),
        )

    async def change_print_setting_bottom_layers(
        self,
        new_layers: int
    ) -> str | None:
        return await self._api_parent._send_order_change_print_settings(
            printer=self,
            print_settings=AnycubicPrintingSettings(
                bottom_layers=new_layers,
            ),
        )

    async def change_print_setting_bottom_time(
        self,
        new_time: float
    ) -> str | None:
        return await self._api_parent._send_order_change_print_settings(
            printer=self,
            print_settings=AnycubicPrintingSettings(
                bottom_time=new_time,
            ),
        )

    async def change_print_setting_off_time(
        self,
        new_time: float
    ) -> str | None:
        return await self._api_parent._send_order_change_print_settings(
            printer=self,
            print_settings=AnycubicPrintingSettings(
                off_time=new_time,
            ),
        )

    async def change_print_setting_on_time(
        self,
        new_time: float
    ) -> str | None:
        return await self._api_parent._send_order_change_print_settings(
            printer=self,
            print_settings=AnycubicPrintingSettings(
                on_time=new_time,
            ),
        )

    async def request_axis_position(self) -> None:
        """Ask the printer for its head position. Reply arrives over MQTT."""
        await self._api_parent._send_order_query_axis_position(printer=self)

    async def query_printer_options(
        self,
        project: AnycubicProject | None = None,
    ) -> None:
        return await self._api_parent.query_printer_options(
            printer=self,
            project=project,
        )

    def __repr__(self) -> str:
        if self._id is None:
            return f"AnycubicPrinter(machine_type={self._machine_type}, machine_name={self._machine_name})"
        else:
            return (
                f"AnycubicPrinter(machine_type={self._machine_type}, machine_name={self._machine_name},\n "
                f"id={self.id}, name={self.name}, key={self.key}, printer_type={self.printer_type}, status={self.status}, "
                f"available={self.available},\n "
                f"device_status={self.device_status}, printer_online={self.printer_online}, ready_status={self.ready_status}, "
                f"is_printing={self.is_printing}, reason={self.reason},\n "
                f"machine_data=\n{self.machine_data},\n "
                f"parameter=\n{self.parameter},\n "
                f"fw_version=\n{self.fw_version},\n "
                f"color=\n{self.color},\n "
                f"tools=\n{self.tools},\n "
                f"multi_color_box_fw_version=\n{self.multi_color_box_fw_version},\n "
                f"external_shelves=\n{self.external_shelves},\n "
                f"multi_color_box=\n{self.multi_color_box},\n "
                f"primary_drying_status=\n{self.primary_drying_status},\n "
                f"secondary_drying_status=\n{self.secondary_drying_status},\n "
                f")")
