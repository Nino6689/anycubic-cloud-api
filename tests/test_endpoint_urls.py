"""The exact URLs this library talks to today.

Characterization tests: they assert the resolved strings, not the shape, and
they were written BEFORE endpoints became region-aware so that the refactor
had something to be measured against. If one of these changes, an existing
international user's integration has moved to a different address.

They pin the string joins deliberately. `BASE_DOMAIN` is joined with a
trailing slash and `PUBLIC_API_ENDPOINT` carries no leading one, while every
entry in `const/api_endpoints.py` starts with `/` -- so the correct full URL
has exactly one slash at each seam, and it is entirely possible to refactor
this into something that looks right and yields `//` or none at all.

That failure would be close to invisible in the field: `api/base.py` catches
every exception from a request and re-raises it as
`api_error_server_maintenance`, so a wrong URL is reported by users as
"Anycubic's servers are down".
"""

from unittest.mock import MagicMock

from anycubic_cloud_api.anycubic_api import AnycubicAPI
from anycubic_cloud_api.const.api_endpoints import API_ENDPOINT
from anycubic_cloud_api.const.const import (
    AUTH_DOMAIN,
    BASE_DOMAIN,
    PROJECT_IMAGE_URL_BASE,
    PUBLIC_API_ENDPOINT,
)
from anycubic_cloud_api.const.mqtt import MQTT_HOST, MQTT_PORT
from anycubic_cloud_api.models.auth import AnycubicAuthMode


def build_api(**kwargs) -> AnycubicAPI:
    return AnycubicAPI(
        session=MagicMock(),
        cookie_jar=MagicMock(),
        **kwargs,
    )


class TestInternationalEndpoints:
    """What an existing user resolves to. None of this may drift."""

    def test_base_url_keeps_its_trailing_slash(self):
        api = build_api()

        assert api._base_url == "https://cloud-universe.anycubic.com/"
        assert api._base_url.endswith("/")

    def test_public_api_root_joins_with_exactly_one_slash(self):
        api = build_api()

        assert (
            api._public_api_root
            == "https://cloud-universe.anycubic.com/p/p/workbench/api"
        )
        assert "//" not in api._public_api_root.removeprefix("https://")

    def test_a_built_endpoint_url_is_unchanged(self):
        """End to end through the seam that actually carries traffic."""
        api = build_api()

        url = api._build_api_url(API_ENDPOINT.user_info)

        assert url.startswith("https://cloud-universe.anycubic.com/p/p/workbench/api/")
        assert "//" not in url.removeprefix("https://")

    def test_constants_are_the_ones_we_think(self):
        """Guards the table a region record is derived from."""
        assert BASE_DOMAIN == "cloud-universe.anycubic.com"
        assert AUTH_DOMAIN == "uc.makeronline.com"
        assert PUBLIC_API_ENDPOINT == "p/p/workbench/api"
        assert not PUBLIC_API_ENDPOINT.startswith("/")
        assert PROJECT_IMAGE_URL_BASE.endswith("/")

    def test_mqtt_host_and_port(self):
        assert MQTT_HOST == "mqtt-universe.anycubic.com"
        assert MQTT_PORT == 8883


class TestOriginHeader:
    """The Origin sent on web-authenticated calls.

    Worth pinning separately: it is supplied as a DEFAULT ARGUMENT in five
    places, which is the single most refactor-hostile shape in this file --
    a default is bound at import, so it cannot follow per-instance state
    without the signature changing.
    """

    @staticmethod
    def web_api() -> AnycubicAPI:
        """A web-authenticated API -- the mode that sends an Origin at all."""
        api = build_api()
        api.set_authentication("token-for-tests", auth_mode=AnycubicAuthMode.WEB)
        return api

    def test_web_mode_sends_an_origin(self):
        """Guard the guard: if this stops holding, the tests below go vacuous."""
        assert self.web_api().anycubic_auth.requires_user_agent

    def test_origin_is_the_auth_domain(self):
        headers = self.web_api()._web_headers()

        assert headers["Origin"] == "https://uc.makeronline.com"

    def test_an_explicit_origin_still_wins(self):
        headers = self.web_api()._web_headers(with_origin="example.test")

        assert headers["Origin"] == "https://example.test"

    def test_origin_can_still_be_suppressed(self):
        """None means "send no Origin", and must stay distinct from unset.

        This is the distinction a naive `if not with_origin` refactor
        destroys, and the one a sentinel default has to preserve.
        """
        headers = self.web_api()._web_headers(with_origin=None)

        assert "Origin" not in headers


class TestMqttHostnameVerification:
    """China's broker presents a certificate that does not name its host.

    Field-verified in hass-anycubic#13: with full verification the handshake
    fails "certificate is not valid for 'mqtt.anycubicloud.com'", while the
    Slicer connects to the same broker using the same private CA. Trust there
    is the pinned CA plus the client certificate; only the hostname comparison
    is waived, and only for the region whose certificate is known not to match.
    """

    def test_international_still_verifies_the_hostname(self):
        from anycubic_cloud_api.const.regions import REGIONS, AnycubicRegion

        assert REGIONS[AnycubicRegion.INTERNATIONAL].mqtt_verify_hostname is True

    def test_china_waives_only_the_hostname(self):
        from anycubic_cloud_api.const.regions import REGIONS, AnycubicRegion

        assert REGIONS[AnycubicRegion.CHINA].mqtt_verify_hostname is False


class TestFailedConnectIsNotStarted:
    """mqtt_is_started must not answer True after connect() raised.

    It reads `_mqtt_client is not None`, and the client was created before the
    connect call -- so a TLS failure left a dead object behind and the
    connection sensor reported ON beside a last_error carrying the failure.
    """

    def test_a_raising_connect_leaves_the_client_cleared(self, monkeypatch):
        from unittest.mock import MagicMock

        import anycubic_cloud_api.api.mqtt as mqtt_mod

        fake = MagicMock()
        fake.connect.side_effect = OSError("tls says no")
        monkeypatch.setattr(
            mqtt_mod.mqtt_client, "Client", MagicMock(return_value=fake)
        )

        real = mqtt_mod.AnycubicMQTTAPI.__new__(mqtt_mod.AnycubicMQTTAPI)
        real._mqtt_client = None
        real._mqtt_connected = None
        real._mqtt_disconnected = None
        real._mqtt_log_all_messages = False
        auth = MagicMock()
        # anycubic_auth is a read-only property; back the underlying slot.
        real._anycubic_auth = auth
        auth.get_mqtt_client_id.return_value = "cid"
        auth.get_mqtt_login_info.return_value = ("u", "p")
        real._endpoints = MagicMock()
        real._endpoints.mqtt_host = "h"
        real._endpoints.mqtt_port = 8883
        real._endpoints.mqtt_verify_hostname = True
        real._mqtt_build_ssl_context = MagicMock()
        real._log_to_debug = MagicMock()

        import pytest as _pytest
        with _pytest.raises(OSError):
            real.connect_mqtt()

        assert real._mqtt_client is None
        assert real.mqtt_is_started is False

    def test_the_ssl_context_honours_the_flag(self):
        """The table is only policy; the context is what talks to the broker."""
        from unittest.mock import MagicMock

        import anycubic_cloud_api.api.mqtt as mqtt_mod

        api = mqtt_mod.AnycubicMQTTAPI.__new__(mqtt_mod.AnycubicMQTTAPI)
        api._log_to_error = MagicMock()
        for flag in (True, False):
            api._endpoints = MagicMock()
            api._endpoints.mqtt_verify_hostname = flag
            ctx = api._mqtt_build_ssl_context()
            assert ctx.check_hostname is flag
            import ssl as _ssl
            assert ctx.verify_mode is _ssl.CERT_REQUIRED


class TestBundledClientCertLoads:
    """The client certificate Anycubic issued is SHA-1 signed, and OpenSSL 3.x
    refuses to load it at any security level above 0 -- CA_MD_TOO_WEAK, before
    a single byte reaches the network. We cannot re-sign it (the issuer is
    Anycubic's private root; we hold no CA key), so the context lowers the
    level. This pins that the context we actually build loads the certificate
    we actually ship, on whatever OpenSSL the test runs against.
    """

    def test_the_built_context_loads_the_shipped_certificate(self):
        import ssl
        from unittest.mock import MagicMock

        import anycubic_cloud_api.api.mqtt as mqtt_mod

        api = mqtt_mod.AnycubicMQTTAPI.__new__(mqtt_mod.AnycubicMQTTAPI)
        api._log_to_error = MagicMock()
        api._endpoints = MagicMock()
        api._endpoints.mqtt_verify_hostname = True
        # Would raise ssl.SSLError(CA_MD_TOO_WEAK) if the seclevel guard went.
        ctx = api._mqtt_build_ssl_context()
        assert isinstance(ctx, ssl.SSLContext)
        assert ctx.verify_mode is ssl.CERT_REQUIRED
