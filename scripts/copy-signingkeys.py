#!/usr/bin/python3 -S
# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Script to copy signing keys between archives."""

import _pythonpath  # noqa: F401

from lp.archivepublisher.scripts.copy_signingkeys import CopySigningKeysScript
from lp.services.config import config


if __name__ == '__main__':
    script = CopySigningKeysScript(
        'copy-signingkeys', dbuser=config.archivepublisher.dbuser)
    script.lock_and_run()
