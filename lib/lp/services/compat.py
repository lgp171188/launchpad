# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Python 2/3 compatibility layer.

Use this for things that six doesn't provide.
"""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    'SafeConfigParser',
    'mock',
    ]

try:
    from configparser import ConfigParser as SafeConfigParser
except ImportError:
    from ConfigParser import SafeConfigParser


try:
    import mock
except ImportError:
    from unittest import mock
