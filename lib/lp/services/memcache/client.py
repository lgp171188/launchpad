# Copyright 2009-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Launchpad Memcache client."""

__all__ = [
    'memcache_client_factory',
    ]

import re

import memcache

from lp.services.config import config


def memcache_client_factory(timeline=True):
    """Return a memcache.Client for Launchpad."""
    servers = [
        (host, int(weight)) for host, weight in re.findall(
            r'\((.+?),(\d+)\)', config.memcache.servers)]
    assert len(servers) > 0, "Invalid memcached server list %r" % (
        config.memcache.servers,)
    if timeline:
        from lp.services.memcache.timeline import TimelineRecordingClient
        client_factory = TimelineRecordingClient
    else:
        client_factory = memcache.Client
    return client_factory(servers)
