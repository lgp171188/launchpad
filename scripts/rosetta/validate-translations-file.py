#!/usr/bin/python3 -S
# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import _pythonpath  # noqa: F401

import sys

from lp.translations.scripts.validate_translations_file import (
    ValidateTranslationsFile,
)

if __name__ == "__main__":
    sys.exit(ValidateTranslationsFile().main())
