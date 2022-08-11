#!/usr/bin/python3
#
# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

r"""
This script is a filter that converts a PostgreSQL plain text schema
dump into a file suitable to be used as a Launchpad database baseline,
stripping out all the Slony-I cruft.

To use, first create a dump of a Launchpad production database schema::

    pg_dump --format=p --schema-only --exclude-schema=_sl \
            --no-privileges --no-owner launchpad_prod_1 > lpraw.sql

Then run it through this filter to create a new baseline::

    ./newbaseline.py < lpraw.sql > newbaseline.sql
"""

import re
import sys
from datetime import datetime, timezone


def main():
    sql = sys.stdin.read()

    # Strip out comment noise
    sql, count = re.subn(r"(?m)(?:^--.*\n)+\s+", "", sql)
    assert count > 0, "regexp failed to match"

    # Strip out Slony-I triggers, which we still get despite dumping
    # using --exclude-schema=_sl because they are in the public schema.
    sql, count = re.subn(
        r"""(?xm)
        ^CREATE \s TRIGGER \s _sl_[^;]+;
        \s+
        (?:^ALTER \s TABLE \s [^;]+ \s DISABLE \s TRIGGER \s _sl_ [^;]+;\s+)?
        """,
        "",
        sql,
    )
    assert count > 0, "regexp failed to match"

    print(
        "-- Generated %s UTC"
        % (datetime.now().replace(tzinfo=timezone.utc).ctime())
    )
    print()
    print("SET client_min_messages TO ERROR;")
    print(sql)


if __name__ == "__main__":
    raise SystemExit(main())
