# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Personal access token utilities."""

__all__ = [
    "create_access_token_secret",
]

import binascii
import os


# XXX cjwatson 2021-09-30: Replace this with secrets.token_hex(32) once we
# can rely on Python 3.6 everywhere.
def create_access_token_secret():
    """Create a secret suitable for use in a personal access token."""
    return binascii.hexlify(os.urandom(32)).decode("ASCII")
