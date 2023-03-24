# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Database classes for project news and announcement."""

__all__ = [
    "Announcement",
    "AnnouncementSet",
    "HasAnnouncements",
    "MakesAnnouncements",
]

from datetime import timezone

from storm.expr import And, LeftJoin, Or, Select
from storm.properties import Bool, DateTime, Int, Unicode
from storm.references import Reference
from zope.interface import implementer

from lp.registry.interfaces.announcement import IAnnouncement, IAnnouncementSet
from lp.registry.interfaces.distribution import IDistribution
from lp.registry.interfaces.person import validate_public_person
from lp.registry.interfaces.product import IProduct
from lp.registry.interfaces.projectgroup import IProjectGroup
from lp.services.database.constants import UTC_NOW
from lp.services.database.interfaces import IPrimaryStore, IStore
from lp.services.database.stormbase import StormBase
from lp.services.utils import utc_now


@implementer(IAnnouncement)
class Announcement(StormBase):
    """A news item. These allow us to generate lists of recent news for
    project groups, products and distributions.
    """

    __storm_table__ = "Announcement"

    __storm_order__ = ("-date_announced", "-date_created")

    id = Int(primary=True)

    date_created = DateTime(
        allow_none=False, default=UTC_NOW, tzinfo=timezone.utc
    )
    date_announced = DateTime(
        allow_none=True, default=None, tzinfo=timezone.utc
    )
    date_last_modified = DateTime(
        name="date_updated", allow_none=True, default=None, tzinfo=timezone.utc
    )

    registrant_id = Int(
        name="registrant", allow_none=False, validator=validate_public_person
    )
    registrant = Reference(registrant_id, "Person.id")

    product_id = Int(name="product", allow_none=True, default=None)
    product = Reference(product_id, "Product.id")

    projectgroup_id = Int(name="project", allow_none=True, default=None)
    projectgroup = Reference(projectgroup_id, "ProjectGroup.id")

    distribution_id = Int(name="distribution", allow_none=True, default=None)
    distribution = Reference(distribution_id, "Distribution.id")

    title = Unicode(allow_none=False)
    summary = Unicode(allow_none=True, default=None)
    url = Unicode(allow_none=True, default=None)
    active = Bool(allow_none=False, default=True)

    def __init__(
        self,
        registrant,
        title,
        summary=None,
        url=None,
        active=True,
        date_created=UTC_NOW,
        date_announced=None,
        date_last_modified=None,
        product=None,
        projectgroup=None,
        distribution=None,
    ):
        self.registrant = registrant
        self.title = title
        self.summary = summary
        self.url = url
        self.active = active
        self.date_created = date_created
        self.date_announced = date_announced
        self.date_last_modified = date_last_modified
        self.product = product
        self.projectgroup = projectgroup
        self.distribution = distribution

    def destroySelf(self):
        IPrimaryStore(self).remove(self)

    def modify(self, title, summary, url):
        title = str(title) if title is not None else None
        summary = str(summary) if summary is not None else None
        url = str(url) if url is not None else None
        if self.title != title:
            self.title = title
            self.date_last_modified = UTC_NOW
        if self.summary != summary:
            self.summary = summary
            self.date_last_modified = UTC_NOW
        if self.url != url:
            self.url = url
            self.date_last_modified = UTC_NOW

    @property
    def target(self):
        if self.product is not None:
            return self.product
        elif self.projectgroup is not None:
            return self.projectgroup
        elif self.distribution is not None:
            return self.distribution
        else:
            raise AssertionError("Announcement has no obvious target")

    @property
    def date_updated(self):
        if self.date_last_modified is not None:
            return self.date_last_modified
        return self.date_created

    def retarget(self, target):
        """See `IAnnouncement`."""
        if IProduct.providedBy(target):
            self.product = target
            self.distribution = None
            self.projectgroup = None
        elif IDistribution.providedBy(target):
            self.distribution = target
            self.projectgroup = None
            self.product = None
        elif IProjectGroup.providedBy(target):
            self.projectgroup = target
            self.distribution = None
            self.product = None
        else:
            raise AssertionError("Unknown target")
        self.date_last_modified = UTC_NOW

    def retract(self):
        """See `IAnnouncement`."""
        self.active = False
        self.date_last_modified = UTC_NOW

    def setPublicationDate(self, publication_date):
        """See `IAnnouncement`."""
        self.date_announced = publication_date
        self.date_last_modified = None
        self.active = True

    @property
    def future(self):
        """See `IAnnouncement`."""
        if self.date_announced is None:
            return True
        return self.date_announced > utc_now()

    @property
    def published(self):
        """See `IAnnouncement`."""
        if self.active is False:
            return False
        return not self.future


class HasAnnouncements:
    """A mixin class for pillars that can have announcements."""

    def getAnnouncement(self, id):
        try:
            announcement_id = int(id)
        except ValueError:
            return None
        announcement = IStore(Announcement).get(Announcement, announcement_id)
        if announcement is None:
            return None
        if announcement.target.name != self.name:
            return None
        return announcement

    def getAnnouncements(self, limit=5, published_only=True):
        """See IHasAnnouncements."""
        from lp.registry.model.product import Product

        # Create the SQL query.
        using = [Announcement]
        query = []
        # Filter for published news items if necessary.
        if published_only:
            query += [
                Announcement.date_announced <= UTC_NOW,
                Announcement.active == True,
            ]
        if IProduct.providedBy(self):
            if self.projectgroup is None:
                query.append(Announcement.product == self.id)
            else:
                query.append(
                    Or(
                        Announcement.product == self.id,
                        Announcement.projectgroup == self.projectgroup,
                    )
                )
        elif IProjectGroup.providedBy(self):
            child_products = Select(
                Product.id,
                And(Product.projectgroup == self, Product.active == True),
            )
            query.append(
                Or(
                    Announcement.projectgroup == self,
                    Announcement.product_id.is_in(child_products),
                )
            )
        elif IDistribution.providedBy(self):
            query.append(Announcement.distribution == self)
        elif IAnnouncementSet.providedBy(self):
            # Just filter out inactive projects, mostly to exclude spam.
            using.append(
                LeftJoin(Product, Product.id == Announcement.product_id)
            )
            query.append(
                Or(Announcement.product == None, Product.active == True)
            )
        else:
            raise AssertionError("Unsupported announcement target")
        store = IStore(Announcement)
        return store.using(*using).find(Announcement, *query)[:limit]


class MakesAnnouncements(HasAnnouncements):
    def announce(
        self, user, title, summary=None, url=None, publication_date=None
    ):
        """See IHasAnnouncements."""

        # We establish the appropriate target property.
        projectgroup = product = distribution = None
        if IProduct.providedBy(self):
            product = self
        elif IProjectGroup.providedBy(self):
            projectgroup = self
        elif IDistribution.providedBy(self):
            distribution = self
        else:
            raise AssertionError("Unsupported announcement target")

        # Create the announcement in the database.
        announcement = Announcement(
            registrant=user,
            title=str(title) if title is not None else None,
            summary=str(summary) if summary is not None else None,
            url=str(url) if url is not None else None,
            product=product,
            projectgroup=projectgroup,
            distribution=distribution,
        )
        store = IPrimaryStore(Announcement)
        store.add(announcement)
        store.flush()

        announcement.setPublicationDate(publication_date)
        return announcement


@implementer(IAnnouncementSet)
class AnnouncementSet(HasAnnouncements):
    """The set of all announcements across all pillars."""

    displayname = "Launchpad-hosted"
    title = "Launchpad"
