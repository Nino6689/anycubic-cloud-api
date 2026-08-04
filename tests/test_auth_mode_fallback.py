"""A web token mistaken for a slicer token must still work.

Reported by a user on a Kobra 2 Pro: a valid web token was rejected with
"Authentication failed. Check credentials." Both kinds are JWTs, so the shape
of the token cannot tell them apart -- the integration guessed slicer, sent it
to a login endpoint that answered "User does not exist", and gave up.
"""

import pytest

from anycubic_cloud_api.models.auth import AnycubicAuthentication, AnycubicAuthMode

TOKEN = "eyJhbGciOiJSUzI1NiJ9.payload.signature"


def slicer_auth():
    """What set_authentication produces for a token guessed to be a slicer one."""
    return AnycubicAuthentication(
        auth_token=None,
        auth_mode=AnycubicAuthMode.SLICER,
        device_id=None,
        auth_access_token=TOKEN,
    )


class TestRetryingAsAWebToken:
    def test_a_rejected_slicer_token_becomes_a_web_token(self):
        auth = slicer_auth()

        assert auth.retry_access_token_as_user_token() is True
        assert auth._auth_token == TOKEN
        assert auth._auth_access_token is None
        assert auth._auth_mode == AnycubicAuthMode.WEB

    def test_it_no_longer_asks_for_an_access_token_login(self):
        """Otherwise the caller would loop on the same failing endpoint."""
        auth = slicer_auth()
        assert auth.requires_access_token is True

        auth.retry_access_token_as_user_token()

        assert auth.requires_access_token is False

    def test_it_only_fires_once(self):
        auth = slicer_auth()

        assert auth.retry_access_token_as_user_token() is True
        assert auth.retry_access_token_as_user_token() is False

    def test_a_genuine_web_token_has_nothing_to_retry(self):
        auth = AnycubicAuthentication(
            auth_token=TOKEN, auth_mode=AnycubicAuthMode.WEB,
            device_id=None, auth_access_token=None,
        )

        assert auth.retry_access_token_as_user_token() is False

    def test_an_android_token_is_left_alone(self):
        """Android supplies a device id and is never ambiguous."""
        auth = AnycubicAuthentication(
            auth_token=TOKEN, auth_mode=AnycubicAuthMode.ANDROID,
            device_id="device123", auth_access_token=None,
        )

        assert auth.retry_access_token_as_user_token() is False
        assert auth._auth_mode == AnycubicAuthMode.ANDROID
