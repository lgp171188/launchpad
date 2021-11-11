# Copyright 2009-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Launchpad Memcache client."""

__all__ = [
    'memcache_client_factory',
    ]

import re

from pymemcache.client.hash import HashClient
from pymemcache.serde import (
    python_memcache_deserializer,
    python_memcache_serializer,
    )

from lp.services.config import config


def memcache_client_factory(timeline=True):
    """Return a pymemcache HashClient for Launchpad."""
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
        client_factory = HashClient
    return client_factory(
        servers,
        serializer=python_memcache_serializer,
        deserializer=python_memcache_deserializer
    )
