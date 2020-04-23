#!/usr/bin/python2 -S
# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Script to inject archive keys into signing service."""
import _pythonpath
from lp.archivepublisher.scripts.sync_signingkeys import SyncSigningKeysScript

if __name__ == '__main__':
    script = SyncSigningKeysScript(
        'lp.archivepublisher.scripts.sync_signingkeys')
    script.lock_and_run()
