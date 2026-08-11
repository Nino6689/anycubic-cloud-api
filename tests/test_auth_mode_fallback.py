"""A web token mistaken for a slicer token must still work.

Reported by a user on a Kobra 2 Pro: a valid web token was rejected with
"Authentication failed. Check credentials." Both kinds are JWTs, so the shape
of the token cannot tell them apart -- the integration guessed slicer, sent it
to a login endpoint that answered "User does not exist", and gave up.
"""


import pytest

from anycubic_cloud_api.exceptions.exceptions import AnycubicMQTTClientError
from anycubic_cloud_api.helpers.helpers import md5_hex_of_string
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


class TestMqttClientIdWithoutEmail:
    """China accounts register against a mobile number, not an email.

    `user_info` returns `user_email: ""` for them, and the client id was
    md5(email) with a hard raise on a falsy value -- so MQTT failed before a
    socket was ever opened, and every China report chased TLS and ports
    instead. Reported in hass-anycubic#13.
    """

    def _auth(self, email, mobile, user_id=4242):
        auth = AnycubicAuthentication(auth_token=TOKEN)
        auth.set_api_user_id(user_id)
        auth.set_api_user_email(email)
        auth.set_api_user_mobile(mobile)
        return auth

    def test_an_email_account_is_unchanged(self):
        auth = self._auth("someone@example.com", None)
        assert auth.get_mqtt_client_id() == md5_hex_of_string("someone@example.com")

    def test_an_empty_email_falls_back_to_the_mobile(self):
        auth = self._auth("", "15010256036")
        assert auth.get_mqtt_client_id() == md5_hex_of_string("15010256036")

    def test_the_email_still_wins_when_both_are_present(self):
        auth = self._auth("someone@example.com", "15010256036")
        assert auth.get_mqtt_client_id() == md5_hex_of_string("someone@example.com")

    def test_neither_still_raises(self):
        auth = self._auth("", "")
        with pytest.raises(AnycubicMQTTClientError):
            auth.get_mqtt_client_id()

    def test_the_identifier_also_falls_back(self):
        assert self._auth("", "15010256036").api_user_identifier == "15010256036"
        assert self._auth("", "").api_user_identifier == "4242"

    def test_the_mqtt_username_carries_the_same_identity(self):
        """Client id and username must agree, or the broker sees a correct id
        beside an empty identity field and rejects it with nothing to log."""
        auth = self._auth("", "15010256036")
        auth.set_access_token("tok")
        username, _password = auth.get_mqtt_login_info()
        fields = username.split("|")
        assert fields[2] == "15010256036", f"identity field was {fields[2]!r}"
        assert "||" not in username
