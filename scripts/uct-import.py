#!/usr/bin/python3 -S
#
# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).
import _pythonpath  # noqa: F401

from lp.bugs.scripts.uctimport import UCTImportScript

if __name__ == "__main__":
    script = UCTImportScript("lp.services.scripts.uctimport")
    script.run()
