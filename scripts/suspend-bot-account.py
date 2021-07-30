#!/usr/bin/python3 -S
#
# Copyright 2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import _pythonpath  # noqa: F401

from lp.registry.scripts.suspendbotaccount import SuspendBotAccountScript


if __name__ == '__main__':
    script = SuspendBotAccountScript('suspend-bot-account', dbuser='launchpad')
    script.run()
