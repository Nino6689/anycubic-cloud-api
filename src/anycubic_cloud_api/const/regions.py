"""Which Anycubic cloud an account lives on.

Anycubic runs two entirely separate deployments. They do not share accounts,
printers or infrastructure -- an account created in the China app does not
exist internationally and vice versa, so this is not a preference or a
language setting, it is which service the credentials belong to.

Region is chosen once, explicitly, by the user. Nothing here probes or
guesses: the only claim that could discriminate is the token's issuer, and
the China token in issue #13 carried the *international* issuer, so the one
field worth keying on is already observed non-discriminating for exactly the
users this exists for.

The international values are re-exported from `const.const` rather than
retyped, so the default region cannot drift from the constants the rest of
the library has always used. `test_regions.py` asserts that equality.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping

from .const import (
    AUTH_DOMAIN,
    BASE_DOMAIN,
    PROJECT_IMAGE_URL_BASE,
    PUBLIC_API_ENDPOINT,
)
from .mqtt import MQTT_HOST, MQTT_PORT


class AnycubicRegion(StrEnum):
    """A str enum because these values land in config entries and logs."""

    INTERNATIONAL = "international"
    CHINA = "china"


@dataclass(frozen=True, slots=True)
class AnycubicEndpoints:
    """Every address that differs between deployments.

    Frozen: an API object binds its cookie jar, MQTT client id and signed
    headers to a host during setup, so an endpoint that could change
    underneath a live connection would only ever produce a half-migrated
    client talking to two services at once.
    """

    base_domain: str
    auth_domain: str
    mqtt_host: str
    mqtt_port: int
    public_api_endpoint: str
    project_image_url_base: str
    # Whether the broker's certificate is expected to name mqtt_host. The
    # international broker's does. The China broker presents a certificate
    # that does NOT cover its public DNS name (field-verified:
    # "certificate is not valid for 'mqtt.anycubicloud.com'"), and the
    # Slicer connects to it regardless -- trust there rests on the pinned
    # private Anycubic CA plus the client certificate, exactly as the LAN
    # client already does. Verification against that CA stays on either way.
    mqtt_verify_hostname: bool = True

    @property
    def base_url(self) -> str:
        # Trailing slash, because public_api_endpoint carries no leading one.
        return f"https://{self.base_domain}/"

    @property
    def public_api_root(self) -> str:
        return f"{self.base_url}{self.public_api_endpoint}"

    @property
    def origin(self) -> str:
        return f"https://{self.auth_domain}"


REGIONS: Mapping[AnycubicRegion, AnycubicEndpoints] = {
    AnycubicRegion.INTERNATIONAL: AnycubicEndpoints(
        base_domain=BASE_DOMAIN,
        auth_domain=AUTH_DOMAIN,
        mqtt_host=MQTT_HOST,
        mqtt_port=MQTT_PORT,
        public_api_endpoint=PUBLIC_API_ENDPOINT,
        project_image_url_base=PROJECT_IMAGE_URL_BASE,
    ),
    AnycubicRegion.CHINA: AnycubicEndpoints(
        # Reported on issue #13 and NOT verified by a maintainer -- nobody
        # here has a China account or printer. Treat these three as the
        # reporter's observation until someone confirms them against live
        # traffic.
        base_domain="cloud-platform.anycubicloud.com",
        auth_domain="uc.makeronline.cn",
        mqtt_host="mqtt.anycubicloud.com",
        mqtt_verify_hostname=False,
        # Not reported. 8883 is standard MQTT-over-TLS and matches the
        # international deployment; a wrong port here produces a silent,
        # permanent reconnect loop rather than an error, so it is worth
        # asking about explicitly.
        mqtt_port=MQTT_PORT,
        # Unreported, so assumed shared. The API path is a route within the
        # application, not infrastructure, and there is no reason for it to
        # differ.
        public_api_endpoint=PUBLIC_API_ENDPOINT,
        # An S3 bucket, so plausibly global. If China serves images from
        # elsewhere the worst case is a missing thumbnail, which is why this
        # is a safe assumption to ship without confirmation.
        project_image_url_base=PROJECT_IMAGE_URL_BASE,
    ),
}

DEFAULT_REGION = AnycubicRegion.INTERNATIONAL


def resolve_region(value: AnycubicRegion | str | None) -> AnycubicRegion:
    """The region for a stored value, never raising.

    Existing config entries predate this field and simply have no region, and
    a LAN-only entry will never acquire one. Both must keep working, so an
    absent or unrecognised value resolves to international -- the behaviour
    every current install already has.

    Raising here would be the worst possible failure: it happens during setup,
    so a typo in stored data would take an entry permanently offline rather
    than merely pointing it at the wrong cloud.
    """
    if isinstance(value, AnycubicRegion):
        return value

    if isinstance(value, str):
        try:
            return AnycubicRegion(value.strip().lower())
        except ValueError:
            return DEFAULT_REGION

    return DEFAULT_REGION
