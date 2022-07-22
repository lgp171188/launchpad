#!/usr/bin/python3 -S
#
# Copyright 2009-2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import _pythonpath  # noqa: F401

from launchpad_loggerhead.wsgi import LoggerheadApplication

if __name__ == "__main__":
    LoggerheadApplication().run()
