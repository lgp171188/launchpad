#!/usr/bin/python3 -S
#
# Copyright 2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Database garbage collector, every 5 minutes.

Remove or archive unwanted data. Detect, warn and possibly repair data
corruption.
"""

__all__ = []

import _pythonpath  # noqa: F401

from lp.scripts.garbo import FrequentDatabaseGarbageCollector

if __name__ == "__main__":
    script = FrequentDatabaseGarbageCollector()
    script.continue_on_failure = True
    script.lock_and_run()
