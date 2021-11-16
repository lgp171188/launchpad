# Copyright 2009-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Launchpad Memcache client."""

__all__ = [
    'MemcacheClient',
    'memcache_client_factory',
    ]

import json
import re

from pymemcache.client.hash import HashClient
from pymemcache.serde import (
    python_memcache_deserializer,
    python_memcache_serializer,
    )

from lp.services.config import config


class MemcacheClient(HashClient):
    """memcached client with added JSON handling"""

    def get_json(self, key, logger, description, default=None):
        """Returns decoded JSON data from a memcache instance for a given key

        In case of a decoding issue, and given a logger and a description, an
        error message gets logged.

        The `default` value is used when no value could be retrieved, or an
        error happens.

        :returns: dict or the default value
        """
        data = self.get(key)
        if data is not None:
            try:
                rv = json.loads(data)
            # the exceptions are chosen deliberately in order to gracefully
            # handle invalid data
            except (TypeError, ValueError):
                if logger and description:
                    logger.exception(
                        "Cannot load cached %s; deleting" % description
                    )
                self.delete(key)
                rv = default
        else:
            rv = default
        return rv

    def set_json(self, key, value, expire=0):
        """Saves the given key/value pair, after converting the value.

        `expire` (optional int) is the number of seconds until the item
            expires from the cache; zero means no expiry.
        """
        self.set(key, json.dumps(value), expire)


def memcache_client_factory(timeline=True):
    """Return an extended pymemcache client for Launchpad."""
    # example value for config.memcache.servers:
    # (127.0.0.1:11242,1)
    servers = [
        host for host, _ in re.findall(
            r'\((.+?),(\d+)\)', config.memcache.servers)]
    assert len(servers) > 0, "Invalid memcached server list %r" % (
        config.memcache.servers,)
    if timeline:
        from lp.services.memcache.timeline import TimelineRecordingClient
        client_factory = TimelineRecordingClient
    else:
        client_factory = MemcacheClient
    return client_factory(
        servers,
        serializer=python_memcache_serializer,
        deserializer=python_memcache_deserializer
    )
