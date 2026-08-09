"""A project whose status the server did not fill in.

Reported from the China region (issue #13 on the integration), but nothing
about the field is region-specific -- `status: null` is simply a shape the
server is willing to send, and any account can be handed one.

It crashed with TypeError from inside a data model, several layers below
anything that knew what a project was, so it surfaced as a parse failure
rather than as a missing optional field. Every neighbouring setter on this
class already tolerated None; only this one did not.
"""

from unittest.mock import MagicMock

import pytest

from anycubic_cloud_api.data_models.project import AnycubicProject

# from_list_json indexes every one of these, so a fixture has to carry them
# all even though only `status` is under test.
_KEYS = [
    "id", "taskid", "user_id", "printer_id", "gcode_id", "model", "img",
    "estimate", "remain_time", "material", "material_type", "pause",
    "progress", "connect_status", "print_status", "reason", "slice_data",
    "slice_status", "status", "ischeck", "project_type", "printed",
    "create_time", "start_time", "end_time", "slice_start_time",
    "slice_end_time", "total_time", "print_time", "slice_param", "delete",
    "auto_operation", "monitor", "last_update_time", "settings", "localtask",
    "source", "device_message", "signal_strength", "key", "type",
    "machine_type", "printer_name", "machine_name", "device_status",
    "slice_result", "gcode_name", "post_title",
]


def project_json(**overrides):
    """A list-endpoint project, every field present and benign.

    Zero throughout: most of these run through int() on the way in, so an
    empty string is not the harmless placeholder it looks like.
    """
    return dict(dict.fromkeys(_KEYS, 0), **overrides)


def test_a_null_status_does_not_crash_the_parse():
    project = AnycubicProject.from_list_json(MagicMock(), project_json(status=None))

    assert project is not None
    assert project._status is None


def test_a_real_status_still_becomes_an_int():
    """The fix must not quietly swallow the values that do arrive."""
    project = AnycubicProject.from_list_json(MagicMock(), project_json(status="3"))

    assert project._status == 3


@pytest.mark.parametrize("absent", [None, 0])
def test_status_zero_is_kept_distinct_from_absent(absent):
    """Zero is a status; None is the absence of one. Not the same thing.

    Defaulting a missing status to 0 would have been the smaller diff, but it
    invents a state the server never reported -- and 0 is a value the server
    does send in its own right, so the two would be indistinguishable.
    """
    project = AnycubicProject.from_list_json(MagicMock(), project_json(status=absent))

    assert project._status == absent
