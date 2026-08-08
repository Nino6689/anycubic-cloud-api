"""Talking to a printer's own MQTT broker in LAN Mode.

The printer runs the same message protocol locally that Anycubic run in the
cloud -- the same topic prefix, the same report shapes -- so everything that
already parses cloud reports parses these too. Only three things differ:

* the broker is the printer itself, reached with credentials from the
  handshake rather than a cloud login;
* commands go out on ``.../web/printer/...`` instead of
  ``.../printer/public/...``, because locally there is no cloud in the middle
  to route them;
* reports must be asked for. The cloud pushes unprompted; the printer answers
  a query, so state is polled rather than streamed.

Report topics have the same shape as the cloud's, with the model id and
device id sitting where the machine type and printer key do, so the report
topic can be handed straight to the existing printer parser.

The broker presents a self-signed certificate naming an address that differs
per unit, so there is nothing to verify it against. The connection is still
encrypted, and it never leaves the local network -- which is the same trade
Home Assistant makes for every other local device that ships its own
certificate. The cloud connection, which does cross the internet, remains
fully verified.
"""

from __future__ import annotations

import asyncio
import json
import ssl
import time
import uuid
from collections.abc import Callable
from typing import Any

from paho.mqtt import client as mqtt_client

try:
    from paho.mqtt.enums import CallbackAPIVersion as _CallbackAPIVersion
    _MQTT_CALLBACK_API_VERSION = _CallbackAPIVersion.VERSION1
except ImportError:  # paho-mqtt 1.x
    _MQTT_CALLBACK_API_VERSION = None

from ..const.mqtt import MQTT_TOPIC_PREFIX
from ..exceptions.error_strings import ErrorsLAN
from ..exceptions.exceptions import AnycubicLANError
from .handshake import AnycubicLANBroker

# What the printer will answer, and the action each one wants. Confirmed
# against a Kobra S1 on firmware 2.7.2.7:
#
# * "tempature" is the firmware's own spelling on the wire -- correcting it
#   gets no reply;
# * multiColorBox answers to "getInfo" and stays silent for "query", which is
#   the difference between having ACE data and having none;
# * "print" answers only while a job exists, so it is asked for anyway and
#   simply produces nothing when idle.
LAN_QUERY_ACTIONS = {
    "info": "query",
    "tempature": "query",
    "fan": "query",
    "light": "query",
    "multiColorBox": "getInfo",
    "print": "query",
    "aiSettings": "query",
    # Which peripherals are fitted, and so whether there is a camera to offer.
    # Over the cloud a separate poll asks for this, but that poll only runs
    # while the cloud MQTT link is up -- which it never is for a printer in
    # LAN Mode. Asked here instead, so a local printer is not permanently
    # assumed to have no camera.
    "peripherie": "query",
    # Head position and the external filament holder. Printers without one
    # simply stay silent rather than erroring, so asking costs nothing.
    "axis": "query",
    "extfilbox": "query",
}

LAN_QUERY_TYPES = tuple(LAN_QUERY_ACTIONS)

LAN_CONNECT_TIMEOUT = 15
LAN_KEEPALIVE = 60


class AnycubicLANClient:
    """An MQTT connection to one printer on the local network."""

    __slots__ = (
        "_broker",
        "_client",
        "_connected",
        "_disconnected",
        "_on_message",
        "_debug_logger",
        "_loop",
    )

    def __init__(
        self,
        broker: AnycubicLANBroker,
        on_message: Callable[[str, str, dict[str, Any]], None],
        debug_logger: Any = None,
    ) -> None:
        self._broker = broker
        self._on_message = on_message
        self._debug_logger = debug_logger
        self._client: mqtt_client.Client | None = None
        self._connected: asyncio.Event | None = None
        self._disconnected: asyncio.Event | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._client.is_connected()

    @property
    def broker(self) -> AnycubicLANBroker:
        return self._broker

    def _log_to_debug(self, msg: str) -> None:
        if self._debug_logger is not None:
            self._debug_logger.debug(msg)

    @property
    def report_topic(self) -> str:
        """Where the printer publishes its own state."""
        return (
            f"{MQTT_TOPIC_PREFIX}/printer/public/"
            f"{self._broker.model_id}/{self._broker.device_id}"
        )

    def query_topic(self, message_type: str) -> str:
        """Where a request for state, or a command, is published."""
        return (
            f"{MQTT_TOPIC_PREFIX}/web/printer/"
            f"{self._broker.model_id}/{self._broker.device_id}/{message_type}"
        )

    def _build_ssl_context(self) -> ssl.SSLContext:
        # The printer signs its own certificate for an address that varies per
        # unit, so there is no chain to verify and no stable name to check.
        # See the module docstring for why that is acceptable here.
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

        return context

    def _on_connect(
        self,
        client: mqtt_client.Client,
        userdata: Any,
        flags: dict[str, Any],
        rc: int,
    ) -> None:
        if rc != 0:
            self._log_to_debug(f"Anycubic LAN MQTT refused the connection: rc={rc}")
            return

        client.subscribe(f"{self.report_topic}/#")
        self._log_to_debug("Anycubic LAN MQTT connected and subscribed")

    def _on_subscribe(
        self,
        client: mqtt_client.Client,
        userdata: Any,
        mid: int,
        granted_qos: tuple[int],
    ) -> None:
        # Only once the subscription is live is the connection actually usable
        # -- publishing before this point succeeds but the replies are lost.
        if self._connected is not None and self._loop is not None:
            self._loop.call_soon_threadsafe(self._connected.set)

    def _on_disconnect(
        self,
        client: mqtt_client.Client,
        userdata: Any,
        rc: int,
    ) -> None:
        if self._disconnected is not None and self._loop is not None:
            self._loop.call_soon_threadsafe(self._disconnected.set)

    def _on_mqtt_message(
        self,
        client: mqtt_client.Client,
        userdata: Any,
        message: mqtt_client.MQTTMessage,
    ) -> None:
        try:
            payload = json.loads(message.payload.decode())
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._log_to_debug("Anycubic LAN MQTT sent a message that was not JSON")
            return

        if not isinstance(payload, dict):
            return

        # The report's `action` varies (query/report/refresh/workReport), so
        # the type is what identifies it. The topic's last segment is the
        # fallback for reports that omit it.
        message_type = payload.get("type") or message.topic.rsplit("/", 1)[-1]

        try:
            self._on_message(str(message.topic), str(message_type), payload)
        except Exception as err:
            # A parsing failure downstream must not take the connection with
            # it -- paho would swallow the traceback and stop delivering.
            self._log_to_debug(f"Anycubic LAN MQTT message handler failed: {err}")

    async def async_connect(self) -> None:
        """Connect to the printer's broker and wait until reports will arrive."""
        if self.is_connected:
            return

        self._loop = asyncio.get_running_loop()
        self._connected = asyncio.Event()
        self._disconnected = asyncio.Event()

        client_id = f"ha-{uuid.uuid4().hex[:12]}"

        client = (
            mqtt_client.Client(_MQTT_CALLBACK_API_VERSION, client_id)
            if _MQTT_CALLBACK_API_VERSION is not None
            else mqtt_client.Client(client_id)
        )
        client.username_pw_set(self._broker.username, self._broker.password)
        client.tls_set_context(self._build_ssl_context())
        client.on_connect = self._on_connect
        client.on_subscribe = self._on_subscribe
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_mqtt_message

        self._client = client

        try:
            await self._loop.run_in_executor(
                None,
                lambda: client.connect(
                    self._broker.host, self._broker.port, LAN_KEEPALIVE
                ),
            )
        except OSError as err:
            self._client = None
            raise AnycubicLANError(
                ErrorsLAN.unreachable.format(self._broker.host)
            ) from err

        client.loop_start()

        try:
            async with asyncio.timeout(LAN_CONNECT_TIMEOUT):
                await self._connected.wait()
        except (asyncio.TimeoutError, asyncio.CancelledError) as err:
            await self.async_disconnect()
            raise AnycubicLANError(
                ErrorsLAN.unreachable.format(self._broker.host)
            ) from err

    async def async_disconnect(self) -> None:
        """Drop the connection, tolerating one that never came up."""
        client = self._client

        if client is None:
            return

        self._client = None

        client.disconnect()
        client.loop_stop()

    def publish(self, message_type: str, payload: dict[str, Any]) -> None:
        """Send a query or command to the printer."""
        if self._client is None:
            raise AnycubicLANError(ErrorsLAN.not_connected)

        self._client.publish(self.query_topic(message_type), json.dumps(payload))

    def publish_command(
        self,
        message_type: str,
        action: str,
        data: dict[str, Any] | None = None,
    ) -> str:
        """Tell the printer to do something, and say which message said so.

        The envelope is the slicer's, field for field: a millisecond timestamp
        and a message id alongside the payload. Queries have always worked
        without either, but a command is not a query, and the shape that is
        known to drive hardware is the one worth sending.

        The id is returned because the cloud returns one too -- the printer
        echoes it in the report that follows, which is what tells a caller its
        command was the one that took effect.
        """
        msgid = str(uuid.uuid4())

        self.publish(
            message_type,
            {
                "type": message_type,
                "action": action,
                "timestamp": int(time.time() * 1000),
                "msgid": msgid,
                "data": data,
            },
        )

        return msgid

    def query(self, message_type: str) -> None:
        """Ask the printer to report one kind of state."""
        action = LAN_QUERY_ACTIONS.get(message_type, "query")

        self.publish(message_type, {"type": message_type, "action": action, "data": {}})

    def query_all(self) -> None:
        """Ask for everything the printer will report."""
        for message_type in LAN_QUERY_TYPES:
            self.query(message_type)
