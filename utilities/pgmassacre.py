#!/usr/bin/python3 -S
#
# Copyright 2009-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# This file is mirrored into lp:losa-db-scripts, so please keep that
# version in sync with the master in the Launchpad tree.

"""
dropdb only more so.

Cut off access, slaughter connections and burn the database to the ground
(but do nothing that could put the system into recovery mode).
"""

import _pythonpath  # noqa: F401

import os
import sys
import time
from optparse import OptionParser

import psycopg2
from psycopg2.extensions import make_dsn, parse_dsn

from lp.services.config import config, dbconfig


def connect(dbname="template1"):
    """Connect to the database, returning the DB-API connection."""
    parsed_dsn = parse_dsn(dbconfig.rw_main_primary)
    if options.user is not None:
        parsed_dsn["user"] = options.user
    # For database administration, we only pass a username if we're
    # connecting over TCP.
    elif "host" not in parsed_dsn:
        parsed_dsn.pop("user", None)
    parsed_dsn["dbname"] = dbname
    return psycopg2.connect(make_dsn(**parsed_dsn))


def rollback_prepared_transactions(database):
    """Rollback any prepared transactions.

    PostgreSQL will refuse to drop a database with outstanding prepared
    transactions.
    """
    con = connect(database)
    con.set_isolation_level(0)  # Autocommit so we can ROLLBACK PREPARED.
    cur = con.cursor()

    # Get a list of outstanding prepared transactions.
    cur.execute(
        "SELECT gid FROM pg_prepared_xacts WHERE database=%(database)s", vars()
    )
    xids = [row[0] for row in cur.fetchall()]
    for xid in xids:
        cur.execute("ROLLBACK PREPARED %(xid)s", {"xid": xid})
    con.close()


def still_open(database, max_wait=120):
    """Return True if there are still open connections, apart from our own.

    Waits a while to ensure that connections shutting down have a chance
    to. This might take a while if there is a big transaction to
    rollback.
    """
    con = connect()
    con.set_isolation_level(0)  # Autocommit.
    cur = con.cursor()
    # Keep checking until the timeout is reached, returning True if all
    # of the backends are gone.
    start = time.time()
    while time.time() < start + max_wait:
        cur.execute(
            """
            SELECT TRUE FROM pg_stat_activity
            WHERE
                datname=%s
                AND pid != pg_backend_pid()
            LIMIT 1
            """,
            [database],
        )
        if cur.fetchone() is None:
            return False
        time.sleep(0.6)  # Stats only updated every 500ms.
    con.close()
    return True


def massacre(database):
    con = connect()
    con.set_isolation_level(0)  # Autocommit
    cur = con.cursor()

    # Allow connections to the doomed database if something turned this off,
    # such as an aborted run of this script.
    cur.execute(
        "UPDATE pg_database SET datallowconn=TRUE WHERE datname=%s", [database]
    )

    # Rollback prepared transactions.
    rollback_prepared_transactions(database)

    try:
        # Stop connections to the doomed database.
        cur.execute(
            "UPDATE pg_database SET datallowconn=FALSE WHERE datname=%s",
            [database],
        )

        # New connections are disabled, but pg_stat_activity is only
        # updated every 500ms. Ensure that pg_stat_activity has
        # been refreshed to catch any connections that opened
        # immediately before setting datallowconn.
        time.sleep(1)

        # Terminate open connections.
        cur.execute(
            """
            SELECT pid, pg_terminate_backend(pid)
            FROM pg_stat_activity
            WHERE datname=%s AND pid <> pg_backend_pid()
            """,
            [database],
        )
        for pid, success in cur.fetchall():
            if not success:
                print("pg_terminate_backend(%s) failed" % pid, file=sys.stderr)
        con.close()

        if still_open(database):
            print(
                "Unable to kill all backends! Database not destroyed.",
                file=sys.stderr,
            )
            return 9

        # Destroy the database.
        con = connect()
        # AUTOCOMMIT required to execute commands like DROP DATABASE.
        con.set_isolation_level(0)
        cur = con.cursor()
        cur.execute("DROP DATABASE %s" % database)  # Not quoted.
        con.close()
        return 0
    finally:
        # In case something messed up, allow connections again so we can
        # inspect the damage.
        con = connect()
        con.set_isolation_level(0)
        cur = con.cursor()
        cur.execute(
            "UPDATE pg_database SET datallowconn=TRUE WHERE datname=%s",
            [database],
        )
        con.close()


def rebuild(database, template):
    if still_open(template, 20):
        print(
            "Giving up waiting for connections to %s to drop." % template,
            file=sys.stderr,
        )
        report_open_connections(template)
        return 10

    start = time.time()
    now = start
    error_msg = None
    con = connect()
    con.set_isolation_level(0)  # Autocommit required for CREATE DATABASE.
    create_db_cmd = """
        CREATE DATABASE %s WITH ENCODING='UTF8' TEMPLATE=%s
        """ % (
        database,
        template,
    )
    # 8.4 allows us to create empty databases with a different locale
    # to template1 by using the template0 database as a template.
    # We make use of this feature so we don't have to care what locale
    # was used to create the database cluster rather than requiring it
    # to be rebuilt in the C locale.
    if template == "template0":
        create_db_cmd += "LC_COLLATE='C' LC_CTYPE='C'"
    while now < start + 20:
        cur = con.cursor()
        try:
            cur.execute(create_db_cmd)
            con.close()
            return 0
        except psycopg2.Error as exception:
            error_msg = str(exception)
        time.sleep(0.6)  # Stats only updated every 500ms.
        now = time.time()
    con.close()

    print("Unable to recreate database: %s" % error_msg, file=sys.stderr)
    return 11


def report_open_connections(database):
    con = connect()
    cur = con.cursor()
    cur.execute(
        """
        SELECT usename, datname, count(*)
        FROM pg_stat_activity
        WHERE pid != pg_backend_pid()
        GROUP BY usename, datname
        ORDER BY datname, usename
        """
    )
    for usename, datname, num_connections in cur.fetchall():
        print(
            "%d connections by %s to %s" % (num_connections, usename, datname),
            file=sys.stderr,
        )
    con.close()


options = None


def main():
    parser = OptionParser(
        "Usage: %prog [options] DBNAME",
        description=(
            "Set LPCONFIG to choose which database cluster to connect to; "
            "credentials are taken from the database.rw_main_primary "
            "configuration option, ignoring the 'dbname' parameter.  The "
            "default behaviour is to connect to a cluster on the local "
            "machine using PostgreSQL's default port."
        ),
    )
    parser.add_option(
        "-U",
        "--user",
        dest="user",
        default=None,
        help="Connect as USER",
        metavar="USER",
    )
    parser.add_option(
        "-t",
        "--template",
        dest="template",
        default=None,
        help="Recreate database using DBNAME as a template database."
        " If template0, database will be created in the C locale.",
        metavar="DBNAME",
    )
    global options
    (options, args) = parser.parse_args()

    if len(args) != 1:
        parser.error("Must specify one, and only one, database to destroy")

    database = args[0]

    # Don't be stupid protection.
    if database in ("template1", "template0"):
        parser.error(
            "Running this script against template1 or template0 is nuts."
        )
    if (
        "host" in parse_dsn(dbconfig.rw_main_primary)
        and os.environ.get("LP_DESTROY_REMOTE_DATABASE") != "yes"
    ):
        parser.error(
            "For safety, refusing to destroy a remote database.  Set "
            "LP_DESTROY_REMOTE_DATABASE=yes to override this."
        )
    if config.vhost.mainsite.hostname == "launchpad.net":
        parser.error("Flatly refusing to destroy production.")

    con = connect()
    cur = con.cursor()

    # Ensure the template database exists.
    if options.template is not None:
        cur.execute(
            "SELECT TRUE FROM pg_database WHERE datname=%s", [options.template]
        )
        if cur.fetchone() is None:
            parser.error(
                "Template database %s does not exist." % options.template
            )
    # If the database doesn't exist, no point attempting to drop it.
    cur.execute("SELECT TRUE FROM pg_database WHERE datname=%s", [database])
    db_exists = cur.fetchone() is not None
    con.close()

    if db_exists:
        rv = massacre(database)
        if rv != 0:
            print("Fail %d" % rv, file=sys.stderr)
            return rv

    if options.template is not None:
        return rebuild(database, options.template)
    else:
        return 0


if __name__ == "__main__":
    sys.exit(main())
