from __future__ import annotations

from collections import UserDict
from typing import Any


class AnycubicConsumableData(UserDict[Any, Any]):
    __slots__ = (
        "data",
        "_consumed_data",
    )

    def __init__(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.data: dict[Any, Any] = self._encode_items()
        self._consumed_data: dict[Any, Any] = dict()

    @property
    def is_empty(self) -> bool:
        return len(self.data) == 0

    @property
    def remaining_data(self) -> dict[Any, Any]:
        return self.data

    def force_empty(self) -> None:
        for key in list(self.data.keys()):
            self._consumed_data[key] = self.data.pop(key)

    def _encode_list(
        self,
        data: list[Any],
    ) -> list[None | str | int | float | bool | AnycubicConsumableData | list[Any]]:
        new_data: list[Any] = list()
        for v in data:
            if isinstance(v, AnycubicConsumableData):
                new_data.append(v)
            elif isinstance(v, dict):
                new_data.append(AnycubicConsumableData(v))
            elif isinstance(v, list):
                new_data.append(self._encode_list(v))
            elif (
                isinstance(v, str) or
                isinstance(v, int) or
                isinstance(v, float) or
                isinstance(v, bool) or
                v is None
            ):
                new_data.append(v)
            else:
                raise TypeError(
                    f"Invalid type for AnycubicConsumableData: {type(v)}"
                )

        return new_data

    def _encode_items(
        self,
    ) -> dict[Any, None | str | int | float | bool | AnycubicConsumableData | list[Any]]:
        new_data: dict[Any, Any] = dict()
        for k, v in self.data.items():
            if isinstance(v, AnycubicConsumableData):
                new_data[k] = v
            elif isinstance(v, dict):
                new_data[k] = AnycubicConsumableData(v)
            elif isinstance(v, list):
                new_data[k] = self._encode_list(v)
            elif (
                isinstance(v, str) or
                isinstance(v, int) or
                isinstance(v, float) or
                isinstance(v, bool) or
                v is None
            ):
                new_data[k] = v
            else:
                raise TypeError(
                    f"Invalid type for AnycubicConsumableData: {type(v)}"
                )

        return new_data

    def __getitem__(
        self,
        key: Any,
    ) -> Any:
        try:
            return self._consumed_data[key]
        except KeyError:
            pass

        try:
            value = self.data[key]
            if (
                not isinstance(value, AnycubicConsumableData) or
                value.is_empty
            ):
                self._consumed_data[key] = self.data.pop(key)
        except KeyError:
            raise

        return value

    def get(
        self,
        key: Any,
        default: Any = None,
    ) -> Any:
        try:
            return self[key]
        except KeyError:
            return default


def plain_data(value: Any) -> Any:
    """Unwrap AnycubicConsumableData into plain dicts and lists, all the way down.

    MQTT payloads arrive wrapped, and every nested dict becomes another
    AnycubicConsumableData -- a ``UserDict``, which ``isinstance(x, dict)``
    rejects. Anything stored for later (slice parameters, settings) should be
    unwrapped first. Reading through the wrapper also marks every key as
    handled, so the copy doesn't leave the payload looking unread.
    """
    if isinstance(value, AnycubicConsumableData):
        unwrapped: dict[Any, Any] = {}
        for key in list(value.data.keys()):
            unwrapped[key] = plain_data(value.get(key))
            # A nested block only counts as read once it is empty and is read
            # again -- the same rule _drain() in printer.py follows.
            value.get(key)
        return unwrapped
    if isinstance(value, dict):
        return {key: plain_data(item) for key, item in value.items()}
    if isinstance(value, list):
        return [plain_data(item) for item in value]
    return value
