# anycubic-cloud-api

Async Python client for the **Anycubic Cloud** API and its MQTT telemetry stream.

Extracted from the [Home Assistant Anycubic Cloud integration](https://github.com/Nino6689/hass-anycubic_cloud)
so it can be versioned, tested and used independently.

## Install

```bash
pip install anycubic-cloud-api
```

## Use

```python
import aiohttp
from anycubic_cloud_api import AnycubicMQTTAPI, AnycubicAuthMode

async with aiohttp.ClientSession() as session:
    api = AnycubicMQTTAPI(session=session)
    api.set_authentication(auth_token="eyJ...", auth_mode=AnycubicAuthMode.SLICER)

    if await api.check_api_tokens():
        for printer in await api.list_my_printers():
            print(printer.name, printer.current_status)
```

## Authentication

Anycubic's login is captcha- and 2FA-protected, so there is no automated
sign-in: you supply a **token** obtained from the Anycubic slicer, website, or
Android app. Slicer tokens are 90-day JWTs and additionally unlock the MQTT
stream; web tokens are polling-only.

## TLS

The MQTT broker requires **mutual TLS** using Anycubic's own certificates, which
ship inside this package. The client verifies the broker against Anycubic's
pinned root CA with hostname checking enabled. Two relaxations are unavoidable
and forced by Anycubic's certificates:

- their client certificate is SHA-1 signed, so OpenSSL 3.x will not load it at
  the default security level
- their root CA omits the `keyUsage` extension, which Python 3.13+ rejects as a
  trust anchor under `VERIFY_X509_STRICT`

Neither weakens chain or hostname verification.

## Licence

GPL-3.0-or-later, matching the integration it came from.
