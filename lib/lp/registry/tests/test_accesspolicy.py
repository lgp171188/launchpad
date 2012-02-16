# Copyright 2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

from storm.exceptions import LostObjectError
from storm.store import Store
from testtools.matchers import MatchesStructure
from zope.component import getUtility

from lp.registry.interfaces.accesspolicy import (
    AccessPolicyType,
    IAccessPolicy,
    IAccessArtifact,
    IAccessArtifactGrant,
    IAccessArtifactGrantSource,
    IAccessArtifactSource,
    IAccessPolicyGrant,
    IAccessPolicyGrantSource,
    IAccessPolicySource,
    )
from lp.services.database.lpstorm import IStore
from lp.testing import TestCaseWithFactory
from lp.testing.layers import DatabaseFunctionalLayer
from lp.testing.matchers import Provides


class TestAccessPolicy(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_provides_interface(self):
        self.assertThat(
            self.factory.makeAccessPolicy(), Provides(IAccessPolicy))

    def test_pillar(self):
        product = self.factory.makeProduct()
        policy = self.factory.makeAccessPolicy(pillar=product)
        self.assertEqual(product, policy.pillar)


class TestAccessPolicySource(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_create_for_product(self):
        product = self.factory.makeProduct()
        type = AccessPolicyType.SECURITY
        policy = getUtility(IAccessPolicySource).create(product, type)
        self.assertThat(
            policy,
            MatchesStructure.byEquality(pillar=product, type=type))

    def test_getByID(self):
        # getByID finds the right policy.
        policy = self.factory.makeAccessPolicy()
        # Flush so we get an ID.
        Store.of(policy).flush()
        self.assertEqual(
            policy, getUtility(IAccessPolicySource).getByID(policy.id))

    def test_getByID_nonexistent(self):
        # getByID returns None if the policy doesn't exist.
        self.assertIs(
            None,
            getUtility(IAccessPolicySource).getByID(
                self.factory.getUniqueInteger()))

    def test_getByPillarAndType(self):
        # getByPillarAndType finds the right policy.
        product = self.factory.makeProduct()

        private_policy = self.factory.makeAccessPolicy(
            pillar=product, type=AccessPolicyType.PRIVATE)
        security_policy = self.factory.makeAccessPolicy(
            pillar=product, type=AccessPolicyType.SECURITY)
        self.assertEqual(
            private_policy,
            getUtility(IAccessPolicySource).getByPillarAndType(
                product, AccessPolicyType.PRIVATE))
        self.assertEqual(
            security_policy,
            getUtility(IAccessPolicySource).getByPillarAndType(
                product, AccessPolicyType.SECURITY))

    def test_getByPillarAndType_nonexistent(self):
        # getByPillarAndType returns None if the policy doesn't exist.
        # Create policy identifiers, and an unrelated policy.
        self.factory.makeAccessPolicy(type=AccessPolicyType.PRIVATE)
        product = self.factory.makeProduct()
        self.assertIs(
            None,
            getUtility(IAccessPolicySource).getByPillarAndType(
                product, AccessPolicyType.PRIVATE))

    def test_findByPillar(self):
        # findByPillar finds only the relevant policies.
        product = self.factory.makeProduct()
        policies = [
            self.factory.makeAccessPolicy(pillar=product, type=type)
            for type in AccessPolicyType.items]
        self.factory.makeAccessPolicy()
        self.assertContentEqual(
            policies,
            getUtility(IAccessPolicySource).findByPillar(product))


class TestAccessArtifact(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_provides_interface(self):
        self.assertThat(
            self.factory.makeAccessArtifact(),
            Provides(IAccessArtifact))


class TestAccessArtifactSourceOnce(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_ensure_other_fails(self):
        # ensure() rejects unsupported objects.
        self.assertRaises(
            ValueError,
            getUtility(IAccessArtifactSource).ensure,
            self.factory.makeProduct())


class BaseAccessArtifactTests:
    layer = DatabaseFunctionalLayer

    def getConcreteArtifact(self):
        raise NotImplementedError()

    def test_ensure(self):
        # ensure() creates an abstract artifact which maps to the
        # concrete one.
        concrete = self.getConcreteArtifact()
        abstract = getUtility(IAccessArtifactSource).ensure(concrete)
        Store.of(abstract).flush()
        self.assertEqual(concrete, abstract.concrete_artifact)

    def test_get(self):
        # get() finds an abstract artifact which maps to the concrete
        # one.
        concrete = self.getConcreteArtifact()
        abstract = getUtility(IAccessArtifactSource).ensure(concrete)
        self.assertEqual(
            abstract, getUtility(IAccessArtifactSource).get(concrete))

    def test_ensure_twice(self):
        # ensure() will reuse an existing matching abstract artifact if
        # it exists.
        concrete = self.getConcreteArtifact()
        abstract = getUtility(IAccessArtifactSource).ensure(concrete)
        Store.of(abstract).flush()
        self.assertEqual(
            abstract.id,
            getUtility(IAccessArtifactSource).ensure(concrete).id)

    def test_delete(self):
        # delete() removes the abstract artifact and any associated
        # grants.
        concrete = self.getConcreteArtifact()
        abstract = getUtility(IAccessArtifactSource).ensure(concrete)
        grant = self.factory.makeAccessArtifactGrant(artifact=abstract)

        # Make some other grants to ensure they're unaffected.
        other_grants = [
            self.factory.makeAccessArtifactGrant(
                artifact=self.factory.makeAccessArtifact()),
            self.factory.makeAccessPolicyGrant(
                policy=self.factory.makeAccessPolicy()),
            ]

        getUtility(IAccessArtifactSource).delete(concrete)
        IStore(grant).invalidate()
        self.assertRaises(LostObjectError, getattr, grant, 'grantor')
        self.assertRaises(
            LostObjectError, getattr, abstract, 'concrete_artifact')

        for other_grant in other_grants:
            other_grant.grantor

    def test_delete_noop(self):
        # delete() works even if there's no abstract artifact.
        concrete = self.getConcreteArtifact()
        getUtility(IAccessArtifactSource).delete(concrete)


class TestAccessArtifactBranch(BaseAccessArtifactTests,
                               TestCaseWithFactory):

    def getConcreteArtifact(self):
        return self.factory.makeBranch()


class TestAccessArtifactBug(BaseAccessArtifactTests,
                            TestCaseWithFactory):

    def getConcreteArtifact(self):
        return self.factory.makeBug()


class TestAccessArtifactGrant(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_provides_interface(self):
        self.assertThat(
            self.factory.makeAccessArtifactGrant(),
            Provides(IAccessArtifactGrant))

    def test_concrete_artifact(self):
        bug = self.factory.makeBug()
        abstract = self.factory.makeAccessArtifact(bug)
        grant = self.factory.makeAccessArtifactGrant(artifact=abstract)
        self.assertEqual(bug, grant.concrete_artifact)


class TestAccessArtifactGrantSource(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_grant(self):
        artifact = self.factory.makeAccessArtifact()
        grantee = self.factory.makePerson()
        grantor = self.factory.makePerson()
        grant = getUtility(IAccessArtifactGrantSource).grant(
            artifact, grantee, grantor)
        self.assertThat(
            grant,
            MatchesStructure.byEquality(
                grantee=grantee,
                grantor=grantor,
                abstract_artifact=artifact,
                concrete_artifact=artifact.concrete_artifact))

    def test_get(self):
        # get() finds the right grant.
        grant = self.factory.makeAccessArtifactGrant()
        self.assertEqual(
            grant,
            getUtility(IAccessArtifactGrantSource).get(
                grant.abstract_artifact, grant.grantee))

    def test_get_nonexistent(self):
        # get() returns None if the grant doesn't exist.
        self.assertIs(
            None,
            getUtility(IAccessArtifactGrantSource).get(
                self.factory.makeAccessArtifact(), self.factory.makePerson()))

    def test_findByPolicy(self):
        # findByPolicy finds only the relevant grants.
        artifact = self.factory.makeAccessArtifact()
        grants = [
            self.factory.makeAccessArtifactGrant(artifact=artifact)
            for i in range(3)]
        self.factory.makeAccessArtifactGrant()
        self.assertContentEqual(
            grants,
            getUtility(IAccessArtifactGrantSource).findByArtifact(artifact))


class TestAccessPolicyGrant(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_provides_interface(self):
        self.assertThat(
            self.factory.makeAccessPolicyGrant(),
            Provides(IAccessPolicyGrant))


class TestAccessPolicyGrantSource(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_grant(self):
        policy = self.factory.makeAccessPolicy()
        grantee = self.factory.makePerson()
        grantor = self.factory.makePerson()
        grant = getUtility(IAccessPolicyGrantSource).grant(
            policy, grantee, grantor)
        self.assertThat(
            grant,
            MatchesStructure.byEquality(
                grantee=grantee,
                grantor=grantor,
                policy=policy))

    def test_get(self):
        # get() finds the right grant.
        grant = self.factory.makeAccessPolicyGrant()
        self.assertEqual(
            grant,
            getUtility(IAccessPolicyGrantSource).get(
                grant.policy, grant.grantee))

    def test_get_nonexistent(self):
        # get() returns None if the grant doesn't exist.
        self.assertIs(
            None,
            getUtility(IAccessPolicyGrantSource).get(
                self.factory.makeAccessPolicy(), self.factory.makePerson()))

    def test_findByPolicy(self):
        # findByPolicy finds only the relevant grants.
        policy = self.factory.makeAccessPolicy()
        grants = [
            self.factory.makeAccessPolicyGrant(policy=policy)
            for i in range(3)]
        self.factory.makeAccessPolicyGrant()
        self.assertContentEqual(
            grants,
            getUtility(IAccessPolicyGrantSource).findByPolicy(policy))
