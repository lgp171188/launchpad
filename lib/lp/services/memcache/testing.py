# Copyright 2016-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "MemcacheFixture",
]

import time as _time

import fixtures
from pymemcache.exceptions import MemcacheIllegalInputError

from lp.services.memcache.client import MemcacheClient
from lp.services.memcache.interfaces import IMemcacheClient
from lp.testing.fixture import ZopeUtilityFixture


class MemcacheFixture(fixtures.Fixture, MemcacheClient):
    """A trivial in-process memcache fixture."""

    def __init__(self):
        self._cache = {}

    def _setUp(self):
        self.useFixture(ZopeUtilityFixture(self, IMemcacheClient))

    def get(self, key, default=None, logger=None):
        value, expiry_time = self._cache.get(key, (None, None))
        if expiry_time and _time.time() >= expiry_time:
            self.delete(key)
            return None
        else:
            return value

    def set(self, key, val, expire=0, logger=None):
        # memcached accepts either delta-seconds from the current time or
        # absolute epoch-seconds, and tells them apart using a magic
        # threshold.  See memcached/memcached.c:realtime.
        MONTH_IN_SECONDS = 60 * 60 * 24 * 30
        if expire:
            if not isinstance(expire, int):
                raise MemcacheIllegalInputError(
                    "expire must be integer, got bad value: %r" % expire
                )
            if expire <= MONTH_IN_SECONDS:
                expire = int(_time.time()) + expire
        self._cache[key] = (val, expire)
        return 1

    def delete(self, key, logger=None):
        self._cache.pop(key, None)
        return 1

    def clear(self):
        self._cache = {}
