# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Python compatibility layer.

Use this for things that six doesn't provide.
"""

__all__ = [
    "message_as_bytes",
    "tzname",
]

import io
from datetime import datetime, time, timezone
from typing import Union


def message_as_bytes(message):
    from email.generator import BytesGenerator
    from email.policy import compat32

    fp = io.BytesIO()
    g = BytesGenerator(fp, mangle_from_=False, maxheaderlen=0, policy=compat32)
    g.flatten(message)
    return fp.getvalue()


def tzname(obj: Union[datetime, time]) -> str:
    """Return this (date)time object's time zone name as a string.

    Python 3.5's `timezone.utc.tzname` returns "UTC+00:00", rather than
    "UTC" which is what we prefer.  Paper over this until we can rely on
    Python >= 3.6 everywhere.
    """
    if obj.tzinfo is None:
        return ""
    elif obj.tzinfo is timezone.utc:
        return "UTC"
    else:
        return obj.tzname()
