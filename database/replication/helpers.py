# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Common helpers for replication scripts."""

__all__ = []

import psycopg2

from lp.services.database.sqlbase import ISOLATION_LEVEL_DEFAULT


class Node:
    """Simple data structure for holding information about a Slony node."""

    def __init__(self, node_id, nickname, connection_string, is_primary):
        self.node_id = node_id
        self.nickname = nickname
        self.connection_string = connection_string
        self.is_primary = is_primary

    def connect(self, isolation=ISOLATION_LEVEL_DEFAULT):
        con = psycopg2.connect(str(self.connection_string))
        con.set_isolation_level(isolation)
        return con
