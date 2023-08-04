# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import doctest
import unittest
from doctest import ELLIPSIS, NORMALIZE_WHITESPACE, REPORT_NDIFF
from typing import Tuple

from psycopg2.errors import InsufficientPrivilege
from psycopg2.extensions import connection, parse_dsn

from lp.services.config import config, dbconfig
from lp.services.database import sqlbase
from lp.testing import TestCase
from lp.testing.layers import DatabaseLayer, ZopelessDatabaseLayer


class TestConnect(TestCase):
    layer = ZopelessDatabaseLayer

    @staticmethod
    def examineConnection(con: connection) -> Tuple[str, str, str]:
        with con.cursor() as cur:
            cur.execute("SHOW session_authorization")
            who = cur.fetchone()[0]
            cur.execute("SELECT current_database()")
            where = cur.fetchone()[0]
            cur.execute("SHOW transaction_isolation")
            how = cur.fetchone()[0]
        return (who, where, how)

    def test_honours_user(self):
        con = sqlbase.connect(user=config.launchpad_session.dbuser)
        who, _, how = self.examineConnection(con)
        self.assertEqual(("session", "read committed"), (who, how))

    def test_honours_dbname(self):
        con = sqlbase.connect(
            user=config.launchpad.dbuser, dbname="launchpad_empty"
        )
        self.assertEqual(
            ("launchpad_main", "launchpad_empty", "read committed"),
            self.examineConnection(con),
        )

    def test_honours_isolation(self):
        con = sqlbase.connect(
            user=config.launchpad.dbuser,
            isolation=sqlbase.ISOLATION_LEVEL_SERIALIZABLE,
        )
        who, _, how = self.examineConnection(con)
        self.assertEqual(("launchpad_main", "serializable"), (who, how))

    def assertCurrentUser(self, con: connection, user: str) -> None:
        with con.cursor() as cur:
            cur.execute("SELECT current_user")
            self.assertEqual(user, cur.fetchone()[0])
        # Ensure that the role is set for the whole session, not just the
        # current transaction.
        con.rollback()
        with con.cursor() as cur:
            cur.execute("SELECT current_user")
            self.assertEqual(user, cur.fetchone()[0])

    def test_refuses_connstring_with_user(self):
        connstr = "dbname=%s user=foo" % DatabaseLayer._db_fixture.dbname
        dbconfig.override(rw_main_primary=connstr)
        self.assertRaisesWithContent(
            AssertionError,
            "Database username must not be specified in connection string "
            "(%s)." % connstr,
            sqlbase.connect,
        )

    def test_refuses_connstring_uri_with_user(self):
        connstr = "postgresql://foo@/%s" % DatabaseLayer._db_fixture.dbname
        dbconfig.override(rw_main_primary=connstr)
        self.assertRaisesWithContent(
            AssertionError,
            "Database username must not be specified in connection string "
            "(%s)." % connstr,
            sqlbase.connect,
        )

    def test_accepts_connstring_without_user(self):
        connstr = "dbname=%s" % DatabaseLayer._db_fixture.dbname
        dbconfig.override(rw_main_primary=connstr)
        con = sqlbase.connect(user="ro")
        self.assertEqual(
            {"dbname": DatabaseLayer._db_fixture.dbname, "user": "ro"},
            parse_dsn(con.dsn),
        )
        self.assertCurrentUser(con, "ro")

    def test_accepts_connstring_uri_without_user(self):
        connstr = "postgresql:///%s" % DatabaseLayer._db_fixture.dbname
        dbconfig.override(rw_main_primary=connstr)
        con = sqlbase.connect(user="ro")
        self.assertEqual(
            {"dbname": DatabaseLayer._db_fixture.dbname, "user": "ro"},
            parse_dsn(con.dsn),
        )
        self.assertCurrentUser(con, "ro")

    def test_set_role_after_connecting_refuses_connstring_without_user(self):
        connstr = "dbname=%s" % DatabaseLayer._db_fixture.dbname
        dbconfig.override(
            set_role_after_connecting=True, rw_main_primary=connstr
        )
        self.assertRaisesWithContent(
            AssertionError,
            "With set_role_after_connecting, database username must be "
            "specified in connection string (%s)." % connstr,
            sqlbase.connect,
            user="read",
        )

    def test_set_role_after_connecting_refuses_connstring_uri_without_user(
        self,
    ):
        connstr = "postgresql:///%s" % DatabaseLayer._db_fixture.dbname
        dbconfig.override(
            set_role_after_connecting=True, rw_main_primary=connstr
        )
        self.assertRaisesWithContent(
            AssertionError,
            "With set_role_after_connecting, database username must be "
            "specified in connection string (%s)." % connstr,
            sqlbase.connect,
            user="read",
        )

    def test_set_role_after_connecting_accepts_connstring_with_user(self):
        connstr = "dbname=%s user=ro" % DatabaseLayer._db_fixture.dbname
        dbconfig.override(
            set_role_after_connecting=True, rw_main_primary=connstr
        )
        con = sqlbase.connect(user="read")
        self.assertEqual(
            {"dbname": DatabaseLayer._db_fixture.dbname, "user": "ro"},
            parse_dsn(con.dsn),
        )
        self.assertCurrentUser(con, "read")

    def test_set_role_after_connecting_accepts_connstring_uri_with_user(self):
        connstr = "postgresql://ro@/%s" % DatabaseLayer._db_fixture.dbname
        dbconfig.override(
            set_role_after_connecting=True, rw_main_primary=connstr
        )
        con = sqlbase.connect(user="read")
        self.assertEqual(
            {"dbname": DatabaseLayer._db_fixture.dbname, "user": "ro"},
            parse_dsn(con.dsn),
        )
        self.assertCurrentUser(con, "read")

    def test_set_role_after_connecting_not_member(self):
        connstr = "dbname=%s user=ro" % DatabaseLayer._db_fixture.dbname
        dbconfig.override(
            set_role_after_connecting=True, rw_main_primary=connstr
        )
        self.assertRaises(
            InsufficientPrivilege, sqlbase.connect, user="launchpad_main"
        )


def test_suite():
    suite = unittest.TestSuite()
    loader = unittest.TestLoader()
    suite.addTest(loader.loadTestsFromTestCase(TestConnect))
    optionflags = ELLIPSIS | NORMALIZE_WHITESPACE | REPORT_NDIFF
    suite.addTest(doctest.DocTestSuite(sqlbase, optionflags=optionflags))
    return suite
