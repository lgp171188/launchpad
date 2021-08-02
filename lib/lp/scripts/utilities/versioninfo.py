# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Script to show version information.

This is useful in deployment scripts.
"""

__metaclass__ = type
__all__ = ['main']

import argparse

from lp.app import versioninfo


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        '-a', '--attribute',
        choices=['revision', 'display_revision', 'date', 'branch_nick'],
        help='Display a single version information attribute.')
    args = parser.parse_args()

    if args.attribute:
        print(getattr(versioninfo, args.attribute))
    else:
        print('Revision:', versioninfo.revision)
        print('Display revision:', versioninfo.display_revision)
        print('Date:', versioninfo.date)
        print('Branch nick:', versioninfo.branch_nick)
