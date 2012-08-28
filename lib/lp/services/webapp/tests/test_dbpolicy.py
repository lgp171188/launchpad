# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the DBPolicy."""

__metaclass__ = type
__all__ = []

from textwrap import dedent

from fixtures import Fixture
from lazr.restful.interfaces import IWebServiceConfiguration
from storm.exceptions import DisconnectionError
import transaction
from zope.component import (
    getAdapter,
    getUtility,
    )
from zope.publisher.interfaces.xmlrpc import IXMLRPCRequest
from zope.security.management import (
    endInteraction,
    newInteraction,
    )
from zope.session.interfaces import (
    IClientIdManager,
    ISession,
    )

from lp.layers import (
    FeedsLayer,
    setFirstLayer,
    WebServiceLayer,
    )
from lp.registry.model.person import Person
from lp.services.config import config
from lp.services.database.lpstorm import (
    IMasterStore,
    ISlaveStore,
    )
from lp.services.webapp.dbpolicy import (
    BaseDatabasePolicy,
    LaunchpadDatabasePolicy,
    MasterDatabasePolicy,
    SlaveDatabasePolicy,
    SlaveOnlyDatabasePolicy,
    )
from lp.services.webapp.interfaces import (
    ALL_STORES,
    DEFAULT_FLAVOR,
    DisallowedStore,
    IDatabasePolicy,
    IStoreSelector,
    MAIN_STORE,
    MASTER_FLAVOR,
    SLAVE_FLAVOR,
    )
from lp.services.webapp.servers import LaunchpadTestRequest
from lp.testing import TestCase
from lp.testing.fixture import PGBouncerFixture
from lp.testing.layers import (
    DatabaseLayer,
    DatabaseFunctionalLayer,
    FunctionalLayer,
    )


class ImplicitDatabasePolicyTestCase(TestCase):
    """Tests for when there is no policy installed."""
    layer = DatabaseFunctionalLayer

    def test_defaults(self):
        for store in ALL_STORES:
            self.assertProvides(
                getUtility(IStoreSelector).get(store, DEFAULT_FLAVOR),
                IMasterStore)

    def test_dbusers(self):
        store_selector = getUtility(IStoreSelector)
        main_store = store_selector.get(MAIN_STORE, DEFAULT_FLAVOR)
        self.failUnlessEqual(self.getDBUser(main_store), 'launchpad_main')

    def getDBUser(self, store):
        return store.execute(
            'SHOW session_authorization').get_one()[0]


class BaseDatabasePolicyTestCase(ImplicitDatabasePolicyTestCase):
    """Base tests for DatabasePolicy implementation."""

    policy = None

    def setUp(self):
        super(BaseDatabasePolicyTestCase, self).setUp()
        if self.policy is None:
            self.policy = BaseDatabasePolicy()
        getUtility(IStoreSelector).push(self.policy)

    def tearDown(self):
        getUtility(IStoreSelector).pop()
        super(BaseDatabasePolicyTestCase, self).tearDown()

    def test_correctly_implements_IDatabasePolicy(self):
        self.assertProvides(self.policy, IDatabasePolicy)


class SlaveDatabasePolicyTestCase(BaseDatabasePolicyTestCase):
    """Tests for the `SlaveDatabasePolicy`."""

    def setUp(self):
        if self.policy is None:
            self.policy = SlaveDatabasePolicy()
        super(SlaveDatabasePolicyTestCase, self).setUp()

    def test_defaults(self):
        for store in ALL_STORES:
            self.assertProvides(
                getUtility(IStoreSelector).get(store, DEFAULT_FLAVOR),
                ISlaveStore)

    def test_master_allowed(self):
        for store in ALL_STORES:
            self.assertProvides(
                getUtility(IStoreSelector).get(store, MASTER_FLAVOR),
                IMasterStore)


class SlaveOnlyDatabasePolicyTestCase(SlaveDatabasePolicyTestCase):
    """Tests for the `SlaveDatabasePolicy`."""

    def setUp(self):
        self.policy = SlaveOnlyDatabasePolicy()
        super(SlaveOnlyDatabasePolicyTestCase, self).setUp()

    def test_master_allowed(self):
        for store in ALL_STORES:
            self.failUnlessRaises(
                DisallowedStore,
                getUtility(IStoreSelector).get, store, MASTER_FLAVOR)


class MasterDatabasePolicyTestCase(BaseDatabasePolicyTestCase):
    """Tests for the `MasterDatabasePolicy`."""

    def setUp(self):
        self.policy = MasterDatabasePolicy()
        super(MasterDatabasePolicyTestCase, self).setUp()

    def test_XMLRPCRequest_uses_MasterPolicy(self):
        """XMLRPC should always use the master flavor, since they always
        use POST and do not support session cookies.
        """
        request = LaunchpadTestRequest(
            SERVER_URL='http://xmlrpc-private.launchpad.dev')
        setFirstLayer(request, IXMLRPCRequest)
        policy = getAdapter(request, IDatabasePolicy)
        self.failUnless(
            isinstance(policy, MasterDatabasePolicy),
            "Expected MasterDatabasePolicy, not %s." % policy)

    def test_slave_allowed(self):
        # We get the master store even if the slave was requested.
        for store in ALL_STORES:
            self.assertProvides(
                getUtility(IStoreSelector).get(store, SLAVE_FLAVOR),
                ISlaveStore)


class LaunchpadDatabasePolicyTestCase(SlaveDatabasePolicyTestCase):
    """Fuller LaunchpadDatabasePolicy tests are in the page tests.

    This test just checks the defaults, which is the same as the
    slave policy for unauthenticated requests.
    """

    def setUp(self):
        request = LaunchpadTestRequest(SERVER_URL='http://launchpad.dev')
        self.policy = LaunchpadDatabasePolicy(request)
        super(LaunchpadDatabasePolicyTestCase, self).setUp()


class LayerDatabasePolicyTestCase(TestCase):
    layer = FunctionalLayer

    def test_FeedsLayer_uses_SlaveDatabasePolicy(self):
        """FeedsRequest should use the SlaveDatabasePolicy since they
        are read-only in nature. Also we don't want to send session cookies
        over them.
        """
        request = LaunchpadTestRequest(
            SERVER_URL='http://feeds.launchpad.dev')
        setFirstLayer(request, FeedsLayer)
        policy = IDatabasePolicy(request)
        self.assertIsInstance(policy, SlaveOnlyDatabasePolicy)

    def test_WebServiceRequest_uses_MasterDatabasePolicy(self):
        """WebService requests should always use the master flavor, since
        it's likely that clients won't support cookies and thus mixing read
        and write requests will result in incoherent views of the data.

        XXX 20090320 Stuart Bishop bug=297052: This doesn't scale of course
            and will meltdown when the API becomes popular.
        """
        api_prefix = getUtility(
            IWebServiceConfiguration).active_versions[0]
        server_url = 'http://api.launchpad.dev/%s' % api_prefix
        request = LaunchpadTestRequest(SERVER_URL=server_url)
        setFirstLayer(request, WebServiceLayer)
        policy = IDatabasePolicy(request)
        self.assertIsInstance(policy, MasterDatabasePolicy)

    def test_WebServiceRequest_uses_LaunchpadDatabasePolicy(self):
        """WebService requests with a session cookie will use the
        standard LaunchpadDatabasePolicy so their database queries
        can be outsourced to a slave database when possible.
        """
        api_prefix = getUtility(
            IWebServiceConfiguration).active_versions[0]
        server_url = 'http://api.launchpad.dev/%s' % api_prefix
        request = LaunchpadTestRequest(SERVER_URL=server_url)
        newInteraction(request)
        try:
            # First, generate a valid session cookie.
            ISession(request)['whatever']['whatever'] = 'whatever'
            # Then stuff it into the request where we expect to
            # find it. The database policy is only interested if
            # a session cookie was sent with the request, not it
            # one has subsequently been set in the response.
            request._cookies = request.response._cookies
            setFirstLayer(request, WebServiceLayer)
            policy = IDatabasePolicy(request)
            self.assertIsInstance(policy, LaunchpadDatabasePolicy)
        finally:
            endInteraction()

    def test_other_request_uses_LaunchpadDatabasePolicy(self):
        """By default, requests should use the LaunchpadDatabasePolicy."""
        server_url = 'http://launchpad.dev/'
        request = LaunchpadTestRequest(SERVER_URL=server_url)
        policy = IDatabasePolicy(request)
        self.assertIsInstance(policy, LaunchpadDatabasePolicy)


class MasterFallbackTestCase(TestCase):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(MasterFallbackTestCase, self).setUp()

        self.fixture = Fixture()
        self.fixture.setUp()

        self.pgbouncer_fixture = PGBouncerFixture()

        dbname = DatabaseLayer._db_fixture.dbname
        conn_str_direct = self.pgbouncer_fixture.databases[dbname]
        conn_str_pgbouncer = 'dbname=%s host=localhost' % dbname

        # Configure slave connections via pgbouncer, so we can shut them
        # down. Master connections direct so they are unaffected.
        config_key = 'master-slave-separation'
        config.push(config_key, dedent('''\
            [database]
            rw_main_master: %s
            rw_main_slave: %s
            ''' % (conn_str_direct, conn_str_pgbouncer)))
        self.addCleanup(lambda: config.pop(config_key))

        self.fixture.useFixture(self.pgbouncer_fixture)

    def tearDown(self):
        self.pgbouncer_fixture = None
        self.fixture.cleanUp()
        super(MasterFallbackTestCase, self).tearDown()

    def test_can_shutdown_slave_only(self):
        '''Confirm that this TestCase's test infrastructure works as needed.
        '''
        master_store = IMasterStore(Person)
        slave_store = ISlaveStore(Person)

        # Both Stores work when pgbouncer is up.
        master_store.get(Person, 1)
        slave_store.get(Person, 1)

        # Slave Store breaks when pgbouncer is torn down. Master Store
        # is fine.
        self.pgbouncer_fixture.stop()
        master_store.get(Person, 2)
        self.assertRaises(DisconnectionError, slave_store.get, Person, 2)

    def test_startup_with_no_slave(self):
        '''An attempt is made for the first time to connect to a slave.'''
        self.pgbouncer_fixture.stop()

        master_store = IMasterStore(Person)
        slave_store = ISlaveStore(Person)

        # The master and slave Stores are the same object.
        self.assertIs(master_store, slave_store)

    def test_slave_shutdown_during_transaction(self):
        '''Slave is shutdown while running, but we can recover.'''
        master_store = IMasterStore(Person)
        slave_store = ISlaveStore(Person)

        self.assertIsNot(master_store, slave_store)

        self.pgbouncer_fixture.stop()

        # The transaction fails if the slave store is used. Robust
        # processes will handle this and retry (even if just means exit
        # and wait for the next scheduled invocation).
        self.assertRaises(DisconnectionError, slave_store.get, Person, 1)

        transaction.abort()

        # But in the next transaction, we get the master Store if we ask
        # for the slave Store so we can continue.
        master_store = IMasterStore(Person)
        slave_store = ISlaveStore(Person)

        self.assertIs(master_store, slave_store)

    def test_slave_shutdown_between_transactions(self):
        '''Slave is shutdown in between transactions.'''
        master_store = IMasterStore(Person)
        slave_store = ISlaveStore(Person)
        self.assertIsNot(master_store, slave_store)

        transaction.abort()
        self.pgbouncer_fixture.stop()

        # The process doesn't notice the slave going down, and things
        # will fail the next time the slave is used.
        master_store = IMasterStore(Person)
        slave_store = ISlaveStore(Person)
        self.assertIsNot(master_store, slave_store)
        self.assertRaises(DisconnectionError, slave_store.get, Person, 1)

        # But now it has been discovered the socket is no longer
        # connected to anything, next transaction we get a master
        # Store when we ask for a slave.
        master_store = IMasterStore(Person)
        slave_store = ISlaveStore(Person)
        self.assertIs(master_store, slave_store)

    def test_slave_reconnect_after_outage(self):
        '''The slave is again used once it becomes available.'''
        self.pgbouncer_fixture.stop()

        master_store = IMasterStore(Person)
        slave_store = ISlaveStore(Person)
        self.assertIs(master_store, slave_store)

        self.pgbouncer_fixture.start()
        transaction.abort()

        master_store = IMasterStore(Person)
        slave_store = ISlaveStore(Person)
        self.assertIsNot(master_store, slave_store)
