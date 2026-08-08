from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .printer_properties import AnycubicMaterialMapping


class AnycubicBaseOrderRequest:
    __slots__ = (
        "_order_id",
        "_printer_id",
    )

    def __init__(
        self,
        order_id: int | None = None,
        printer_id: int | None = None,
    ) -> None:
        if order_id is None:
            raise Exception("AnycubicBaseOrderRequest missing order_id")

        if printer_id is None:
            raise Exception("AnycubicBaseOrderRequest missing printer_id")

        self._order_id: int = int(order_id)
        self._printer_id: int = int(printer_id)

    @property
    def order_request_data(self) -> dict[str, Any]:
        return {
            'order_id': self._order_id,
            'printer_id': self._printer_id,
        }

    @property
    def order_id(self) -> int:
        return self._order_id

    @property
    def order_data(self) -> dict[str, Any] | None:
        """The order's payload, for a transport that carries it differently.

        Sending an order locally reuses this untouched -- the cloud and the
        printer's own broker take the same data -- so it is read here rather
        than rebuilt. Requests with no payload of their own keep this None.
        """
        return None

    @property
    def project_id(self) -> int | None:
        """The project this order belongs to, if it belongs to one."""
        return None

    def __repr__(self) -> str:
        return (
            f"AnycubicBaseOrderRequest("
            f"order_id={self._order_id}, "
            f"printer_id={self._printer_id})"
        )


class AnycubicPrinterOrderRequest(AnycubicBaseOrderRequest):
    """An order aimed at the printer itself, carrying no project.

    ⚠ Not the same as sending project_id=0. The slicer omits the field
    entirely for printer-level orders, and at least MOVE_AXLE quietly does
    nothing when it is present -- the server still answers "Operation
    successful", so the only symptom is a printer that does not move.
    """

    __slots__ = (
        "_order_data",
    )

    def __init__(
        self,
        order_data: dict[str, Any] | None = {},
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        # None is deliberate for orders with no payload of their own -- see
        # the base class -- and reaches the wire as a null the server expects.
        self._order_data = order_data

    @property
    def order_request_data(self) -> dict[str, Any]:
        return {
            **super().order_request_data,
            # ⚠ A STRING, as the slicer sends it. With an integer the server
            # still answers "Operation successful" and the printer does
            # nothing at all -- MOVE_AXLE was silently ignored until this was
            # matched exactly.
            'order_id': str(self._order_id),
            'data': self._order_data,
        }

    @property
    def order_data(self) -> dict[str, Any] | None:
        return self._order_data

    def __repr__(self) -> str:
        return (
            f"AnycubicPrinterOrderRequest("
            f"order_id={self._order_id}, "
            f"printer_id={self._printer_id}, "
            f"order_data={self._order_data})"
        )


class AnycubicPrinterQueryOrderRequest(AnycubicBaseOrderRequest):
    """A bare printer-level poll: order id and printer id, nothing else.

    The slicer's peripheral and light-status polls carry no ``data`` and no
    ``project_id``, and their order id is a STRING. Sent any other way the
    server still answers "Operation successful" and the printer never
    replies -- which is why nothing ever knew whether a camera was fitted,
    and why the light entity stayed unavailable until some other action
    happened to make the printer volunteer its state.
    """

    @property
    def order_request_data(self) -> dict[str, Any]:
        return {
            **super().order_request_data,
            'order_id': str(self._order_id),
        }

    def __repr__(self) -> str:
        return (
            f"AnycubicPrinterQueryOrderRequest("
            f"order_id={self._order_id}, "
            f"printer_id={self._printer_id})"
        )


class AnycubicBaseProjectOrderRequest(AnycubicBaseOrderRequest):
    __slots__ = (
        "_project_id",
    )

    def __init__(
        self,
        project_id: int,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._project_id = int(project_id)

    @property
    def order_request_data(self) -> dict[str, Any]:
        return {
            **super().order_request_data,
            'project_id': self._project_id,
        }

    @property
    def project_id(self) -> int | None:
        return self._project_id

    def __repr__(self) -> str:
        return (
            f"AnycubicBaseProjectOrderRequest("
            f"order_id={self._order_id}, "
            f"printer_id={self._printer_id}, "
            f"project_id={self._project_id})"
        )


class AnycubicProjectOrderRequest(AnycubicBaseProjectOrderRequest):
    __slots__ = (
        "_order_data",
    )

    def __init__(
        self,
        order_data: dict[str, Any] = {},
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._order_data = order_data

    @property
    def order_request_data(self) -> dict[str, Any]:
        return {
            **super().order_request_data,
            'data': self._order_data,
        }

    @property
    def order_data(self) -> dict[str, Any] | None:
        return self._order_data

    def __repr__(self) -> str:
        return (
            f"AnycubicProjectOrderRequest("
            f"order_id={self._order_id}, "
            f"printer_id={self._printer_id}, "
            f"project_id={self._project_id}, "
            f"order_data={self._order_data})"
        )


class AnycubicProjectCtrlOrderRequest(AnycubicProjectOrderRequest):
    __slots__ = (
        "_ams_info",
        "_print_settings",
    )

    def __init__(
        self,
        ams_box_mapping: list[AnycubicMaterialMapping] | None = None,
        print_settings: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._ams_info: dict[str, Any] | None = None
        self._set_ams_info(ams_box_mapping)
        self._print_settings: dict[str, Any] | None = print_settings

    def _set_ams_info(self, ams_box_mapping: list[AnycubicMaterialMapping] | None) -> None:
        if ams_box_mapping:
            self._ams_info = {
                'ams_box_mapping': [
                    x.as_box_mapping_data()
                    for x in ams_box_mapping
                ],
                'use_ams': (
                    True
                    if len(ams_box_mapping) > 0 else
                    False
                ),
            }
        else:
            self._ams_info = None

    @property
    def order_request_data(self) -> dict[str, Any]:
        return {
            **super().order_request_data,
            'ams_info': self._ams_info,
            'settings': self._print_settings,
        }

    def __repr__(self) -> str:
        return (
            f"AnycubicProjectCtrlOrderRequest("
            f"order_id={self._order_id}, "
            f"printer_id={self._printer_id}, "
            f"project_id={self._project_id}, "
            f"order_data={self._order_data}, "
            f"ams_info={self._ams_info}, "
            f"print_settings={self._print_settings})"
        )


class AnycubicBaseStartPrintRequest:
    __slots__ = (
        "_file_key",
        "_file_name",
        "_filetype",
        "_task_setting_ai_detect",
        "_task_setting_camera_timelapse",
    )

    def __init__(
        self,
        file_key: str = "",
        file_name: str = "",
        filetype: int = 0,
        task_setting_ai_detect: int = 0,
        task_setting_camera_timelapse: int = 0,
    ) -> None:
        self._file_key = file_key
        self._file_name = file_name
        self._filetype = filetype
        self._task_setting_ai_detect = task_setting_ai_detect
        self._task_setting_camera_timelapse = task_setting_camera_timelapse

    @property
    def task_settings(self) -> dict[str, Any]:
        return {
            'ai_detect': self._task_setting_ai_detect,
            'camera_timelapse': self._task_setting_camera_timelapse,
        }

    @property
    def data(self) -> dict[str, Any]:
        return {
            'filetype': self._filetype,
            'file_key': self._file_key,
            'file_name': self._file_name,
            'task_settings': self.task_settings,
        }

    def __repr__(self) -> str:
        return (
            f"AnycubicBaseStartPrintRequest("
            f"filetype={self._filetype}, "
            f"file_name={self._file_name}, "
            f"task_settings={self.task_settings})"
        )


class AnycubicStartPrintRequestLocal(AnycubicBaseStartPrintRequest):
    __slots__ = (
        "_filename",
        "_filepath",
    )

    def __init__(
        self,
        filename: str = "",
        filepath: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._filename = filename
        self._filepath = filepath
        self._filetype = 1

    @property
    def data(self) -> dict[str, Any]:
        return {
            **super().data,
            'filename': self._filename,
            'filepath': f"/{self._filepath}",
        }

    def __repr__(self) -> str:
        return (
            f"AnycubicStartPrintRequestLocal("
            f"filetype={self._filetype}, "
            f"filename={self._filename}, "
            f"filepath={self._filepath}, "
            f"task_settings={self.task_settings})"
        )


class AnycubicStartPrintRequestUdisk(AnycubicStartPrintRequestLocal):
    def __init__(
        self,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._filetype = 2

    def __repr__(self) -> str:
        return (
            f"AnycubicStartPrintRequestUdisk("
            f"filetype={self._filetype}, "
            f"filename={self._filename}, "
            f"filepath={self._filepath}, "
            f"task_settings={self.task_settings})"
        )


class AnycubicStartPrintRequestCloud(AnycubicBaseStartPrintRequest):
    __slots__ = (
        "_file_id",
        "_hollow_param",
        "_is_delete_file",
        "_matrix",
        "_project_type",
        "_punching_param",
        "_slice_param",
        "_slice_size",
        "_template_id",
    )

    def __init__(
        self,
        file_id: int = -1,
        hollow_param: Any = None,
        is_delete_file: int = 0,
        matrix: str = "",
        project_type: int = 1,
        punching_param: Any = None,
        slice_param: dict[str, Any] | None = None,
        slice_size: Any = None,
        template_id: int = 0,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._file_id = file_id
        self._hollow_param = hollow_param
        self._is_delete_file = int(is_delete_file)
        self._matrix = matrix
        self._project_type = project_type
        self._punching_param = punching_param
        self._slice_param = slice_param
        self._slice_size = slice_size
        self._template_id = template_id

    @property
    def data(self) -> dict[str, Any]:
        return {
            **super().data,
            'file_id': self._file_id,
            'hollow_param': self._hollow_param,
            'is_delete_file': self._is_delete_file,
            'matrix': self._matrix,
            'project_type': self._project_type,
            'punching_param': self._punching_param,
            'slice_param': self._slice_param,
            'slice_size': self._slice_size,
            'template_id': self._template_id,
        }

    def __repr__(self) -> str:
        return (
            f"AnycubicStartPrintRequestCloud("
            f"filetype={self._filetype}, "
            f"file_id={self._file_name}, "
            f"task_settings={self.task_settings})"
        )


class AnycubicCameraToken:
    __slots__ = (
        "_secret_id",
        "_secret_key",
        "_session_token",
        "_region",
        "_msg_id",
    )

    def __init__(
        self,
        secret_id: str,
        secret_key: str,
        session_token: str,
        region: str,
        msg_id: str,
    ) -> None:
        self._secret_id: str = secret_id
        self._secret_key: str = secret_key
        self._session_token: str = session_token
        self._region: str = region
        self._msg_id: str = msg_id

    @property
    def secret_id(self) -> str:
        return self._secret_id

    @property
    def secret_key(self) -> str:
        return self._secret_key

    @property
    def session_token(self) -> str:
        return self._session_token

    @property
    def region(self) -> str:
        return self._region

    @property
    def msg_id(self) -> str:
        return self._msg_id

    def __repr__(self) -> str:
        return (
            f"AnycubicCameraToken("
            f"secret_id={self.secret_id}, "
            f"secret_key={self.secret_key}, "
            f"session_token={self.session_token}, "
            f"region={self.region}, "
            f"msg_id={self.msg_id})"
        )


class AnycubicCameraOpenOrderRequest(AnycubicBaseOrderRequest):
    """CAMERA_OPEN, shaped exactly as the slicer sends it.

    Two details are load bearing and neither produces an error when wrong --
    the server answers "Operation successful" either way:

    * ``order_id`` must be a STRING.
    * ``shengwang_rtc_support`` is a TOP LEVEL field, not part of ``data``,
      and without it the server replies "Video service upgraded. Update the
      slicer to enable." instead of returning credentials.

    There is no ``data`` key at all for this order.
    """

    @property
    def order_request_data(self) -> dict[str, Any]:
        return {
            **super().order_request_data,
            'order_id': str(self._order_id),
            'shengwang_rtc_support': True,
        }

    def __repr__(self) -> str:
        return (
            f"AnycubicCameraOpenOrderRequest("
            f"order_id={self._order_id}, "
            f"printer_id={self._printer_id})"
        )


class AnycubicShengwangCredentials:
    """Per-session Agora ("shengwang", 声网) join credentials.

    Short lived -- the slicer re-requests rather than renewing, and caches for
    only 30 seconds. ``client_uid`` is issued fresh on every call, so these
    must never be reused across sessions.
    """

    __slots__ = (
        "_appid",
        "_channel",
        "_rtc_token",
        "_client_uid",
        "_device_uid",
        "_encryption_key",
        "_encryption_kdf_salt",
        "_encryption_mode",
        "_event_id",
        "_msg_id",
    )

    def __init__(
        self,
        appid: str,
        channel: str,
        rtc_token: str,
        client_uid: int,
        device_uid: int | None = None,
        encryption_key: str | None = None,
        encryption_kdf_salt: str | None = None,
        encryption_mode: str | None = None,
        event_id: str | None = None,
        msg_id: str | None = None,
    ) -> None:
        self._appid = appid
        self._channel = channel
        self._rtc_token = rtc_token
        self._client_uid = int(client_uid)
        self._device_uid = int(device_uid) if device_uid is not None else None
        self._encryption_key = encryption_key
        self._encryption_kdf_salt = encryption_kdf_salt
        self._encryption_mode = encryption_mode
        self._event_id = event_id
        self._msg_id = msg_id

    @classmethod
    def from_order_response(
        cls,
        data: dict[str, Any],
    ) -> AnycubicShengwangCredentials | None:
        block = data.get('shengwang')
        if not block:
            return None

        # Present in the slicer's build, absent from the responses this
        # account receives; the subscriber does not need it, it is only used
        # to filter user-left events.
        device = data.get('shengwang_device') or {}

        return cls(
            appid=block['appid'],
            channel=block['channel'],
            rtc_token=block['rtc_token'],
            client_uid=block['client_uid'],
            device_uid=device.get('uid', block.get('uid')),
            encryption_key=block.get('encryption_key'),
            encryption_kdf_salt=block.get('encryption_kdf_salt'),
            encryption_mode=block.get('encryption_mode'),
            event_id=block.get('event_id'),
            msg_id=data.get('msgid'),
        )

    @property
    def appid(self) -> str:
        return self._appid

    @property
    def channel(self) -> str:
        return self._channel

    @property
    def rtc_token(self) -> str:
        return self._rtc_token

    @property
    def client_uid(self) -> int:
        return self._client_uid

    @property
    def device_uid(self) -> int | None:
        return self._device_uid

    @property
    def encryption_key(self) -> str | None:
        return self._encryption_key

    @property
    def encryption_kdf_salt(self) -> str | None:
        return self._encryption_kdf_salt

    @property
    def encryption_mode(self) -> str | None:
        """Agora's enum spelling, eg. ``AES_256_GCM2``."""
        return self._encryption_mode

    @property
    def web_encryption_mode(self) -> str | None:
        """The spelling the wire protocol wants, eg. ``aes-256-gcm2``."""
        if not self._encryption_mode:
            return None
        return self._encryption_mode.lower().replace('_', '-')

    @property
    def is_encrypted(self) -> bool:
        return bool(
            self._encryption_mode
            and self._encryption_mode.lower() != 'none'
            and self._encryption_key
        )

    @property
    def event_id(self) -> str | None:
        return self._event_id

    @property
    def msg_id(self) -> str | None:
        return self._msg_id

    def __repr__(self) -> str:
        # Never render the token, key or salt.
        return (
            f"AnycubicShengwangCredentials("
            f"appid={self._appid}, "
            f"channel={self._channel}, "
            f"client_uid={self._client_uid}, "
            f"device_uid={self._device_uid}, "
            f"encryption_mode={self._encryption_mode})"
        )
