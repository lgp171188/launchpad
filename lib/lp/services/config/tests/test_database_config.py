# Copyright 2010-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from lp.services.config import DatabaseConfig
from lp.services.propertycache import get_property_cache
from lp.testing import TestCase
from lp.testing.layers import DatabaseLayer


class TestDatabaseConfig(TestCase):
    layer = DatabaseLayer

    def test_override(self):
        # dbuser and isolation_level can be overridden at runtime.
        dbc = DatabaseConfig()
        self.assertEqual("launchpad_main", dbc.dbuser)
        self.assertEqual("repeatable_read", dbc.isolation_level)

        # dbuser and isolation_level overrides both work.
        dbc.override(dbuser="not_launchpad", isolation_level="autocommit")
        self.assertEqual("not_launchpad", dbc.dbuser)
        self.assertEqual("autocommit", dbc.isolation_level)

        # Overriding dbuser again preserves the isolation_level override.
        dbc.override(dbuser="also_not_launchpad")
        self.assertEqual("also_not_launchpad", dbc.dbuser)
        self.assertEqual("autocommit", dbc.isolation_level)

        # Overriding with None removes the override.
        dbc.override(dbuser=None, isolation_level=None)
        self.assertEqual("launchpad_main", dbc.dbuser)
        self.assertEqual("repeatable_read", dbc.isolation_level)

    def test_reset(self):
        # reset() removes any overrides.
        dbc = DatabaseConfig()
        self.assertEqual("launchpad_main", dbc.dbuser)
        dbc.override(dbuser="not_launchpad")
        self.assertEqual("not_launchpad", dbc.dbuser)
        dbc.reset()
        self.assertEqual("launchpad_main", dbc.dbuser)

    def test_main_standby(self):
        # If rw_main_standby is a comma-separated list, then the
        # main_standby property selects among them randomly, and caches the
        # result.
        dbc = DatabaseConfig()
        original_standby = dbc.main_standby
        standbys = [
            "dbname=launchpad_standby1 port=5433",
            "dbname=launchpad_standby2 port=5433",
        ]
        dbc.override(rw_main_standby=",".join(standbys))
        selected_standby = dbc.main_standby
        self.assertIn(selected_standby, standbys)
        self.assertEqual(
            selected_standby, get_property_cache(dbc).main_standby
        )
        dbc.reset()
        self.assertEqual(original_standby, dbc.main_standby)
