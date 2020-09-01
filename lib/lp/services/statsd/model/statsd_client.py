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


class UnconfiguredStatsdClient:
    """Dummy client for if statsd is not configured in the environment.

    This client will be used if the statsd settings are not available to
    Launchpad. Prevents unnecessary network traffic.
    """

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


@implementer(IStatsdClient)
class StatsdClient:
    """See `IStatsdClient`."""

    client = None

    def getClient(self):
        if not self.client:
            if config.statsd.host:
                self.client = StatsClient(
                    host=config.statsd.host,
                    port=config.statsd.port,
                    prefix=config.statsd.prefix)
            else:
                self.client = UnconfiguredStatsdClient()
        return self.client
