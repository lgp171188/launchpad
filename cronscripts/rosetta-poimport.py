#!/usr/bin/python2 -S
#
# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import _pythonpath  # noqa: F401

from lp.services.config import config
from lp.translations.scripts.po_import import TranslationsImport


if __name__ == '__main__':
    script = TranslationsImport(
        'rosetta-poimport', dbuser=config.poimport.dbuser)
    script.lock_and_run()
