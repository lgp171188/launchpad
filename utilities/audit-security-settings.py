#! /usr/bin/python3 -S

# Copyright 2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Check that everything is alright in security.cfg

Usage hint:

% utilities/audit-security.py
"""

from __future__ import absolute_import, print_function

__metatype__ = type

import _pythonpath  # noqa: F401

import os

from lp.scripts.utilities.settingsauditor import SettingsAuditor


BRANCH_ROOT = os.path.split(
    os.path.dirname(os.path.abspath(__file__)))[0]
SECURITY_PATH = os.path.join(
    BRANCH_ROOT, 'database', 'schema', 'security.cfg')


def main():
    with open(SECURITY_PATH) as f:
        data = f.read()
    auditor = SettingsAuditor(data)
    settings = auditor.audit()
    with open(SECURITY_PATH, 'w') as f:
        f.write(settings)
    print(auditor.error_data)

if __name__ == '__main__':
    main()
