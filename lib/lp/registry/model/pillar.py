# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Launchpad Pillars share a namespace.

Pillars are currently Product, ProjectGroup and Distribution.
"""

import warnings
from operator import attrgetter

import six
from storm.databases.postgres import Case
from storm.expr import And, Coalesce, Desc, LeftJoin, Lower, Or
from storm.info import ClassAlias
from storm.locals import Bool, Int, Reference, Unicode
from storm.store import Store
from zope.component import getUtility
from zope.interface import implementer, provider

from lp.app.errors import NotFoundError
from lp.registry.interfaces.distribution import IDistribution, IDistributionSet
from lp.registry.interfaces.pillar import (
    IPillarName,
    IPillarNameSet,
    IPillarPerson,
    IPillarPersonFactory,
)
from lp.registry.interfaces.product import IProduct, IProductSet
from lp.registry.interfaces.projectgroup import IProjectGroupSet
from lp.registry.model.featuredproject import FeaturedProject
from lp.services.config import config
from lp.services.database.bulk import load_related
from lp.services.database.decoratedresultset import DecoratedResultSet
from lp.services.database.interfaces import IStore
from lp.services.database.stormbase import StormBase
from lp.services.database.stormexpr import fti_search, rank_by_fti
from lp.services.librarian.model import LibraryFileAlias

__all__ = [
    "pillar_sort_key",
    "HasAliasMixin",
    "PillarNameSet",
    "PillarName",
    "PillarPerson",
]


def pillar_sort_key(pillar):
    """A sort key for a set of pillars. We want:

    - products first, alphabetically
    - distributions, with ubuntu first and the rest alphabetically
    """
    product_name = ""
    distribution_name = ""
    if IProduct.providedBy(pillar):
        product_name = pillar.name
    elif IDistribution.providedBy(pillar):
        distribution_name = pillar.name
    # Move ubuntu to the top.
    if distribution_name == "ubuntu":
        distribution_name = "-"

    return (distribution_name, product_name)


@implementer(IPillarNameSet)
class PillarNameSet:
    def __contains__(self, name):
        """See `IPillarNameSet`."""
        name = six.ensure_text(name)
        result = IStore(PillarName).execute(
            """
            SELECT TRUE
            FROM PillarName
            WHERE (id IN (SELECT alias_for FROM PillarName WHERE name=?)
                   OR name=?)
                AND alias_for IS NULL
                AND active IS TRUE
            """,
            [name, name],
        )
        return result.get_one() is not None

    def __getitem__(self, name):
        """See `IPillarNameSet`."""
        pillar = self.getByName(name, ignore_inactive=True)
        if pillar is None:
            raise NotFoundError(name)
        return pillar

    def getByName(self, name, ignore_inactive=False):
        """Return the pillar with the given name.

        If ignore_inactive is True, then only active pillars are considered.

        If no pillar is found, None is returned.
        """
        # We could attempt to do this in a single database query, but I
        # expect that doing two queries will be faster that OUTER JOINing
        # the Project, Product and Distribution tables (and this approach
        # works better with SQLObject too.

        # Retrieve information out of the PillarName table.
        query = """
            SELECT id, product, project, distribution
            FROM PillarName
            WHERE (id = (SELECT alias_for FROM PillarName WHERE name=?)
                   OR name=?)
                AND alias_for IS NULL%s
            LIMIT 1
            """
        if ignore_inactive:
            query %= " AND active IS TRUE"
        else:
            query %= ""
        name = six.ensure_text(name)
        result = IStore(PillarName).execute(query, [name, name])
        row = result.get_one()
        if row is None:
            return None

        assert len([column for column in row[1:] if column is None]) == 2, (
            "One (and only one) of product, project or distribution may be "
            "NOT NULL: %s" % row[1:]
        )

        id, product, projectgroup, distribution = row

        if product is not None:
            return getUtility(IProductSet).get(product)
        elif projectgroup is not None:
            return getUtility(IProjectGroupSet).get(projectgroup)
        else:
            return getUtility(IDistributionSet).get(distribution)

    def build_search_query(self, user, text):
        """Query parameters shared by search() and count_search_matches().

        :returns: Storm ResultSet object
        """
        # These classes are imported in this method to prevent an import loop.
        from lp.registry.model.distribution import Distribution
        from lp.registry.model.product import Product, ProductSet
        from lp.registry.model.projectgroup import ProjectGroup

        OtherPillarName = ClassAlias(PillarName)
        origin = [
            PillarName,
            LeftJoin(
                OtherPillarName, PillarName.alias_for == OtherPillarName.id
            ),
            LeftJoin(Product, PillarName.product == Product.id),
            LeftJoin(ProjectGroup, PillarName.projectgroup == ProjectGroup.id),
            LeftJoin(Distribution, PillarName.distribution == Distribution.id),
        ]
        conditions = And(
            PillarName.active,
            Or(
                PillarName.name == Lower(text),
                fti_search(Product, text),
                Lower(Product._title) == Lower(text),
                fti_search(ProjectGroup, text),
                Lower(ProjectGroup._title) == Lower(text),
                fti_search(Distribution, text),
                Lower(Distribution._title) == Lower(text),
            ),
        )
        columns = [
            PillarName,
            OtherPillarName,
            Product,
            ProjectGroup,
            Distribution,
        ]
        return (
            IStore(PillarName)
            .using(*origin)
            .find(
                tuple(columns),
                And(conditions, ProductSet.getProductPrivacyFilter(user)),
            )
        )

    def count_search_matches(self, user, text):
        text = six.ensure_text(text)
        result = self.build_search_query(user, text)
        return result.count()

    def search(self, user, text, limit):
        """See `IPillarSet`."""
        # Avoid circular imports.
        from lp.registry.model.distribution import Distribution
        from lp.registry.model.product import Product, get_precached_products
        from lp.registry.model.projectgroup import ProjectGroup

        text = six.ensure_text(text)
        if limit is None:
            limit = config.launchpad.default_batch_size

        # Pull out the licences as a subselect which is converted
        # into a PostgreSQL array so that multiple licences per product
        # can be retrieved in a single row for each product.
        result = self.build_search_query(user, text)

        # If the search text matches the name or title of the
        # Product, Project, or Distribution exactly, then this
        # row should get the highest search rank (9999999).
        # Each row in the PillarName table will join with only one
        # of either the Product, Project, or Distribution tables,
        # so the coalesce() is necessary to find the ts_rank() which
        # is not null.
        result.order_by(
            Desc(
                Case(
                    cases=(
                        (
                            Or(
                                PillarName.name == Lower(text),
                                Lower(Product._title) == Lower(text),
                                Lower(ProjectGroup._title) == Lower(text),
                                Lower(Distribution._title) == Lower(text),
                            ),
                            9999999,
                        ),
                    ),
                    default=Coalesce(
                        rank_by_fti(Product, text, desc=False),
                        rank_by_fti(ProjectGroup, text, desc=False),
                        rank_by_fti(Distribution, text, desc=False),
                    ),
                )
            ),
            PillarName.name,
        )
        # People shouldn't be calling this method with too big limits
        longest_expected = 2 * config.launchpad.default_batch_size
        if limit > longest_expected:
            warnings.warn(
                "The search limit (%s) was greater "
                "than the longest expected size (%s)"
                % (limit, longest_expected),
                stacklevel=2,
            )
        pillars = []
        products = []
        for pillar_name, other, product, projectgroup, distro in result[
            :limit
        ]:
            pillar = pillar_name.pillar
            if IProduct.providedBy(pillar):
                products.append(pillar)
            pillars.append(pillar)
        # Prefill pillar.product.licenses.
        get_precached_products(products, need_licences=True)
        return pillars

    def add_featured_project(self, project):
        """See `IPillarSet`."""
        existing = (
            IStore(FeaturedProject)
            .find(
                FeaturedProject,
                PillarName.name == project.name,
                PillarName.id == FeaturedProject.pillar_name_id,
            )
            .one()
        )
        if existing is None:
            pillar_name = (
                IStore(PillarName).find(PillarName, name=project.name).one()
            )
            featured_project = FeaturedProject(pillar_name=pillar_name)
            IStore(FeaturedProject).add(featured_project)
            return featured_project

    def remove_featured_project(self, project):
        """See `IPillarSet`."""
        existing = (
            IStore(FeaturedProject)
            .find(
                FeaturedProject,
                PillarName.name == project.name,
                PillarName.id == FeaturedProject.pillar_name_id,
            )
            .one()
        )
        if existing is not None:
            existing.destroySelf()

    @property
    def featured_projects(self):
        """See `IPillarSet`."""
        # Circular imports.
        from lp.registry.model.distribution import Distribution
        from lp.registry.model.product import Product
        from lp.registry.model.projectgroup import ProjectGroup

        store = IStore(PillarName)
        pillar_names = store.find(
            PillarName, PillarName.id == FeaturedProject.pillar_name_id
        )

        def preload_pillars(rows):
            pillar_names = set(rows).union(
                load_related(PillarName, rows, ["alias_for"])
            )
            pillars = load_related(Product, pillar_names, ["product_id"])
            pillars.extend(
                load_related(ProjectGroup, pillar_names, ["projectgroup_id"])
            )
            pillars.extend(
                load_related(Distribution, pillar_names, ["distribution_id"])
            )
            load_related(LibraryFileAlias, pillars, ["icon_id"])

        return list(
            DecoratedResultSet(
                pillar_names,
                result_decorator=attrgetter("pillar"),
                pre_iter_hook=preload_pillars,
            )
        )


@implementer(IPillarName)
class PillarName(StormBase):
    __storm_table__ = "PillarName"
    __storm_order__ = "name"

    id = Int(primary=True)
    name = Unicode(name="name", allow_none=False)
    product_id = Int(name="product", allow_none=True)
    product = Reference(product_id, "Product.id")
    projectgroup_id = Int(name="project", allow_none=True)
    projectgroup = Reference(projectgroup_id, "ProjectGroup.id")
    distribution_id = Int(name="distribution", allow_none=True)
    distribution = Reference(distribution_id, "Distribution.id")
    active = Bool(name="active", allow_none=False, default=True)
    alias_for_id = Int(name="alias_for", allow_none=True, default=None)
    alias_for = Reference(alias_for_id, "PillarName.id")

    def __init__(self, name, alias_for=None):
        super().__init__()
        self.name = name
        self.alias_for = alias_for

    @property
    def pillar(self):
        pillar_name = self
        if self.alias_for is not None:
            pillar_name = self.alias_for

        if pillar_name.distribution is not None:
            return pillar_name.distribution
        elif pillar_name.projectgroup is not None:
            return pillar_name.projectgroup
        elif pillar_name.product is not None:
            return pillar_name.product
        else:
            raise AssertionError("Unknown pillar type: %s" % pillar_name.name)


class HasAliasMixin:
    """Mixin for classes that implement IHasAlias."""

    @property
    def aliases(self):
        """See `IHasAlias`."""
        store = IStore(PillarName)
        aliases = store.find(
            PillarName, alias_for=store.find(PillarName, name=self.name).one()
        )
        return [alias.name for alias in aliases]

    def setAliases(self, names):
        """See `IHasAlias`."""
        store = Store.of(self)
        existing_aliases = set(self.aliases)
        self_pillar = store.find(PillarName, name=self.name).one()
        to_remove = set(existing_aliases).difference(names)
        to_add = set(names).difference(existing_aliases)
        for name in to_add:
            assert store.find(PillarName, name=name).count() == 0, (
                "This alias is already in use: %s" % name
            )
            PillarName(name=name, alias_for=self_pillar)
        for name in to_remove:
            pillar_name = store.find(PillarName, name=name).one()
            assert (
                pillar_name.alias_for == self_pillar
            ), "Can't remove an alias of another pillar."
            store.remove(pillar_name)


@implementer(IPillarPerson)
@provider(IPillarPersonFactory)
class PillarPerson:
    def __init__(self, pillar, person):
        self.pillar = pillar
        self.person = person

    @staticmethod
    def create(pillar, person):
        return PillarPerson(pillar, person)
