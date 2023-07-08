# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from psycopg2.errors import InsufficientPrivilege
from psycopg2.extensions import parse_dsn
from zope.component import getUtility

from lp.services.config import dbconfig
from lp.services.database.interfaces import (
    MAIN_STORE,
    PRIMARY_FLAVOR,
    IStoreSelector,
)
from lp.services.database.sqlbase import disconnect_stores
from lp.testing import TestCase
from lp.testing.layers import DatabaseFunctionalLayer, DatabaseLayer


class TestLaunchpadDatabase(TestCase):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.addCleanup(dbconfig.reset)

    def assertCurrentUser(self, store, user):
        self.assertEqual(
            user, store.execute("SELECT current_user").get_one()[0]
        )

    def test_refuses_connstring_with_user(self):
        connstr = "dbname=%s user=foo" % DatabaseLayer._db_fixture.dbname
        dbconfig.override(rw_main_primary=connstr)
        disconnect_stores()
        self.assertRaisesWithContent(
            AssertionError,
            "Database username must not be specified in connection string "
            "(%s)." % connstr,
            getUtility(IStoreSelector).get,
            MAIN_STORE,
            PRIMARY_FLAVOR,
        )

    def test_refuses_connstring_uri_with_user(self):
        connstr = "postgresql://foo@/%s" % DatabaseLayer._db_fixture.dbname
        dbconfig.override(rw_main_primary=connstr)
        disconnect_stores()
        self.assertRaisesWithContent(
            AssertionError,
            "Database username must not be specified in connection string "
            "(%s)." % connstr,
            getUtility(IStoreSelector).get,
            MAIN_STORE,
            PRIMARY_FLAVOR,
        )

    def test_accepts_connstring_without_user(self):
        connstr = "dbname=%s" % DatabaseLayer._db_fixture.dbname
        dbconfig.override(rw_main_primary=connstr, dbuser="ro")
        disconnect_stores()
        store = getUtility(IStoreSelector).get(MAIN_STORE, PRIMARY_FLAVOR)
        self.assertEqual(
            {"dbname": DatabaseLayer._db_fixture.dbname, "user": "ro"},
            parse_dsn(store.get_database()._dsn),
        )
        self.assertCurrentUser(store, "ro")

    def test_accepts_connstring_uri_without_user(self):
        connstr = "postgresql:///%s" % DatabaseLayer._db_fixture.dbname
        dbconfig.override(rw_main_primary=connstr, dbuser="ro")
        disconnect_stores()
        store = getUtility(IStoreSelector).get(MAIN_STORE, PRIMARY_FLAVOR)
        self.assertEqual(
            {"dbname": DatabaseLayer._db_fixture.dbname, "user": "ro"},
            parse_dsn(store.get_database()._dsn),
        )
        self.assertCurrentUser(store, "ro")

    def test_set_role_after_connecting_refuses_connstring_without_user(self):
        connstr = "dbname=%s" % DatabaseLayer._db_fixture.dbname
        dbconfig.override(
            set_role_after_connecting=True,
            rw_main_primary=connstr,
            dbuser="read",
        )
        disconnect_stores()
        self.assertRaisesWithContent(
            AssertionError,
            "With set_role_after_connecting, database username must be "
            "specified in connection string (%s)." % connstr,
            getUtility(IStoreSelector).get,
            MAIN_STORE,
            PRIMARY_FLAVOR,
        )

    def test_set_role_after_connecting_refuses_connstring_uri_without_user(
        self,
    ):
        connstr = "postgresql:///%s" % DatabaseLayer._db_fixture.dbname
        dbconfig.override(
            set_role_after_connecting=True,
            rw_main_primary=connstr,
            dbuser="read",
        )
        disconnect_stores()
        self.assertRaisesWithContent(
            AssertionError,
            "With set_role_after_connecting, database username must be "
            "specified in connection string (%s)." % connstr,
            getUtility(IStoreSelector).get,
            MAIN_STORE,
            PRIMARY_FLAVOR,
        )

    def test_set_role_after_connecting_accepts_connstring_with_user(self):
        connstr = "dbname=%s user=ro" % DatabaseLayer._db_fixture.dbname
        dbconfig.override(
            set_role_after_connecting=True,
            rw_main_primary=connstr,
            dbuser="read",
        )
        disconnect_stores()
        store = getUtility(IStoreSelector).get(MAIN_STORE, PRIMARY_FLAVOR)
        self.assertEqual(
            {"dbname": DatabaseLayer._db_fixture.dbname, "user": "ro"},
            parse_dsn(store.get_database()._dsn),
        )
        self.assertCurrentUser(store, "read")

    def test_set_role_after_connecting_accepts_connstring_uri_with_user(self):
        connstr = "postgresql://ro@/%s" % DatabaseLayer._db_fixture.dbname
        dbconfig.override(
            set_role_after_connecting=True,
            rw_main_primary=connstr,
            dbuser="read",
        )
        disconnect_stores()
        store = getUtility(IStoreSelector).get(MAIN_STORE, PRIMARY_FLAVOR)
        self.assertEqual(
            {"dbname": DatabaseLayer._db_fixture.dbname, "user": "ro"},
            parse_dsn(store.get_database()._dsn),
        )
        self.assertCurrentUser(store, "read")

    def test_set_role_after_connecting_not_member(self):
        connstr = "dbname=%s user=ro" % DatabaseLayer._db_fixture.dbname
        dbconfig.override(
            set_role_after_connecting=True,
            rw_main_primary=connstr,
            dbuser="launchpad_main",
        )
        disconnect_stores()
        self.assertRaises(
            InsufficientPrivilege,
            getUtility(IStoreSelector).get,
            MAIN_STORE,
            PRIMARY_FLAVOR,
        )
