#!/usr/bin/python3 -S
#
# Copyright 2009-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Disable autovacuum on all tables in the database and kill off
any autovacuum processes.

We run this script on databases we require to be totally inactive with
no open connections, such as the template databases we clone. If not
disabled, autovacuum processes sometimes run and break our scripts.

Don't run this on any production systems.
"""

__all__ = []

import _pythonpath  # noqa: F401

import sys
import time
from optparse import OptionParser

from lp.services.database.sqlbase import ISOLATION_LEVEL_AUTOCOMMIT, connect
from lp.services.scripts import db_options, logger, logger_options


def main():
    parser = OptionParser()
    logger_options(parser)
    db_options(parser)

    options, args = parser.parse_args()

    if len(args) > 0:
        parser.error("Too many arguments.")

    log = logger(options)

    log.debug("Connecting")
    con = connect()
    con.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = con.cursor()

    log.debug("Disabling autovacuum on all tables in the database.")
    cur.execute(
        """
        SELECT nspname,relname
        FROM pg_namespace, pg_class
        WHERE relnamespace = pg_namespace.oid
            AND relkind = 'r' AND nspname <> 'pg_catalog'
        """
    )
    for namespace, table in list(cur.fetchall()):
        cur.execute(
            """
            ALTER TABLE ONLY "%s"."%s" SET (
                autovacuum_enabled=false,
                toast.autovacuum_enabled=false)
            """
            % (namespace, table)
        )

    log.debug("Killing existing autovacuum processes")
    num_autovacuums = -1
    while num_autovacuums != 0:
        # Sleep long enough for pg_stat_activity to be updated.
        time.sleep(0.6)
        cur.execute(
            """
            SELECT pid FROM pg_stat_activity
            WHERE
                datname=current_database()
                AND query LIKE 'autovacuum: %'
            """
        )
        autovacuums = [row[0] for row in cur.fetchall()]
        num_autovacuums = len(autovacuums)
        for pid in autovacuums:
            log.debug("Cancelling %d" % pid)
            cur.execute("SELECT pg_cancel_backend(%d)" % pid)


if __name__ == "__main__":
    sys.exit(main())
