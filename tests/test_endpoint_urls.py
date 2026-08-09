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
