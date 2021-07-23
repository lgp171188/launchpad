#!/usr/bin/python2 -S
#
# Copyright 2017 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import _pythonpath  # noqa: F401

from lp.registry.scripts.createbotaccount import CreateBotAccountScript


if __name__ == '__main__':
    script = CreateBotAccountScript('create-bot-account', dbuser='launchpad')
    script.run()
