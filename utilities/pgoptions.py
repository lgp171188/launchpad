#!/usr/bin/python3 -S
#
# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""
Print PostgreSQL connection options matching the current Launchpad primary
database configuration.

To avoid leaking information via process command lines, any password in the
configured connection string is ignored; passwords should be set in
~/.pgpass instead.
"""

import _pythonpath  # noqa: F401

from optparse import OptionParser

from psycopg2.extensions import parse_dsn

from lp.services.config import dbconfig

if __name__ == "__main__":
    parser = OptionParser()
    _, args = parser.parse_args()
    if args:
        parser.error("Too many options given")
    parsed_dsn = parse_dsn(dbconfig.rw_main_primary)
    conn_opts = []
    if "host" in parsed_dsn:
        conn_opts.append("--host=%s" % parsed_dsn["host"])
    if "port" in parsed_dsn:
        conn_opts.append("--port=%s" % parsed_dsn["port"])
    # For database administration, we only pass a username if we're
    # connecting over TCP.
    if "host" in parsed_dsn and "user" in parsed_dsn:
        conn_opts.append("--username=%s" % parsed_dsn["user"])
    print(" ".join(conn_opts))
