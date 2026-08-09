"""Region resolution.

The point of these is not that China works -- nobody here can test that. It
is that *international is untouched*, and that no stored value, however
malformed, can take an existing entry offline.
"""

from unittest.mock import MagicMock

import pytest

from anycubic_cloud_api.anycubic_api import AnycubicAPI
from anycubic_cloud_api.const.const import (
    AUTH_DOMAIN,
    BASE_DOMAIN,
    PROJECT_IMAGE_URL_BASE,
    PUBLIC_API_ENDPOINT,
)
from anycubic_cloud_api.const.mqtt import MQTT_HOST, MQTT_PORT
from anycubic_cloud_api.const.regions import (
    DEFAULT_REGION,
    REGIONS,
    AnycubicRegion,
    resolve_region,
)
from anycubic_cloud_api.models.auth import AnycubicAuthMode


def build_api(**kwargs) -> AnycubicAPI:
    return AnycubicAPI(session=MagicMock(), cookie_jar=MagicMock(), **kwargs)


class TestTheDefaultRegionIsTodaysBehaviour:
    """If any of this drifts, existing installs have silently moved cloud."""

    def test_international_matches_the_legacy_constants(self):
        e = REGIONS[AnycubicRegion.INTERNATIONAL]

        assert e.base_domain == BASE_DOMAIN
        assert e.auth_domain == AUTH_DOMAIN
        assert e.mqtt_host == MQTT_HOST
        assert e.mqtt_port == MQTT_PORT
        assert e.public_api_endpoint == PUBLIC_API_ENDPOINT
        assert e.project_image_url_base == PROJECT_IMAGE_URL_BASE

    def test_the_default_is_international(self):
        assert DEFAULT_REGION is AnycubicRegion.INTERNATIONAL

    def test_an_api_built_with_no_region_resolves_international(self):
        api = build_api()

        assert api.endpoints is REGIONS[AnycubicRegion.INTERNATIONAL]
        assert api._base_url == "https://cloud-universe.anycubic.com/"


class TestResolveRegionNeverRaises:
    """Called during setup, so raising here takes an entry permanently down."""

    @pytest.mark.parametrize(
        "value",
        [
            None,            # every entry that predates the field
            "",              # a cleared option
            "garbage",       # a typo, or a region we dropped
            "CHINA",         # right value, wrong case
            "  china  ",     # whitespace from a text field
            123,             # wrong type entirely
            object(),        # very wrong type
            [],
        ],
    )
    def test_anything_unrecognised_resolves_rather_than_raising(self, value):
        result = resolve_region(value)

        assert isinstance(result, AnycubicRegion)

    def test_unknown_strings_fall_back_to_international(self):
        assert resolve_region("garbage") is AnycubicRegion.INTERNATIONAL
        assert resolve_region(None) is AnycubicRegion.INTERNATIONAL
        assert resolve_region("") is AnycubicRegion.INTERNATIONAL

    def test_case_and_whitespace_are_tolerated(self):
        """Stored values pass through a UI and a JSON file before arriving."""
        assert resolve_region("CHINA") is AnycubicRegion.CHINA
        assert resolve_region("  china  ") is AnycubicRegion.CHINA

    def test_an_enum_passes_straight_through(self):
        assert resolve_region(AnycubicRegion.CHINA) is AnycubicRegion.CHINA


class TestChinaResolvesToChinaAddresses:
    """Unverified values, but the plumbing that carries them is testable."""

    def test_urls_are_built_from_the_china_domains(self):
        api = build_api(region="china")

        assert api._base_url == "https://cloud-platform.anycubicloud.com/"
        assert (
            api._public_api_root
            == "https://cloud-platform.anycubicloud.com/p/p/workbench/api"
        )
        assert "//" not in api._public_api_root.removeprefix("https://")

    def test_the_origin_header_follows_the_region(self):
        api = build_api(region="china")
        api.set_authentication("token-for-tests", auth_mode=AnycubicAuthMode.WEB)

        assert api._web_headers()["Origin"] == "https://uc.makeronline.cn"

    def test_mqtt_host_follows_the_region(self):
        assert build_api(region="china").endpoints.mqtt_host == "mqtt.anycubicloud.com"

    def test_region_is_not_settable_after_construction(self):
        """Changing it live would leave one client talking to two clouds."""
        api = build_api()

        assert not hasattr(api, "set_region")
