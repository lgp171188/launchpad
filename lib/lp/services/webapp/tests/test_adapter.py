# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

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

    def test_refuses_connection_string_with_user(self):
        self.addCleanup(dbconfig.reset)
        connstr = "dbname=%s user=foo" % DatabaseLayer._db_fixture.dbname
        dbconfig.override(rw_main_primary=connstr)
        disconnect_stores()
        self.assertRaisesWithContent(
            AssertionError,
            "Database username should not be specified in connection string "
            "(%s)." % connstr,
            getUtility(IStoreSelector).get,
            MAIN_STORE,
            PRIMARY_FLAVOR,
        )

    def test_refuses_connection_string_uri_with_user(self):
        self.addCleanup(dbconfig.reset)
        connstr = "postgresql://foo@/%s" % DatabaseLayer._db_fixture.dbname
        dbconfig.override(rw_main_primary=connstr)
        disconnect_stores()
        self.assertRaisesWithContent(
            AssertionError,
            "Database username should not be specified in connection string "
            "(%s)." % connstr,
            getUtility(IStoreSelector).get,
            MAIN_STORE,
            PRIMARY_FLAVOR,
        )

    def test_accepts_connection_string_without_user(self):
        self.addCleanup(dbconfig.reset)
        connstr = "dbname=%s" % DatabaseLayer._db_fixture.dbname
        dbconfig.override(rw_main_primary=connstr, dbuser="ro")
        disconnect_stores()
        store = getUtility(IStoreSelector).get(MAIN_STORE, PRIMARY_FLAVOR)
        self.assertEqual(
            {"dbname": DatabaseLayer._db_fixture.dbname, "user": "ro"},
            parse_dsn(store.get_database()._dsn),
        )

    def test_accepts_connection_string_uri_without_user(self):
        self.addCleanup(dbconfig.reset)
        connstr = "postgresql:///%s" % DatabaseLayer._db_fixture.dbname
        dbconfig.override(rw_main_primary=connstr, dbuser="ro")
        disconnect_stores()
        store = getUtility(IStoreSelector).get(MAIN_STORE, PRIMARY_FLAVOR)
        self.assertEqual(
            {"dbname": DatabaseLayer._db_fixture.dbname, "user": "ro"},
            parse_dsn(store.get_database()._dsn),
        )
