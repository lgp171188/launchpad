# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

from zope.component import getSiteManager
from zope.interface import (
    implements,
    Interface,
    )

from canonical.testing.layers import ZopelessDatabaseLayer
from lp.app.interfaces.security import IAuthorization
from lp.app.security import AuthorizationBase
from lp.testing import TestCaseWithFactory
from lp.testing.fakemethod import FakeMethod


class FakeSecurityAdapter(AuthorizationBase):

    def __init__(self):
        super(FakeSecurityAdapter, self).__init__(None)
        self.checkAuthenticated = FakeMethod()
        self.checkUnauthenticated = FakeMethod()

    def getCallCounts(self):
        """Helper method to create a tuple of the call counts.

        :returns: A tuple of the call counts for
            (checkAuthenticated, checkUnauthenticated).
        """
        return (
            self.checkAuthenticated.call_count,
            self.checkUnauthenticated.call_count
            )

class NextInterface(Interface):
    """Marker interface to test forwarding."""


class NextClass:
    """An implementation of NextInterface."""
    implements(NextInterface)


class TestAuthorizationBase(TestCaseWithFactory):

    layer = ZopelessDatabaseLayer

    def test_checkAccountAuthenticated_for_full_fledged_account(self):
        # AuthorizationBase.checkAccountAuthenticated should delegate to
        # checkAuthenticated() when the given account can be adapted into an
        # IPerson.
        full_fledged_account = self.factory.makePerson().account
        adapter = FakeSecurityAdapter()
        adapter.checkAccountAuthenticated(full_fledged_account)
        self.assertEquals((1, 0), adapter.getCallCounts())

    def test_checkAccountAuthenticated_for_personless_account(self):
        # AuthorizationBase.checkAccountAuthenticated should delegate to
        # checkUnauthenticated() when the given account can't be adapted into
        # an IPerson.
        personless_account = self.factory.makeAccount('Test account')
        adapter = FakeSecurityAdapter()
        adapter.checkAccountAuthenticated(personless_account)
        self.assertEquals((0, 1), adapter.getCallCounts())

    def _registerFakeSecurityAdpater(self, interface, permission):
        """Register an instance of FakeSecurityAdapter.

        Create an instance of FakeSecurityAdapter and register it as an
        adapter for the given interface and permission name.
        """
        adapter = FakeSecurityAdapter()
        def adapter_factory(adaptee):
            return adapter
        getSiteManager().registerAdapter(
            adapter_factory, (interface,), IAuthorization, permission)
        return adapter

    def test_forwardCheckAuthenticated_object_changes(self):
        permission = self.factory.getUniqueString()
        next_object = NextClass()
        next_adapter = self._registerFakeSecurityAdpater(
            NextInterface, permission)

        adapter = FakeSecurityAdapter()
        adapter.permission = permission
        adapter.usedfor = None
        adapter.checkPermissionIsRegistered = FakeMethod(result=True)

        adapter.forwardCheckAuthenticated(None, next_object)

        self.assertEqual(1, next_adapter.checkAuthenticated.call_count)
