# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Interfaces for configuring and retrieving a statsd client."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = ['IStatsdClient']


from zope.interface import Interface


class IStatsdClient(Interface):
    """Methods for retrieving a statsd client using Launchpad config."""

    def getClient():
        """Return an appropriately configured statsd client."""
