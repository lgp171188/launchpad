#!/usr/bin/python3 -S
#
# Copyright 2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import _pythonpath  # noqa: F401

from lp.translations.utilities.translationmerger import MergeExistingPackagings

if __name__ == "__main__":
    script = MergeExistingPackagings(
        "lp.services.scripts.message-sharing-merge", dbuser="rosettaadmin"
    )
    script.run()
