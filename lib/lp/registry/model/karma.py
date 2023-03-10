# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "Karma",
    "KarmaAction",
    "KarmaActionSet",
    "KarmaAssignedEvent",
    "KarmaCache",
    "KarmaCacheManager",
    "KarmaTotalCache",
    "KarmaCategory",
    "KarmaContextMixin",
]

from datetime import timezone

from storm.locals import DateTime, Desc, Int, Reference, ReferenceSet, Unicode
from zope.interface import implementer

from lp.app.errors import NotFoundError
from lp.registry.interfaces.distribution import IDistribution
from lp.registry.interfaces.karma import (
    IKarma,
    IKarmaAction,
    IKarmaActionSet,
    IKarmaAssignedEvent,
    IKarmaCache,
    IKarmaCacheManager,
    IKarmaCategory,
    IKarmaContext,
    IKarmaTotalCache,
)
from lp.registry.interfaces.product import IProduct
from lp.registry.interfaces.projectgroup import IProjectGroup
from lp.services.database.constants import UTC_NOW
from lp.services.database.interfaces import IStore
from lp.services.database.stormbase import StormBase


@implementer(IKarmaAssignedEvent)
class KarmaAssignedEvent:
    """See `IKarmaAssignedEvent`."""

    def __init__(self, object, karma):
        self.object = object
        self.karma = karma


@implementer(IKarma)
class Karma(StormBase):
    """See IKarma."""

    __storm_table__ = "Karma"
    __storm_order__ = ["action", "id"]

    id = Int(primary=True)

    person_id = Int(name="person", allow_none=False)
    person = Reference(person_id, "Person.id")
    action_id = Int(name="action", allow_none=False)
    action = Reference(action_id, "KarmaAction.id")
    product_id = Int(name="product", allow_none=True)
    product = Reference(product_id, "Product.id")
    distribution_id = Int(name="distribution", allow_none=True)
    distribution = Reference(distribution_id, "Distribution.id")
    sourcepackagename_id = Int(name="sourcepackagename", allow_none=True)
    sourcepackagename = Reference(sourcepackagename_id, "SourcePackageName.id")
    datecreated = DateTime(
        name="datecreated",
        allow_none=False,
        default=UTC_NOW,
        tzinfo=timezone.utc,
    )

    def __init__(
        self,
        person,
        action,
        product=None,
        distribution=None,
        sourcepackagename=None,
        datecreated=None,
    ):
        super().__init__()
        self.person = person
        self.action = action
        self.product = product
        self.distribution = distribution
        self.sourcepackagename = sourcepackagename
        self.datecreated = datecreated


@implementer(IKarmaAction)
class KarmaAction(StormBase):
    """See IKarmaAction."""

    __storm_table__ = "KarmaAction"
    sortingColumns = ["category", "name"]
    __storm_order__ = sortingColumns

    id = Int(primary=True)

    name = Unicode(name="name", allow_none=False)
    title = Unicode(name="title", allow_none=False)
    summary = Unicode(name="summary", allow_none=False)
    category_id = Int(name="category", allow_none=False)
    category = Reference(category_id, "KarmaCategory.id")
    points = Int(name="points", allow_none=False)


@implementer(IKarmaActionSet)
class KarmaActionSet:
    """See IKarmaActionSet."""

    def __iter__(self):
        return iter(IStore(KarmaAction).find(KarmaAction))

    def getByName(self, name, default=None):
        """See IKarmaActionSet."""
        action = IStore(KarmaAction).find(KarmaAction, name=name).one()
        if action is None:
            return default
        return action

    def selectByCategory(self, category):
        """See IKarmaActionSet."""
        return IStore(KarmaAction).find(KarmaAction, category=category)

    def selectByCategoryAndPerson(self, category, person, orderBy=None):
        """See IKarmaActionSet."""
        if orderBy is None:
            orderBy = KarmaAction.sortingColumns
        return (
            IStore(KarmaAction)
            .find(
                KarmaAction,
                KarmaAction.category == category,
                Karma.action == KarmaAction.id,
                Karma.person == person,
            )
            .config(distinct=True)
            .order_by(orderBy)
        )


@implementer(IKarmaCache)
class KarmaCache(StormBase):
    """See IKarmaCache."""

    __storm_table__ = "KarmaCache"
    __storm_order__ = ["category", "id"]

    id = Int(primary=True)

    person_id = Int(name="person", allow_none=False)
    person = Reference(person_id, "Person.id")
    category_id = Int(name="category", allow_none=True)
    category = Reference(category_id, "KarmaCategory.id")
    karmavalue = Int(name="karmavalue", allow_none=False)
    product_id = Int(name="product", allow_none=True)
    product = Reference(product_id, "Product.id")
    projectgroup_id = Int(name="project", allow_none=True)
    projectgroup = Reference(projectgroup_id, "ProjectGroup.id")
    distribution_id = Int(name="distribution", allow_none=True)
    distribution = Reference(distribution_id, "Distribution.id")
    sourcepackagename_id = Int(name="sourcepackagename", allow_none=True)
    sourcepackagename = Reference(sourcepackagename_id, "SourcePackageName.id")

    # It's a little odd for the constructor to explicitly take IDs, but this
    # is mainly called by cronscripts/foaf-update-karma-cache.py which only
    # has the IDs available to it.
    def __init__(
        self,
        person_id,
        karmavalue,
        category_id=None,
        product_id=None,
        projectgroup_id=None,
        distribution_id=None,
        sourcepackagename_id=None,
    ):
        super().__init__()
        self.person_id = person_id
        self.karmavalue = karmavalue
        self.category_id = category_id
        self.product_id = product_id
        self.projectgroup_id = projectgroup_id
        self.distribution_id = distribution_id
        self.sourcepackagename_id = sourcepackagename_id


@implementer(IKarmaCacheManager)
class KarmaCacheManager:
    """See IKarmaCacheManager."""

    def new(
        self,
        value,
        person_id,
        category_id,
        product_id=None,
        distribution_id=None,
        sourcepackagename_id=None,
        projectgroup_id=None,
    ):
        """See IKarmaCacheManager."""
        karma_cache = KarmaCache(
            karmavalue=value,
            person_id=person_id,
            category_id=category_id,
            product_id=product_id,
            distribution_id=distribution_id,
            sourcepackagename_id=sourcepackagename_id,
            projectgroup_id=projectgroup_id,
        )
        IStore(KarmaCache).add(karma_cache)
        return karma_cache

    def updateKarmaValue(
        self,
        value,
        person_id,
        category_id,
        product_id=None,
        distribution_id=None,
        sourcepackagename_id=None,
        projectgroup_id=None,
    ):
        """See IKarmaCacheManager."""
        entry = self._getEntry(
            person_id=person_id,
            category_id=category_id,
            product_id=product_id,
            distribution_id=distribution_id,
            projectgroup_id=projectgroup_id,
            sourcepackagename_id=sourcepackagename_id,
        )
        if entry is None:
            raise NotFoundError("KarmaCache not found: %s" % vars())
        else:
            entry.karmavalue = value
            IStore(entry).flush()

    def _getEntry(
        self,
        person_id,
        category_id,
        product_id=None,
        distribution_id=None,
        sourcepackagename_id=None,
        projectgroup_id=None,
    ):
        """Return the KarmaCache entry with the given arguments.

        Return None if it's not found.
        """
        return (
            IStore(KarmaCache)
            .find(
                KarmaCache,
                KarmaCache.person == person_id,
                KarmaCache.category == category_id,
                KarmaCache.product == product_id,
                KarmaCache.projectgroup == projectgroup_id,
                KarmaCache.distribution == distribution_id,
                KarmaCache.sourcepackagename == sourcepackagename_id,
            )
            .one()
        )


@implementer(IKarmaTotalCache)
class KarmaTotalCache(StormBase):
    """A cached value of the total of a person's karma (all categories)."""

    __storm_table__ = "KarmaTotalCache"
    __storm_order__ = ["id"]

    id = Int(primary=True)

    person_id = Int(name="person", allow_none=False)
    person = Reference(person_id, "Person.id")
    karma_total = Int(name="karma_total", allow_none=False)

    def __init__(self, person, karma_total):
        super().__init__()
        self.person = person
        self.karma_total = karma_total


@implementer(IKarmaCategory)
class KarmaCategory(StormBase):
    """See IKarmaCategory."""

    __storm_table__ = "KarmaCategory"
    __storm_order__ = ["title", "id"]

    id = Int(primary=True)

    name = Unicode(allow_none=False)
    title = Unicode(allow_none=False)
    summary = Unicode(allow_none=False)

    karmaactions = ReferenceSet(
        "id", "KarmaAction.category_id", order_by="KarmaAction.name"
    )


@implementer(IKarmaContext)
class KarmaContextMixin:
    """A mixin to be used by classes implementing IKarmaContext.

    This would be better as an adapter for Product and Distribution, but a
    mixin should be okay for now.
    """

    def getTopContributorsGroupedByCategory(self, limit=None):
        """See IKarmaContext."""
        contributors_by_category = {}
        for category in IStore(KarmaCategory).find(KarmaCategory):
            results = self.getTopContributors(category=category, limit=limit)
            if results:
                contributors_by_category[category] = results
        return contributors_by_category

    def getTopContributors(self, category=None, limit=None):
        """See IKarmaContext."""
        from lp.registry.model.person import Person

        store = IStore(Person)
        if IProduct.providedBy(self):
            condition = KarmaCache.product == self.id
        elif IDistribution.providedBy(self):
            condition = KarmaCache.distribution == self.id
        elif IProjectGroup.providedBy(self):
            condition = KarmaCache.projectgroup == self.id
        else:
            raise AssertionError(
                "Not a product, project group or distribution: %r" % self
            )

        if category is not None:
            category = category.id
        contributors = (
            store.find(
                (Person, KarmaCache.karmavalue),
                KarmaCache.person_id == Person.id,
                KarmaCache.category == category,
                condition,
            )
            .order_by(Desc(KarmaCache.karmavalue))
            .config(limit=limit)
        )
        return list(contributors)
