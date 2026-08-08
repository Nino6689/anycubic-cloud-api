"""Cloud orders expressed as their local (LAN Mode) equivalents.

A printer talks to exactly one of the two transports -- switching LAN Mode on
drops its cloud connection -- so a printer that answers locally is a printer
whose cloud orders would go nowhere. Anything sent while the local connection
is up therefore has to go out locally, or not at all.

The mapping below is not inferred. Anycubic Slicer Next carries both halves of
it side by side: an ``http_fuction`` module that posts cloud orders and an
``mqtt_fuction`` module that publishes the local equivalents, function for
function. The payloads turned out to be the same on both transports, so only
the routing differs -- a command is a topic, a verb, and the order's own data
passed through untouched.

Two orders in the cloud module have no local twin, and the slicer says why in
its own comment: AI detection settings are marked "only wide-area network".
They are left out here rather than guessed at, so they keep falling through to
the cloud rather than being published into a void.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..const.enums import AnycubicOrderID


@dataclass(frozen=True)
class AnycubicLANCommand:
    """Where a cloud order goes when it is sent locally instead.

    ``message_type`` is both the topic's last segment and the message's own
    ``type`` field; the printer uses the latter to identify a report, so the
    two always match.
    """

    message_type: str
    action: str
    # Locally there is no project id field, so the three print controls and the
    # in-progress settings change carry the task id inside ``data`` instead.
    needs_taskid: bool = False


# Keyed by cloud order. An order that is absent is one with no verified local
# form, and is left to the cloud rather than being approximated.
LAN_ORDER_COMMANDS: dict[int, AnycubicLANCommand] = {
    AnycubicOrderID.PAUSE_PRINT: AnycubicLANCommand("print", "pause", True),
    AnycubicOrderID.RESUME_PRINT: AnycubicLANCommand("print", "resume", True),
    AnycubicOrderID.STOP_PRINT: AnycubicLANCommand("print", "stop", True),
    AnycubicOrderID.PRINT_SETTINGS: AnycubicLANCommand("print", "update", True),
    AnycubicOrderID.MOVE_AXLE: AnycubicLANCommand("axis", "move"),
    AnycubicOrderID.MULTI_COLOR_BOX_GET_INFO: AnycubicLANCommand(
        "multiColorBox", "getInfo"
    ),
    AnycubicOrderID.MULTI_COLOR_BOX_DRY: AnycubicLANCommand(
        "multiColorBox", "setDry"
    ),
    AnycubicOrderID.FEED_FILAMENT: AnycubicLANCommand(
        "multiColorBox", "feedFilament"
    ),
    AnycubicOrderID.MULTI_COLOR_BOX_SET_SLOT: AnycubicLANCommand(
        "multiColorBox", "setInfo"
    ),
    AnycubicOrderID.MULTI_COLOR_BOX_AUTO_FEED: AnycubicLANCommand(
        "multiColorBox", "setAutoFeed"
    ),
    AnycubicOrderID.MOVE_AXLE_TURN_OFF: AnycubicLANCommand("axis", "turnOff"),
    AnycubicOrderID.QUERY_AXIS_POSITION: AnycubicLANCommand("axis", "query"),
    AnycubicOrderID.SET_TEMPERATURE: AnycubicLANCommand("tempature", "set"),
    AnycubicOrderID.SET_FAN_SPEED: AnycubicLANCommand("fan", "setSpeed"),
    AnycubicOrderID.QUERY_PERIPHERALS: AnycubicLANCommand("peripherie", "query"),
    AnycubicOrderID.GET_LIGHT_STATUS: AnycubicLANCommand("light", "query"),
    AnycubicOrderID.SET_LIGHT_STATUS: AnycubicLANCommand("light", "control"),
}


def lan_command_for_order(order_id: int) -> AnycubicLANCommand | None:
    """The local form of a cloud order, if it has a verified one."""
    return LAN_ORDER_COMMANDS.get(order_id)
