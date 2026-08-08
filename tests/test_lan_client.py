"""Tests for the local MQTT client.

These cover message routing and topic construction without a broker -- the
connection itself is proved against real hardware, not here.
"""

import json
from unittest.mock import MagicMock

import pytest

from anycubic_cloud_api.exceptions.exceptions import AnycubicLANError
from anycubic_cloud_api.lan.client import (
    LAN_QUERY_ACTIONS,
    LAN_QUERY_TYPES,
    AnycubicLANClient,
)
from anycubic_cloud_api.lan.handshake import AnycubicLANBroker

BROKER = AnycubicLANBroker(
    host="10.0.66.28",
    port=9883,
    username="user",
    password="pass",
    device_id="DEVICE1234",
    model_id="20025",
)


def make_client():
    received = []
    client = AnycubicLANClient(
        BROKER, lambda topic, kind, payload: received.append((kind, payload))
    )

    return client, received


def make_message(topic, payload):
    message = MagicMock()
    message.topic = topic
    message.payload = payload if isinstance(payload, bytes) else json.dumps(payload).encode()

    return message


class TestTopics:
    def test_reports_come_from_the_printer_public_topic(self):
        client, _ = make_client()

        assert client.report_topic == (
            "anycubic/anycubicCloud/v1/printer/public/20025/DEVICE1234"
        )

    def test_queries_go_to_the_web_topic(self):
        """Locally there is no cloud in the middle, so the direction differs."""
        client, _ = make_client()

        assert client.query_topic("info") == (
            "anycubic/anycubicCloud/v1/web/printer/20025/DEVICE1234/info"
        )


class TestMessageRouting:
    def test_the_topic_is_passed_through_for_the_existing_parser(self):
        """Local report topics have the same shape as the cloud's."""
        seen = []
        client = AnycubicLANClient(BROKER, lambda topic, kind, payload: seen.append(topic))

        client._on_mqtt_message(
            None, None, make_message(f"{client.report_topic}/info", {"type": "info"})
        )

        assert seen[0].split("/")[5:7] == ["20025", "DEVICE1234"]

    def test_the_payload_type_identifies_the_report(self):
        client, received = make_client()

        client._on_mqtt_message(
            None, None, make_message(f"{client.report_topic}/anything", {"type": "info", "data": {}})
        )

        assert received == [("info", {"type": "info", "data": {}})]

    def test_the_topic_is_the_fallback_when_type_is_absent(self):
        client, received = make_client()

        client._on_mqtt_message(
            None, None, make_message(f"{client.report_topic}/tempature", {"data": {}})
        )

        assert received[0][0] == "tempature"

    @pytest.mark.parametrize(
        "payload", [b"not json", b"", json.dumps([1, 2]).encode(), b"\xff\xfe"]
    )
    def test_junk_is_dropped_not_raised(self, payload):
        client, received = make_client()

        client._on_mqtt_message(None, None, make_message("x/y", payload))

        assert received == []

    def test_a_failing_handler_does_not_escape(self):
        """paho would silently stop delivering if this propagated."""
        def explode(topic, kind, payload):
            raise ValueError("boom")

        client = AnycubicLANClient(BROKER, explode)

        client._on_mqtt_message(None, None, make_message("x/info", {"type": "info"}))


class TestPublishing:
    def test_publishing_without_a_connection_raises(self):
        client, _ = make_client()

        with pytest.raises(AnycubicLANError):
            client.query("info")

    def test_a_query_is_published_on_the_right_topic(self):
        client, _ = make_client()
        client._client = MagicMock()

        client.query("multiColorBox")

        topic, body = client._client.publish.call_args.args

        assert topic.endswith("/web/printer/20025/DEVICE1234/multiColorBox")
        assert json.loads(body) == {
            "type": "multiColorBox",
            "action": "getInfo",
            "data": {},
        }

    def test_the_ace_needs_getinfo_not_query(self):
        """Confirmed on a Kobra S1: "query" gets no reply at all."""
        assert LAN_QUERY_ACTIONS["multiColorBox"] == "getInfo"
        assert LAN_QUERY_ACTIONS["info"] == "query"

    def test_an_unknown_type_falls_back_to_query(self):
        client, _ = make_client()
        client._client = MagicMock()

        client.query("somethingNew")

        assert json.loads(client._client.publish.call_args.args[1])["action"] == "query"

    def test_query_all_asks_for_every_type(self):
        client, _ = make_client()
        client._client = MagicMock()

        client.query_all()

        asked = [
            json.loads(call.args[1])["type"]
            for call in client._client.publish.call_args_list
        ]

        assert asked == list(LAN_QUERY_TYPES)

    def test_head_position_is_asked_for(self):
        """Confirmed answering on a Kobra S1; without it the entities are dead."""
        assert LAN_QUERY_ACTIONS["axis"] == "query"

    def test_asking_for_something_the_printer_lacks_is_harmless(self):
        """A printer with no external holder stays silent rather than erroring."""
        assert "extfilbox" in LAN_QUERY_ACTIONS

    def test_peripherals_are_asked_for(self):
        """The cloud's peripherals poll only runs while the cloud MQTT link is
        up, which it never is in LAN Mode -- so without this a local printer is
        permanently assumed to have no camera."""
        assert LAN_QUERY_ACTIONS["peripherie"] == "query"

    def test_the_firmware_misspelling_is_preserved(self):
        """The printer answers "tempature"; correcting it gets no reply."""
        assert "tempature" in LAN_QUERY_TYPES
        assert "temperature" not in LAN_QUERY_TYPES


class TestConnectionState:
    def test_a_fresh_client_is_not_connected(self):
        client, _ = make_client()

        assert client.is_connected is False

    @pytest.mark.asyncio
    async def test_disconnecting_when_never_connected_is_harmless(self):
        client, _ = make_client()

        await client.async_disconnect()

    def test_the_local_context_does_not_verify_the_device_certificate(self):
        """Self-signed, per-unit name -- there is nothing to verify against."""
        import ssl

        client, _ = make_client()
        context = client._build_ssl_context()

        assert context.check_hostname is False
        assert context.verify_mode == ssl.CERT_NONE
