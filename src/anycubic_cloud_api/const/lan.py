"""Constants for the printer's local (LAN Mode) interface."""

from __future__ import annotations

# The printer serves its discovery document here once LAN Mode is switched on
# at the panel. In cloud mode the port is closed entirely, which is the
# cheapest way to tell the two modes apart.
LAN_INFO_PORT = 18910
LAN_INFO_PATH = "/info"

# `ctrlType` in the discovery document. The printer talks to exactly one of the
# two -- turning LAN Mode on drops its cloud connection and vice versa -- so
# this doubles as the check for "is the printer actually in LAN Mode".
LAN_CTRL_TYPE_CLOUD = "cloud"

# Query string the /ctrl request is signed with.
LAN_NONCE_LENGTH = 6
LAN_DEVICE_ID_LENGTH = 32

# The signing token is also the AES key material: the first half keys the
# signature, the second half decrypts the response body.
LAN_TOKEN_SIGN_SLICE = slice(0, 16)
LAN_TOKEN_KEY_SLICE = slice(16, 32)

LAN_AES_BLOCK_BITS = 128
LAN_AES_IV_LENGTH = 16

LAN_HTTP_TIMEOUT = 10

# Local broker. The printer presents a self-signed certificate for an address
# that varies per unit, so this connection is encrypted but not verified --
# see AnycubicLANHandshake for why that is the right trade-off here.
LAN_MQTT_DEFAULT_PORT = 9883

LAN_REQUIRED_INFO_FIELDS = ("token", "ctrlInfoUrl", "modelId")
LAN_REQUIRED_BROKER_FIELDS = ("broker", "username", "password", "deviceId")
