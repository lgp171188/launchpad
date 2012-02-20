# Copyright 2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Model classes for pillar and artifact access policies."""

__metaclass__ = type
__all__ = [
    'AccessArtifact',
    'AccessPolicy',
    'AccessPolicyGrant',
    ]

from storm.databases.postgres import Returning
from storm.properties import (
    DateTime,
    Int,
    )
from storm.references import Reference
from zope.interface import implements

from lp.registry.interfaces.accesspolicy import (
    AccessPolicyType,
    IAccessArtifact,
    IAccessArtifactGrant,
    IAccessPolicy,
    IAccessPolicyGrant,
    )
from lp.registry.interfaces.person import IPerson
from lp.services.database.bulk import load
from lp.services.database.enumcol import DBEnum
from lp.services.database.lpstorm import IStore
from lp.services.database.stormbase import StormBase
from lp.services.database.stormexpr import BulkInsert


class AccessArtifact(StormBase):
    implements(IAccessArtifact)

    __storm_table__ = 'AccessArtifact'

    id = Int(primary=True)
    bug_id = Int(name='bug')
    bug = Reference(bug_id, 'Bug.id')
    branch_id = Int(name='branch')
    branch = Reference(branch_id, 'Branch.id')

    @property
    def concrete_artifact(self):
        artifact = self.bug or self.branch
        assert artifact is not None
        return artifact

    @staticmethod
    def _getConcreteAttribute(concrete_artifact):
        from lp.bugs.interfaces.bug import IBug
        from lp.code.interfaces.branch import IBranch
        if IBug.providedBy(concrete_artifact):
            return 'bug'
        elif IBranch.providedBy(concrete_artifact):
            return 'branch'
        else:
            raise ValueError(
                "%r is not a valid artifact" % concrete_artifact)

    @classmethod
    def get(cls, concrete_artifact):
        """See `IAccessArtifactSource`."""
        constraints = {
            cls._getConcreteAttribute(concrete_artifact): concrete_artifact}
        return IStore(cls).find(cls, **constraints).one()

    @classmethod
    def ensure(cls, concrete_artifact):
        """See `IAccessArtifactSource`."""
        existing = cls.get(concrete_artifact)
        if existing is not None:
            return existing
        # No existing object. Create a new one.
        obj = cls()
        setattr(
            obj, cls._getConcreteAttribute(concrete_artifact),
            concrete_artifact)
        IStore(cls).add(obj)
        return obj

    @classmethod
    def delete(cls, concrete_artifact):
        """See `IAccessPolicyArtifactSource`."""
        abstract = cls.get(concrete_artifact)
        if abstract is None:
            return
        IStore(abstract).find(
            AccessArtifactGrant, abstract_artifact=abstract).remove()
        IStore(abstract).find(AccessArtifact, id=abstract.id).remove()


class AccessPolicy(StormBase):
    implements(IAccessPolicy)

    __storm_table__ = 'AccessPolicy'

    id = Int(primary=True)
    product_id = Int(name='product')
    product = Reference(product_id, 'Product.id')
    distribution_id = Int(name='distribution')
    distribution = Reference(distribution_id, 'Distribution.id')
    type = DBEnum(allow_none=True, enum=AccessPolicyType)

    @property
    def pillar(self):
        return self.product or self.distribution

    @classmethod
    def create(cls, policies):
        from lp.registry.interfaces.distribution import IDistribution
        from lp.registry.interfaces.product import IProduct

        insert_values = []
        for pillar, type in policies:
            if IProduct.providedBy(pillar):
                insert_values.append((pillar.id, None, type.value))
            elif IDistribution.providedBy(pillar):
                insert_values.append((None, pillar.id, type.value))
            else:
                raise ValueError("%r is not a supported pillar" % pillar)
        result = IStore(cls).execute(
            Returning(BulkInsert(
                (cls.product_id, cls.distribution_id, cls.type),
                expr=insert_values, primary_columns=cls.id)))
        return load(AccessPolicy, (cols[0] for cols in result))

    @classmethod
    def _constraintForPillar(cls, pillar):
        from lp.registry.interfaces.distribution import IDistribution
        from lp.registry.interfaces.product import IProduct
        if IProduct.providedBy(pillar):
            col = cls.product
        elif IDistribution.providedBy(pillar):
            col = cls.distribution
        else:
            raise ValueError("%r is not a supported pillar" % pillar)
        return col == pillar

    @classmethod
    def getByID(cls, id):
        """See `IAccessPolicySource`."""
        return IStore(cls).get(cls, id)

    @classmethod
    def findByPillar(cls, pillar):
        """See `IAccessPolicySource`."""
        return IStore(cls).find(cls, cls._constraintForPillar(pillar))

    @classmethod
    def getByPillarAndType(cls, pillar, type):
        """See `IAccessPolicySource`."""
        return cls.findByPillar(pillar).find(type=type).one()


class AccessArtifactGrant(StormBase):
    implements(IAccessArtifactGrant)

    __storm_table__ = 'AccessArtifactGrant'
    __storm_primary__ = 'abstract_artifact_id', 'grantee_id'

    abstract_artifact_id = Int(name='artifact')
    abstract_artifact = Reference(
        abstract_artifact_id, 'AccessArtifact.id')
    grantee_id = Int(name='grantee')
    grantee = Reference(grantee_id, 'Person.id')
    grantor_id = Int(name='grantor')
    grantor = Reference(grantor_id, 'Person.id')
    date_created = DateTime()

    @property
    def concrete_artifact(self):
        if self.abstract_artifact is not None:
            return self.abstract_artifact.concrete_artifact

    @classmethod
    def grant(cls, artifact, grantee, grantor):
        """See `IAccessArtifactGrantSource`."""
        grant = cls()
        grant.abstract_artifact = artifact
        grant.grantee = grantee
        grant.grantor = grantor
        IStore(cls).add(grant)
        return grant

    @classmethod
    def get(cls, artifact, grantee):
        """See `IAccessArtifactGrantSource`."""
        assert IAccessArtifact.providedBy(artifact)
        assert IPerson.providedBy(grantee)
        return IStore(cls).get(cls, (artifact.id, grantee.id))

    @classmethod
    def findByArtifact(cls, artifact):
        """See `IAccessArtifactGrantSource`."""
        return IStore(cls).find(cls, abstract_artifact=artifact)


class AccessPolicyGrant(StormBase):
    implements(IAccessPolicyGrant)

    __storm_table__ = 'AccessPolicyGrant'
    __storm_primary__ = 'policy_id', 'grantee_id'

    policy_id = Int(name='policy')
    policy = Reference(policy_id, 'AccessPolicy.id')
    grantee_id = Int(name='grantee')
    grantee = Reference(grantee_id, 'Person.id')
    grantor_id = Int(name='grantor')
    grantor = Reference(grantor_id, 'Person.id')
    date_created = DateTime()

    @classmethod
    def grant(cls, policy, grantee, grantor):
        """See `IAccessPolicyGrantSource`."""
        grant = cls()
        grant.policy = policy
        grant.grantee = grantee
        grant.grantor = grantor
        IStore(cls).add(grant)
        return grant

    @classmethod
    def get(cls, policy, grantee):
        """See `IAccessPolicyGrantSource`."""
        assert IAccessPolicy.providedBy(policy)
        assert IPerson.providedBy(grantee)
        return IStore(cls).get(cls, (policy.id, grantee.id))

    @classmethod
    def findByPolicy(cls, policy):
        """See `IAccessPolicyGrantSource`."""
        return IStore(cls).find(cls, policy=policy)
