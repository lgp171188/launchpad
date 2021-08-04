# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Python 2/3 compatibility layer.

Use this for things that six doesn't provide.
"""

__metaclass__ = type
__all__ = [
    'escape',
    'message_as_bytes',
    'message_from_bytes',
    'mock',
    'SafeConfigParser',
    ]

try:
    from configparser import ConfigParser as SafeConfigParser
except ImportError:
    from ConfigParser import SafeConfigParser

try:
    from email import message_from_bytes
except ImportError:
    from email import message_from_string as message_from_bytes

try:
    from html import escape
except ImportError:
    from cgi import escape

import io

try:
    import mock
except ImportError:
    from unittest import mock

import six


if six.PY3:
    def message_as_bytes(message):
        from email.generator import BytesGenerator
        from email.policy import compat32

        fp = io.BytesIO()
        g = BytesGenerator(
            fp, mangle_from_=False, maxheaderlen=0, policy=compat32)
        g.flatten(message)
        return fp.getvalue()
else:
    def message_as_bytes(message):
        return message.as_string()
