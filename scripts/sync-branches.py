#!/usr/bin/python2 -S
# Copyright 2021 Canonical Ltd.  All rights reserved.

"""Sync branches from production to a staging environment."""

import _pythonpath  # noqa: F401

from lp.codehosting.scripts.sync_branches import SyncBranchesScript


if __name__ == "__main__":
    script = SyncBranchesScript("sync-branches", dbuser="ro")
    script.lock_and_run()
