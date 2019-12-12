#!/usr/bin/python -S

# Copyright 2009-2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Sync Mailman data from one Launchpad to another."""

import _pythonpath

import sys

from lp.services.mailman.scripts.mlist_sync import MailingListSyncScript


if __name__ == '__main__':
    script = MailingListSyncScript('mlist-sync', dbuser='mlist-sync')
    status = script.lock_and_run()
    sys.exit(status)
