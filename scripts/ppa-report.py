#!/usr/bin/python3 -S
#
# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import _pythonpath  # noqa: F401

from lp.soyuz.scripts.ppareport import PPAReportScript

if __name__ == "__main__":
    script = PPAReportScript("ppareport", dbuser="ro")
    script.run()
