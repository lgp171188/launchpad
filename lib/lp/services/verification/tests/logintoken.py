# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Helper functions for logintoken-related tests."""

import re

import six

from lp.services.compat import message_from_bytes


def get_token_url_from_email(email_msg):
    """Return the logintoken URL contained in the given email message."""
    msg = message_from_bytes(email_msg)
    return get_token_url_from_bytes(msg.get_payload(decode=True))


def get_token_url_from_bytes(buf):
    """Return the logintoken URL contained in the given byte string."""
    return six.ensure_str(re.findall(br'http.*/token/.*', buf)[0])
