"""Printer error codes, as published by Anycubic.

Transcribed from the manufacturer's own list at
https://wiki.anycubic.com/en/error-codes -- so the wording a user reads in
Home Assistant is the wording they will find if they go looking the code up,
and the table can be refreshed from one place when Anycubic adds to it.

The printer reports a result code on every message it sends. In normal
operation that code is 200 (or 0): "message processed", not a fault. Only the
other values mean something went wrong, and those are the ones listed here.

The list is not exhaustive and is not meant to be. Anycubic ships codes that
have never appeared on the wiki -- 11858, reported from a Kobra X ACE in
issue #21, is one of them -- and newer firmware will add more. An unknown
code is reported as itself rather than guessed at: a number the user can
search for is worth more than a label that might be wrong.
"""

from typing import Final

# Codes that mean "nothing is wrong". Everything else is a fault.
PRINTER_OK_CODES: Final[frozenset[int]] = frozenset({0, 200})

PRINTER_ERROR_CODES: Final[dict[int, str]] = {
    10000: "Unknown error",
    10101: "There already has a printing task",
    10102: "There is no print task",
    10103: "The printing task has been suspended",
    10104: "The printing task has stopped",
    10105: "File download failed",
    10106: "Insufficient memory available",
    10107: "Filament broken",
    10111: "Task abnormally ended",
    10113: "Failed to verify the MD5 checksum of the downloaded file",
    10115: "The device cannot parse the file",
    10116: "Abnormal slice file",
    10118: "X-axis homing failed",
    10119: "Y-axis homing failed",
    10120: "Z-axis homing failed",
    10121: "Hotbed heating abnormal",
    10122: "Extruder heating abnormal",
    10123: "Hotbed NTC abnormal",
    10124: "Extruder NTC abnormal",
    10125: "The printing task has been restored",
    10126: "X-axis vibration compensation detected abnormal",
    10127: "Y-axis vibration compensation detected abnormal",
    10128: "X-axis vibration compensation abnormal",
    10130: "Z-axis homing failed",
    10131: "Nozzle Mcu abnormal",
    10132: "The print head is scratched",
    10133: "The file is missing necessary commands",
    10134: "This feature requires access to the camera",
    10135: "This function requires a USB flash drive",
    10136: "This function requires access to both the camera and the USB stick",
    10137: "The remaining capacity of the USB flash drive is less than 800M, and the ti...",
    10237: "Auto-leveling failed",
    10401: "User initiates print stop",
    10402: "Filament broken, please load a new filament",
    10403: "Filament broken, please load a new filament into the ACE",
    10408: "The firmware version of the print head or mainboard is too low to start the...",
    10409: "An issue occurred",
    10411: "TMC or extruder overheat. Please check cooling",
    10412: "An issue occurred",
    10413: "An issue occurred",
    10414: "An issue occurred",
    10415: "The heated bed temperature is too high.",
    10536: "ACE Pro Error. Please restart",
    10537: "Nozzle size does not match",
    10603: "Print task abnormally interrupted",
    10607: "Forces the end of the task",
    10608: "Task abnormally ended",
    10609: "Initiated by the user",
    10801: "Firmware download failed",
    10802: "Firmware update failed",
    10803: "Insufficient memory available",
    10804: "Failed to mount external storage",
    10805: "Firmware verification failed",
    11001: "Failed to delete local file",
    11101: "WiFi connection failed",
    11401: "The camera is not connected",
    11402: "Network connection timed out",
    11403: "The camera detects an anomaly",
    11404: "Video stream startup failed",
    11407: "The device fails to start",
    11412: "The mainboard MCU and the driver MCU is disconnected",
    11503: "There is a problem with the connection of the ACE Pro",
    11504: "Unknown feed location for notmulti-color model",
    11505: "The drying request did not enter the target temperature",
    11506: "Requests drying without entering the duration",
    11508: "Edit the color of consumables without entering the type of consumables",
    11509: "ACE responses timeout",
    11511: "Extrusion abnormal",
    11512: "Retraction abnormal",
    11513: "ACE Pro responses timeout",
    11517: "There has no ACE Pro connection",
    11518: "Filament clogging detected",
    11519: "Filament tangle detected",
    11520: "ACE Pro is out of material",
    11521: "Abnormal rotation of the color engine motor",
    11524: "There is a problem with the connection of the ACE Pro",
    11525: "The number of filaments in the ACE Pro does not meet the requirements of th...",
    11527: "ACE Pro is working and cannot be upgraded",
    11529: "ACE Pro NTC abnormal",
    11530: "ACE Pro PTC abnormal",
    11531: "The number of model colors is greater than 8 and cannot be printed",
    11532: "Device lacks automatic leveling",
    11534: "Auto-leveling failed",
    11535: "Unknown consumables in the material breaking module",
    11538: "Cutter signal error",
    11801: "Detected messy printing offried noodles, task has been paused",
    11802: "Foreign Object Detected. Check Print Area is Clean",
    11810: "Ambient Light Too Dim",
    11811: "Camera Possibly Obstructed — Obstruction Affects Detection Accuracy",
    11812: "Spaghetti Detected — Please Check If Printing Is Affected",
    11813: "Power supply error, please turn off the printer",
    11817: "E-axis motor module may have a short circuit",
    11830: "The device may not have enough remaining storage space, which may cause the...",
    11831: "Failed to delete local file",
    11871: "Print Head Shell Detached",
}


def describe_printer_code(code: int) -> str:
    """What to call a code, including the ones Anycubic has not published."""
    known = PRINTER_ERROR_CODES.get(code)

    return known if known is not None else f"Unknown error code {code}"
