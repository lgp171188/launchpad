# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Python compatibility layer.

Use this for things that six doesn't provide.
"""

__all__ = [
    "message_as_bytes",
]

import io


def message_as_bytes(message):
    from email.generator import BytesGenerator
    from email.policy import compat32

    fp = io.BytesIO()
    g = BytesGenerator(fp, mangle_from_=False, maxheaderlen=0, policy=compat32)
    g.flatten(message)
    return fp.getvalue()
