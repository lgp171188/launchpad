# Copyright 2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Session tests."""

from lp.services.database.interfaces import (
    IMasterStore,
    IStandbyStore,
    IStore,
    )
from lp.services.session.model import (
    SessionData,
    SessionPkgData,
    )
from lp.testing import TestCase
from lp.testing.layers import DatabaseFunctionalLayer


class TestSessionModelAdapters(TestCase):
    layer = DatabaseFunctionalLayer

    def test_adapters(self):
        for adapter in [IMasterStore, IStandbyStore, IStore]:
            for cls in [SessionData, SessionPkgData]:
                for obj in [cls, cls()]:
                    store = adapter(obj)
                    self.assertTrue(
                        'session' in store.get_database()._dsn,
                        'Unknown store returned adapting %r to %r'
                        % (obj, adapter))
