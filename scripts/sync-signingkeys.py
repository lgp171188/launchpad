#!/usr/bin/python3 -S
# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Script to inject archive keys into signing service."""

import _pythonpath  # noqa: F401

from lp.archivepublisher.scripts.sync_signingkeys import SyncSigningKeysScript
from lp.services.config import config

if __name__ == "__main__":
    script = SyncSigningKeysScript(
        "sync-signingkeys", dbuser=config.archivepublisher.dbuser
    )
    script.lock_and_run()
