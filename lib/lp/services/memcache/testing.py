# Copyright 2016-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type
__all__ = [
    'MemcacheFixture',
    ]

import time as _time

import fixtures

from lp.services.memcache.interfaces import IMemcacheClient
from lp.testing.fixture import ZopeUtilityFixture


class MemcacheFixture(fixtures.Fixture):
    """A trivial in-process memcache fixture."""

    def __init__(self):
        self._cache = {}

    def _setUp(self):
        self.useFixture(ZopeUtilityFixture(self, IMemcacheClient))

    def get(self, key):
        value, expiry_time = self._cache.get(key, (None, None))
        if expiry_time and _time.time() >= expiry_time:
            self.delete(key)
            return None
        else:
            return value

    def set(self, key, val, time=0):
        # memcached accepts either delta-seconds from the current time or
        # absolute epoch-seconds, and tells them apart using a magic
        # threshold.  See memcached/memcached.c:realtime.
        if time and time <= 60 * 60 * 24 * 30:
            time = _time.time() + time
        self._cache[key] = (val, time)
        return 1

    def delete(self, key):
        self._cache.pop(key, None)
        return 1

    def clear(self):
        self._cache = {}
