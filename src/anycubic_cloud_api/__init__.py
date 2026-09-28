"""Async client for the Anycubic Cloud API and its MQTT stream.

Extracted from the Home Assistant `anycubic_cloud` integration so the client
can be versioned, tested and consumed independently.
"""

from .anycubic_api import AnycubicAPI, AnycubicMQTTAPI
from .const.enums import (
    AnycubicFeedType,
    AnycubicFunctionID,
    AnycubicOrderID,
    AnycubicPrinterMaterialType,
    AnycubicPrintStatus,
)
from .data_models.orders import AnycubicShengwangCredentials
from .data_models.printer import AnycubicPrinter
from .data_models.printer_properties import AnycubicAxisPosition
from .data_models.project import AnycubicProject
from .exceptions.exceptions import (
    AnycubicAPIError,
    AnycubicAPIParsingError,
    AnycubicRateLimitError,
    AnycubicAuthError,
    AnycubicAuthTokensExpired,
    AnycubicCloudUploadError,
    AnycubicDataParsingError,
    AnycubicFileNotFoundError,
    AnycubicGcodeParsingError,
    AnycubicInvalidValue,
    AnycubicMQTTClientError,
    AnycubicMQTTUnhandledData,
    AnycubicMQTTUnknownUpdate,
    AnycubicPropertiesNotLoaded,
)
from .models.auth import AnycubicAuthentication, AnycubicAuthMode

__version__ = "0.1.4"

__all__ = [
    "AnycubicAxisPosition",
    "AnycubicAPI",
    "AnycubicAPIError",
    "AnycubicAPIParsingError",
    "AnycubicRateLimitError",
    "AnycubicAuthError",
    "AnycubicAuthMode",
    "AnycubicAuthTokensExpired",
    "AnycubicAuthentication",
    "AnycubicCloudUploadError",
    "AnycubicDataParsingError",
    "AnycubicFeedType",
    "AnycubicFileNotFoundError",
    "AnycubicFunctionID",
    "AnycubicGcodeParsingError",
    "AnycubicInvalidValue",
    "AnycubicMQTTAPI",
    "AnycubicMQTTClientError",
    "AnycubicMQTTUnhandledData",
    "AnycubicMQTTUnknownUpdate",
    "AnycubicOrderID",
    "AnycubicPrintStatus",
    "AnycubicPrinter",
    "AnycubicPrinterMaterialType",
    "AnycubicProject",
    "AnycubicPropertiesNotLoaded",
    "AnycubicShengwangCredentials",
    "__version__",
]
