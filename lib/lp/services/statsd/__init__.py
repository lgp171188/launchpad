# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Statsd client wrapper with Launchpad configuration"""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = ['LPStatsClient']


from lp.services.config import config
from statsd import StatsClient


class UnconfiguredStatsdClient:
    """Dummy client for if statsd is not configured in the environment.

    This client will be used if the statsd settings are not available to
    Launchpad. Prevents unnecessary network traffic.
    """

    def __call__(self, *args, **kwargs):
        pass


if config.statsd.host:
    LPStatsClient = StatsClient(
        host=config.statsd.host,
        port=config.statsd.port,
        prefix=config.statsd.prefix)
else:
    LPStatsClient = UnconfiguredStatsdClient()
