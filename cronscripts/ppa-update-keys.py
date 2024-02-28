#!/usr/bin/python3 -S
#
# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""
A cron script that generates 4096-bit RSA signing keys for PPAs that only
have 1024-bit RSA signing keys.
"""

import _pythonpath  # noqa: F401

from lp.services.config import config
from lp.soyuz.scripts.ppakeyupdater import PPAKeyUpdater

if __name__ == "__main__":
    script = PPAKeyUpdater("ppa-generate-keys", config.archivepublisher.dbuser)
    script.lock_and_run()
