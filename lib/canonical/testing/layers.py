# Copyright 2006 Canonical Ltd.  All rights reserved.

"""Layers used by Canonical tests.

Layers are the mechanism used by the Zope3 test runner to efficiently
provide environments for tests and are documented in the lib/zope/testing.

Note that every Layer should define all of setUp, tearDown, testSetUp
and testTearDown. If you don't do this, a base classes method will be called
instead probably breaking something.

TODO: Make the Zope3 test runner handle multiple layers per test instead
of one, forcing us to attempt to make some sort of layer tree.
-- StuartBishop 20060619
"""

__all__ = [
    'Database', 'Librarian', 'Functional', 'Zopeless',
    'LaunchpadFunctional', 'LaunchpadZopeless', 'PageTest',
    ]

from urllib import urlopen
import transaction
from zope.component import getUtility

from canonical.librarian.ftests.harness import LibrarianTestSetup
from canonical.launchpad.scripts import execute_zcml_for_scripts
from canonical.testing import reset_logging
from canonical.config import config
from canonical.launchpad.scripts import execute_zcml_for_scripts
import canonical.launchpad.mail.stub

class Base:
    @classmethod
    def setUp(cls):
        pass

    @classmethod
    def tearDown(cls):
        pass

    @classmethod
    def testSetUp(cls):
        pass

    @classmethod
    def testTearDown(cls):
        reset_logging()
        del canonical.launchpad.mail.stub.test_emails[:]


class Librarian(Base):
    """Provides tests access to a Librarian instance.

    Calls to the Librarian will fail unless there is also a Launchpad
    database available.
    """
    _reset_between_tests = True
    @classmethod
    def setUp(cls):
        LibrarianTestSetup().setUp()

    @classmethod
    def tearDown(cls):
        LibrarianTestSetup().tearDown()

    @classmethod
    def testSetUp(cls):
        # Confirm that the Librarian hasn't been killed!
        f = urlopen(config.librarian.download_url)
        f.read()
        if Librarian._reset_between_tests:
            LibrarianTestSetup().clear()

    @classmethod
    def testTearDown(cls):
        # Confirm that the test hasn't killed the Librarian
        f = urlopen(config.librarian.download_url)
        f.read()
        if Librarian._reset_between_tests:
            LibrarianTestSetup().clear()


class Database(Base):
    """This Layer provides tests access to the Launchpad sample database."""
    _reset_between_tests = True

    @classmethod
    def setUp(cls):
        cls.force_dirty_database()

    @classmethod
    def tearDown(cls):
        from canonical.launchpad.ftests.harness import LaunchpadTestSetup
        LaunchpadTestSetup().tearDown()

    @classmethod
    def testSetUp(cls):
        from canonical.launchpad.ftests.harness import LaunchpadTestSetup
        if Database._reset_between_tests:
            LaunchpadTestSetup().setUp()
        # Ensure that the database is connectable
        con = Database.connect()
        con.close()

    @classmethod
    def testTearDown(cls):
        # Ensure that the database is connectable
        con = Database.connect()
        con.close()
        from canonical.launchpad.ftests.harness import LaunchpadTestSetup
        if Database._reset_between_tests:
            LaunchpadTestSetup().tearDown()

    @classmethod
    def force_dirty_database(cls):
        from canonical.launchpad.ftests.harness import LaunchpadTestSetup
        LaunchpadTestSetup().force_dirty_database()

    @classmethod
    def connect(cls):
        from canonical.launchpad.ftests.harness import LaunchpadTestSetup
        return LaunchpadTestSetup().connect()


class SQLOS(Base):
    """Maintains the SQLOS connection.

    This Layer is not useful by itself, but it intended to be used as
    a mixin to the Functional and Zopeless Layers.
    """
    @classmethod
    def setUp(cls):
        pass

    @classmethod
    def tearDown(cls):
        pass

    @classmethod
    def testSetUp(cls):
        from canonical.launchpad.ftests.harness import _reconnect_sqlos
        _reconnect_sqlos()

    @classmethod
    def testTearDown(cls):
        from canonical.launchpad.ftests.harness import _disconnect_sqlos
        _disconnect_sqlos()


class Launchpad(Database, Librarian):
    """Provides access to the Launchpad database and daemons.
    
    We need to ensure that the database setup runs before the daemon
    setup, or the database setup will fail because the daemons are
    already connected to the database.
    """
    @classmethod
    def setUp(cls):
        pass

    @classmethod
    def tearDown(cls):
        pass

    @classmethod
    def testSetUp(cls):
        pass

    @classmethod
    def testTearDown(cls):
        pass


class Functional(Base):
    """Loads the Zope3 component architecture in appserver mode."""
    @classmethod
    def setUp(cls):
        from canonical.functional import FunctionalTestSetup
        FunctionalTestSetup().setUp()

    @classmethod
    def tearDown(cls):
        raise NotImplementedError

    @classmethod
    def testSetUp(cls):
        pass

    @classmethod
    def testTearDown(cls):
        transaction.abort()


class Zopeless(Database, Librarian):
    """For Zopeless tests that call initZopeless themselves."""
    @classmethod
    def setUp(cls):
        pass

    @classmethod
    def tearDown(cls):
        raise NotImplementedError

    @classmethod
    def testSetUp(cls):
        pass

    @classmethod
    def testTearDown(cls):
        pass


class ZopelessCA(Zopeless):
    """Zopeless plus the component architecture"""
    @classmethod
    def setUp(cls):
        execute_zcml_for_scripts()

    @classmethod
    def tearDown(cls):
        raise NotImplementedError

    @classmethod
    def testSetUp(cls):
        pass

    @classmethod
    def testTearDown(cls):
        pass


class LaunchpadFunctional(Database, Librarian, Functional, SQLOS):
    """Provides the Launchpad Zope3 application server environment."""
    @classmethod
    def setUp(cls):
        pass

    @classmethod
    def tearDown(cls):
        pass

    @classmethod
    def testSetUp(cls):
        pass

    @classmethod
    def testTearDown(cls):
        from canonical.launchpad.interfaces import IOpenLaunchBag
        getUtility(IOpenLaunchBag).clear()


class LaunchpadZopeless(Database, Librarian, SQLOS):
    """Provides the Launchpad Zopeless environment."""
    @classmethod
    def setUp(cls):
        execute_zcml_for_scripts()

    @classmethod
    def tearDown(cls):
        raise NotImplementedError

    @classmethod
    def testSetUp(cls):
        from canonical.lp import initZopeless
        from canonical.database.sqlbase import ZopelessTransactionManager
        from canonical.launchpad.ftests.harness import (
                LaunchpadZopelessTestSetup
                )
        assert ZopelessTransactionManager._installed is None, \
                'Last test using Zopeless failed to tearDown correctly'
        LaunchpadZopelessTestSetup.txn = initZopeless()

    @classmethod
    def testTearDown(cls):
        from canonical.database.sqlbase import ZopelessTransactionManager
        from canonical.launchpad.ftests.harness import (
                LaunchpadZopelessTestSetup
                )
        LaunchpadZopelessTestSetup.txn.abort()
        LaunchpadZopelessTestSetup.txn.uninstall()
        assert ZopelessTransactionManager._installed is None, \
                'Failed to tearDown Zopeless correctly'


class PageTest(LaunchpadFunctional):
    """Environment for page tests.
    """
    @classmethod
    def resetBetweenTests(cls, flag):
        Librarian._reset_between_tests = flag
        Database._reset_between_tests = flag

    @classmethod
    def setUp(cls):
        cls.resetBetweenTests(True)

    @classmethod
    def tearDown(cls):
        cls.resetBetweenTests(True)

    @classmethod
    def startStory(cls):
        cls.resetBetweenTests(False)

    @classmethod
    def endStory(cls):
        from canonical.launchpad.ftests.harness import LaunchpadTestSetup
        LaunchpadTestSetup().force_dirty_database()
        cls.resetBetweenTests(True)

    @classmethod
    def testSetUp(cls):
        pass

    @classmethod
    def testTearDown(cls):
        pass

