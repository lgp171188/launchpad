# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Personal access token utilities."""

__all__ = [
    "create_access_token_secret",
]

import secrets


def create_access_token_secret():
    """Create a secret suitable for use in a personal access token."""
    return secrets.token_hex(32)
