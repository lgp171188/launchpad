#!/usr/bin/python3 -S
#
# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""
Rebuild the full text indexes in a more friendly fashion, enabling this to
be done without downtime.
"""

import _pythonpath  # noqa: F401

import psycopg

from fti import ALL_FTI


def main():
    con = psycopg.connect("dbname=launchpad_prod user=postgres")
    con.set_isolation_level(0)  # autocommit
    cur = con.cursor()

    for table, _ in ALL_FTI:
        print("Doing %s" % table, end="")
        cur.execute("SELECT id FROM %s" % table)
        ids = [row[0] for row in cur.fetchall()]
        for id in ids:
            cur.execute("UPDATE %s SET fti=NULL WHERE id=%s" % (table, id))
            if id % 100 == 0:
                print(".", end="")
        print()


if __name__ == "__main__":
    main()
