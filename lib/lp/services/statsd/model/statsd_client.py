# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Statsd client wrapper with Launchpad configuration"""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = ['StatsdClient']


from statsd import StatsClient
from zope.interface import implementer

from lp.services.config import config
from lp.services.statsd.interfaces.statsd_client import IStatsdClient


client = None


@implementer(IStatsdClient)
class StatsdClient:
    """See `IStatsdClient`."""

    # We need to explicitly set the component name as otherwise our
    # __getattr__ may confuse component registration.
    __component_name__ = ""

    def __init__(self):
        self._make_client()

    def _make_client(self):
        if config.statsd.host:
            self._client = StatsClient(
                host=config.statsd.host,
                port=config.statsd.port,
                prefix=config.statsd.prefix)
        else:
            self._client = None

    def reload(self):
        self._make_client()

    def __getattr__(self, name):
        if self._client is not None:
            return getattr(self._client, name)
        else:
            # Prevent unnecessary network traffic if this Launchpad instance
            # has no statsd configuration.
            return lambda *args, **kwargs: None
