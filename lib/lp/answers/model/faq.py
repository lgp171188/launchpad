# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""FAQ document models."""

__all__ = [
    "FAQ",
    "FAQSearch",
    "FAQSet",
]

from datetime import timezone

from lazr.lifecycle.event import ObjectCreatedEvent
from storm.expr import And, Desc
from storm.properties import DateTime, Int, Unicode
from storm.references import Reference, ReferenceSet
from storm.store import EmptyResultSet, Store
from zope.event import notify
from zope.interface import implementer

from lp.answers.interfaces.faq import IFAQ, CannotDeleteFAQ, IFAQSet
from lp.answers.interfaces.faqcollection import FAQSort
from lp.registry.interfaces.distribution import IDistribution
from lp.registry.interfaces.person import IPerson, validate_public_person
from lp.registry.interfaces.product import IProduct
from lp.registry.interfaces.projectgroup import IProjectGroup
from lp.services.database.constants import DEFAULT
from lp.services.database.interfaces import IPrimaryStore, IStore
from lp.services.database.nl_search import nl_phrase_search
from lp.services.database.stormbase import StormBase
from lp.services.database.stormexpr import fti_search, rank_by_fti


@implementer(IFAQ)
class FAQ(StormBase):
    """See `IFAQ`."""

    __storm_table__ = "FAQ"

    __storm_order__ = ["date_created", "id"]

    id = Int(primary=True)

    owner_id = Int(
        name="owner", allow_none=False, validator=validate_public_person
    )
    owner = Reference(owner_id, "Person.id")

    title = Unicode(allow_none=False)

    keywords = Unicode(name="tags", allow_none=True, default=None)

    content = Unicode(allow_none=True, default=None)

    date_created = DateTime(
        allow_none=False, default=DEFAULT, tzinfo=timezone.utc
    )

    last_updated_by_id = Int(
        name="last_updated_by",
        allow_none=True,
        default=None,
        validator=validate_public_person,
    )
    last_updated_by = Reference(last_updated_by_id, "Person.id")

    date_last_updated = DateTime(
        allow_none=True, default=None, tzinfo=timezone.utc
    )

    product_id = Int(name="product", allow_none=True, default=None)
    product = Reference(product_id, "Product.id")

    distribution_id = Int(name="distribution", allow_none=True, default=None)
    distribution = Reference(distribution_id, "Distribution.id")

    related_questions = ReferenceSet(
        "id", "Question.faq_id", order_by=("Question.datecreated")
    )

    def __init__(
        self,
        owner,
        title,
        content=None,
        keywords=None,
        date_created=DEFAULT,
        product=None,
        distribution=None,
    ):
        self.owner = owner
        self.title = title
        self.content = content
        self.keywords = keywords
        self.date_created = date_created
        self.product = product
        self.distribution = distribution

    @property
    def target(self):
        """See `IFAQ`."""
        if self.product:
            return self.product
        else:
            return self.distribution

    def destroySelf(self):
        if not self.related_questions.is_empty():
            raise CannotDeleteFAQ(
                "Cannot delete FAQ: questions must be unlinked first."
            )
        Store.of(self).remove(self)

    @staticmethod
    def new(
        owner,
        title,
        content,
        keywords=keywords,
        date_created=None,
        product=None,
        distribution=None,
    ):
        """Factory method to create a new FAQ.

        Ensure that only one of product or distribution is given.
        """
        if not IPerson.providedBy(owner):
            raise AssertionError(
                "owner parameter should be an IPerson, not %s" % type(owner)
            )
        if product is not None and distribution is not None:
            raise AssertionError(
                "only one of product or distribution should be provided"
            )
        if product is None and distribution is None:
            raise AssertionError("product or distribution must be provided")
        if date_created is None:
            date_created = DEFAULT
        faq = FAQ(
            owner=owner,
            title=str(title),
            content=str(content),
            keywords=keywords,
            date_created=date_created,
            product=product,
            distribution=distribution,
        )
        store = IPrimaryStore(FAQ)
        store.add(faq)
        store.flush()
        notify(ObjectCreatedEvent(faq))
        return faq

    @staticmethod
    def findSimilar(summary, product=None, distribution=None):
        """Return the FAQs similar to summary.

        See `IFAQTarget.findSimilarFAQs` for details.
        """
        assert not (
            product and distribution
        ), "only one of product or distribution should be provided"
        if product:
            target_constraint = FAQ.product == product
        elif distribution:
            target_constraint = FAQ.distribution == distribution
        else:
            raise AssertionError("must provide product or distribution")

        phrases = nl_phrase_search(summary, FAQ, [target_constraint])
        if not phrases:
            # No useful words to search on in that summary.
            return EmptyResultSet()

        store = IStore(FAQ)
        resultset = store.find(
            FAQ, fti_search(FAQ, phrases, ftq=False), target_constraint
        )
        return resultset.order_by(
            rank_by_fti(FAQ, phrases, ftq=False), Desc(FAQ.date_created)
        )

    @staticmethod
    def getForTarget(id, target):
        """Return the FAQ with the requested id.

        When target is not None, the target will be checked to make sure
        that the FAQ is in the expected target or return None otherwise.
        """
        faq = IStore(FAQ).get(FAQ, int(id))
        if faq is None:
            return None
        if target is None or target == faq.target:
            return faq
        else:
            return None


class FAQSearch:
    """Object that encapsulates a FAQ search.

    It is used to implement the `IFAQCollection`.searchFAQs() method.
    """

    search_text = None
    owner = None
    sort = None
    product = None
    distribution = None
    projectgroup = None

    def __init__(
        self,
        search_text=None,
        owner=None,
        sort=None,
        product=None,
        distribution=None,
        projectgroup=None,
    ):
        """Initialize a new FAQ search.

        See `IFAQCollection`.searchFAQs for the basic parameters description.
        Additional parameters:
        :param product: The product in which to search for FAQs.
        :param distribution: The distribution in which to search for FAQs.
        :param projectgroup: The project group in which to search for FAQs.
        """
        if search_text is not None:
            assert isinstance(
                search_text, str
            ), "search_text should be a string, not %s" % type(search_text)
            self.search_text = search_text

        if owner is not None:
            assert IPerson.providedBy(
                owner
            ), "owner should be an IPerson, not %s" % type(owner)
            self.owner = owner

        if sort is not None:
            assert (
                sort in FAQSort.items
            ), "sort should be an item from FAQSort, not %s" % type(sort)
            self.sort = sort

        if product is not None:
            assert IProduct.providedBy(
                product
            ), "product should be an IProduct, not %s" % type(product)
            assert (
                distribution is None and projectgroup is None
            ), "can only use one of product, distribution, or projectgroup"
            self.product = product

        if distribution is not None:
            assert IDistribution.providedBy(
                distribution
            ), "distribution should be an IDistribution, %s" % type(
                distribution
            )
            assert (
                product is None and projectgroup is None
            ), "can only use one of product, distribution, or projectgroup"
            self.distribution = distribution

        if projectgroup is not None:
            assert IProjectGroup.providedBy(
                projectgroup
            ), "projectgroup should be an IProjectGroup, not %s" % type(
                projectgroup
            )
            assert (
                product is None and distribution is None
            ), "can only use one of product, distribution, or projectgroup"
            self.projectgroup = projectgroup

    def getResults(self):
        """Return the FAQs matching this search."""
        store = IStore(FAQ)
        tables = self.getClauseTables()
        if tables:
            store = store.using(*tables)
        resultset = store.find(FAQ, *self.getConstraints())
        return resultset.order_by(self.getOrderByClause())

    def getConstraints(self):
        """Return the constraints to use by this search."""
        from lp.registry.model.product import Product

        constraints = []

        if self.search_text:
            constraints.append(fti_search(FAQ, self.search_text))

        if self.owner:
            constraints.append(FAQ.owner == self.owner)

        if self.product:
            constraints.append(FAQ.product == self.product)

        if self.distribution:
            constraints.append(FAQ.distribution == self.distribution)

        if self.projectgroup:
            constraints.append(
                And(
                    FAQ.product == Product.id,
                    Product.projectgroup == self.projectgroup,
                )
            )

        return constraints

    def getClauseTables(self):
        """Return the tables that should be added to the FROM clause."""
        from lp.registry.model.product import Product

        if self.projectgroup:
            return [FAQ, Product]
        else:
            return [FAQ]

    def getOrderByClause(self):
        """Return the ORDER BY clause to sort the results."""
        sort = self.sort
        if sort is None:
            if self.search_text is not None:
                sort = FAQSort.RELEVANCY
            else:
                sort = FAQSort.NEWEST_FIRST
        if sort is FAQSort.NEWEST_FIRST:
            return Desc(FAQ.date_created)
        elif sort is FAQSort.OLDEST_FIRST:
            return FAQ.date_created
        elif sort is FAQSort.RELEVANCY:
            if self.search_text:
                return [
                    rank_by_fti(FAQ, self.search_text),
                    Desc(FAQ.date_created),
                ]
            else:
                return Desc(FAQ.date_created)
        else:
            raise AssertionError("Unknown FAQSort value: %r" % sort)


@implementer(IFAQSet)
class FAQSet:
    """See `IFAQSet`."""

    def getFAQ(self, id):
        """See `IFAQSet`."""
        return FAQ.getForTarget(id, None)

    def searchFAQs(self, search_text=None, owner=None, sort=None):
        """See `IFAQSet`."""
        return FAQSearch(
            search_text=search_text, owner=owner, sort=sort
        ).getResults()
