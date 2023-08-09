#!/usr/bin/python3 -S
#
# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Kill transactions that have hung around for too long."""

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
        "--max-seconds",
        type="int",
        dest="max_seconds",
        default=60 * 60,
        help=(
            "Connections with a transaction older than MAX_SECONDS seconds "
            "will be killed. If 0, all matched connections will be killed."
        ),
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
        dest="dry_run",
        help="Dry run - don't kill anything",
    )
    parser.add_option(
        "-u",
        "--user",
        action="append",
        dest="users",
        help="Kill connection of users matching REGEXP",
        metavar="REGEXP",
    )
    options, args = parser.parse_args()
    if len(args) > 0:
        parser.error("Too many arguments")
    if not options.users:
        parser.error("--user is required")

    user_match_sql = "AND (%s)" % " OR ".join(
        ["usename ~* %s"] * len(options.users)
    )

    con = psycopg2.connect(options.connect_string)
    cur = con.cursor()
    cur.execute(
        """
        SELECT usename, pid, backend_start, xact_start
        FROM pg_stat_activity
        WHERE
            pid <> pg_backend_pid()
            AND xact_start < CURRENT_TIMESTAMP - '%d seconds'::interval
            %s
        ORDER BY pid
        """
        % (options.max_seconds, user_match_sql),
        options.users,
    )

    rows = list(cur.fetchall())

    if len(rows) == 0:
        if not options.quiet:
            print("No transactions to kill")
        return 0

    for usename, pid, backend_start, transaction_start in rows:
        print(
            "Killing %s (%d), %s, %s"
            % (
                usename,
                pid,
                backend_start,
                transaction_start,
            )
        )
        if not options.dry_run:
            cur.execute("SELECT pg_terminate_backend(%s)", (pid,))
    cur.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
