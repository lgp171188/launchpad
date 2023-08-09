#!/usr/bin/python3 -S
#
# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Kill idle-in-transaction connections that have hung around for too long."""

__all__ = []

import _pythonpath  # noqa: F401

import sys
from optparse import OptionParser

import psycopg2


def main():
    parser = OptionParser()
    parser.add_option(
        "-c",
        "--connection",
        type="string",
        dest="connect_string",
        default="",
        help="Psycopg connection string",
    )
    parser.add_option(
        "-s",
        "--max-idle-seconds",
        type="int",
        dest="max_idle_seconds",
        default=10 * 60,
        help="Maximum seconds time idle but open transactions are allowed",
    )
    parser.add_option(
        "-q",
        "--quiet",
        action="store_true",
        dest="quiet",
        default=False,
        help="Silence output",
    )
    parser.add_option(
        "-n",
        "--dry-run",
        action="store_true",
        default=False,
        dest="dryrun",
        help="Dry run - don't kill anything",
    )
    parser.add_option(
        "-i",
        "--ignore",
        action="append",
        dest="ignore",
        help="Ignore connections by USER",
        metavar="USER",
    )
    options, args = parser.parse_args()
    if len(args) > 0:
        parser.error("Too many arguments")

    ignore_sql = " AND %s NOT IN (usename, application_name)" * len(
        options.ignore or []
    )

    con = psycopg2.connect(options.connect_string)
    cur = con.cursor()
    cur.execute(
        """
        SELECT
            usename, application_name, datname, pid,
            backend_start, state_change, AGE(NOW(), state_change) AS age
        FROM pg_stat_activity
        WHERE
            pid <> pg_backend_pid()
            AND state = 'idle in transaction'
            AND state_change < CURRENT_TIMESTAMP - '%d seconds'::interval
            %s
        ORDER BY age
        """
        % (options.max_idle_seconds, ignore_sql),
        options.ignore,
    )

    rows = cur.fetchall()

    if len(rows) == 0:
        if not options.quiet:
            print("No IDLE transactions to kill")
        return 0

    for usename, appname, datname, pid, backend, state, age in rows:
        print(80 * "=")
        print("Killing %s(%d) %s from %s:" % (usename, pid, appname, datname))
        print("    backend start: %s" % (backend,))
        print("    idle start:    %s" % (state,))
        print("    age:           %s" % (age,))
        if not options.dryrun:
            cur.execute("SELECT pg_terminate_backend(%s)", (pid,))
    cur.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
