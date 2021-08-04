#!/usr/bin/python3
#
# Copyright 2017-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""WSGI archive authorisation provider entry point.

Unlike most Launchpad scripts, the #! line of this script does not use -S.
This is because it is only executed (as opposed to imported) for testing,
and mod_wsgi does not disable the automatic import of the site module when
importing this script, so we want the test to imitate mod_wsgi's behaviour
as closely as possible.
"""

__metaclass__ = type
__all__ = [
    'check_password',
    ]

# mod_wsgi imports this file without a useful sys.path, so we need some
# acrobatics to set ourselves up properly.
import os.path
import sys

scripts_dir = os.path.dirname(os.path.abspath(os.path.realpath(__file__)))
if scripts_dir not in sys.path:
    sys.path.insert(0, scripts_dir)
top = os.path.dirname(scripts_dir)

# We can't stop mod_wsgi importing the site module.  Cross fingers and
# arrange for it to be re-imported.
sys.modules.pop("site", None)
sys.modules.pop("sitecustomize", None)

import _pythonpath  # noqa: F401 E402

from lp.soyuz.wsgi.archiveauth import check_password # noqa: E402


def main():
    """Hook for testing, not used by WSGI."""
    from argparse import ArgumentParser

    from lp.services.memcache.testing import MemcacheFixture
    from lp.soyuz.wsgi import archiveauth

    parser = ArgumentParser()
    parser.add_argument("archive_path")
    parser.add_argument("username")
    parser.add_argument("password")
    args = parser.parse_args()
    archiveauth._memcache_client = MemcacheFixture()
    result = check_password(
        {"SCRIPT_NAME": args.archive_path}, args.username, args.password)
    if result is None:
        return 2
    elif result is False:
        return 1
    elif result is True:
        return 0
    else:
        print("Unexpected result from check_password: %s" % result)
        return 3


if __name__ == "__main__":
    sys.exit(main())
