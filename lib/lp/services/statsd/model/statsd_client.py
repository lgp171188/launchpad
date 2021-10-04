# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Statsd client wrapper with Launchpad configuration"""

__all__ = ['StatsdClient']

import re

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
        """See `IStatsdClient`."""
        self._make_client()

    def _escapeMeasurement(self, measurement):
        # Escape a measurement name for the InfluxDB line protocol:
        #   https://docs.influxdata.com/influxdb/cloud/reference/syntax/\
        #       line-protocol/
        return re.sub(r"([, \\])", r"\\\1", measurement)

    def _escapeTag(self, tag):
        # Escape a tag key or value for the InfluxDB line protocol:
        #   https://docs.influxdata.com/influxdb/cloud/reference/syntax/\
        #       line-protocol/
        return re.sub(r"([,= \\])", r"\\\1", tag)

    def composeMetric(self, name, labels):
        """See `IStatsdClient`."""
        if labels is None:
            labels = {}
        elements = [self._escapeMeasurement(name)]
        for key, value in sorted(labels.items()):
            elements.append("{}={}".format(
                self._escapeTag(key), self._escapeTag(str(value))))
        return ",".join(elements)

    def __getattr__(self, name):
        if self._client is not None:
            wrapped = getattr(self._client, name)
            if name in ("timer", "timing", "incr", "decr", "gauge", "set"):
                def wrapper(stat, *args, **kwargs):
                    labels = kwargs.pop("labels", None) or {}
                    labels["env"] = config.statsd.environment
                    return wrapped(
                        self.composeMetric(stat, labels), *args, **kwargs)

                return wrapper
            else:
                return wrapped
        else:
            # Prevent unnecessary network traffic if this Launchpad instance
            # has no statsd configuration.
            return lambda *args, **kwargs: None
