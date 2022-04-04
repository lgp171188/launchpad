#!/usr/bin/python3 -S
#
# Copyright 2009-2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# This script updates the cached source package information in the system.
# We use this for fast source package searching (as opposed to joining
# through gazillions of publishing tables).

import _pythonpath  # noqa: F401

from lp.soyuz.scripts.update_pkgcache import PackageCacheUpdater


if __name__ == "__main__":
    script = PackageCacheUpdater("update-cache", dbuser="update-pkg-cache")
    script.lock_and_run()
