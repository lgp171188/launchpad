# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "Sprint",
    "SprintSet",
    "HasSprintsMixin",
]

from datetime import timezone

from storm.locals import (
    Bool,
    DateTime,
    Desc,
    Int,
    Join,
    Or,
    Reference,
    Store,
    Unicode,
)
from zope.component import getUtility
from zope.interface import implementer

from lp.app.interfaces.launchpad import (
    IHasIcon,
    IHasLogo,
    IHasMugshot,
    ILaunchpadCelebrities,
)
from lp.blueprints.enums import (
    SpecificationFilter,
    SpecificationSort,
    SprintSpecificationStatus,
)
from lp.blueprints.interfaces.sprint import ISprint, ISprintSet
from lp.blueprints.model.specification import (
    HasSpecificationsMixin,
    Specification,
)
from lp.blueprints.model.specificationsearch import (
    get_specification_active_product_filter,
    get_specification_filters,
    get_specification_privacy_filter,
)
from lp.blueprints.model.sprintattendance import SprintAttendance
from lp.blueprints.model.sprintspecification import SprintSpecification
from lp.registry.interfaces.person import IPersonSet, validate_public_person
from lp.registry.model.hasdrivers import HasDriversMixin
from lp.services.database.constants import DEFAULT, UTC_NOW
from lp.services.database.interfaces import IStore
from lp.services.database.sqlbase import flush_database_updates
from lp.services.database.stormbase import StormBase
from lp.services.propertycache import cachedproperty


@implementer(ISprint, IHasLogo, IHasMugshot, IHasIcon)
class Sprint(StormBase, HasDriversMixin, HasSpecificationsMixin):
    """See `ISprint`."""

    __storm_table__ = "Sprint"
    __storm_order__ = ["name"]

    # db field names
    id = Int(primary=True)
    owner_id = Int(
        name="owner", validator=validate_public_person, allow_none=False
    )
    owner = Reference(owner_id, "Person.id")
    name = Unicode(allow_none=False)
    title = Unicode(allow_none=False)
    summary = Unicode(allow_none=False)
    driver_id = Int(name="driver", validator=validate_public_person)
    driver = Reference(driver_id, "Person.id")
    home_page = Unicode(allow_none=True, default=None)
    homepage_content = Unicode(default=None)
    icon_id = Int(name="icon", default=None)
    icon = Reference(icon_id, "LibraryFileAlias.id")
    logo_id = Int(name="logo", default=None)
    logo = Reference(logo_id, "LibraryFileAlias.id")
    mugshot_id = Int(name="mugshot", default=None)
    mugshot = Reference(mugshot_id, "LibraryFileAlias.id")
    address = Unicode(allow_none=True, default=None)
    datecreated = DateTime(
        tzinfo=timezone.utc, allow_none=False, default=DEFAULT
    )
    time_zone = Unicode(allow_none=False)
    time_starts = DateTime(tzinfo=timezone.utc, allow_none=False)
    time_ends = DateTime(tzinfo=timezone.utc, allow_none=False)
    is_physical = Bool(allow_none=False, default=True)

    def __init__(
        self,
        owner,
        name,
        title,
        time_zone,
        time_starts,
        time_ends,
        summary,
        address=None,
        driver=None,
        home_page=None,
        mugshot=None,
        logo=None,
        icon=None,
        is_physical=True,
    ):
        super().__init__()
        self.owner = owner
        self.name = name
        self.title = title
        self.time_zone = time_zone
        self.time_starts = time_starts
        self.time_ends = time_ends
        self.summary = summary
        self.address = address
        self.driver = driver
        self.home_page = home_page
        self.mugshot = mugshot
        self.logo = logo
        self.icon = icon
        self.is_physical = is_physical

    # attributes

    # we want to use this with templates that can assume a displayname,
    # because in many ways a sprint behaves just like a project or a
    # product - it has specs
    @property
    def displayname(self):
        return self.title

    @property
    def drivers(self):
        """See IHasDrivers."""
        if self.driver is not None:
            return [self.driver, self.owner]
        return [self.owner]

    @property
    def attendees(self):
        # Only really used in tests.
        return [a.attendee for a in self.attendances]

    def spec_filter_clause(self, user, filter=None):
        """Figure out the appropriate query for specifications on a sprint.

        We separate out the query generation from the normal
        specifications() method because we want to reuse this query in the
        specificationLinks() method.
        """
        # Avoid circular imports.
        from lp.blueprints.model.specification import Specification

        tables, query = get_specification_active_product_filter(self)
        tables.insert(0, Specification)
        query.append(get_specification_privacy_filter(user))
        tables.append(
            Join(
                SprintSpecification,
                SprintSpecification.specification == Specification.id,
            )
        )
        query.append(SprintSpecification.sprint == self)

        if not filter:
            # filter could be None or [] then we decide the default
            # which for a sprint is to show everything approved
            filter = [SpecificationFilter.ACCEPTED]

        # figure out what set of specifications we are interested in. for
        # sprint, we need to be able to filter on the basis of:
        #
        #  - completeness.
        #  - acceptance for sprint agenda.
        #  - informational.
        #

        sprint_status = []
        # look for specs that have a particular SprintSpecification
        # status (proposed, accepted or declined)
        if SpecificationFilter.ACCEPTED in filter:
            sprint_status.append(SprintSpecificationStatus.ACCEPTED)
        if SpecificationFilter.PROPOSED in filter:
            sprint_status.append(SprintSpecificationStatus.PROPOSED)
        if SpecificationFilter.DECLINED in filter:
            sprint_status.append(SprintSpecificationStatus.DECLINED)
        statuses = [
            SprintSpecification.status == status for status in sprint_status
        ]
        if len(statuses) > 0:
            query.append(Or(*statuses))
        # Filter for specification text
        query.extend(get_specification_filters(filter, goalstatus=False))
        return tables, query

    def all_specifications(self, user):
        return self.specifications(user, filter=[SpecificationFilter.ALL])

    def specifications(
        self,
        user,
        sort=None,
        quantity=None,
        filter=None,
        need_people=False,
        need_branches=False,
        need_workitems=False,
    ):
        """See IHasSpecifications."""
        # need_* is provided only for interface compatibility and
        # need_*=True is not implemented.
        if filter is None:
            filter = {SpecificationFilter.ACCEPTED}
        tables, query = self.spec_filter_clause(user, filter)
        # import here to avoid circular deps
        from lp.blueprints.model.specification import Specification

        results = Store.of(self).using(*tables).find(Specification, *query)
        if sort == SpecificationSort.DATE:
            order = (Desc(SprintSpecification.date_created), Specification.id)
            distinct = [SprintSpecification.date_created, Specification.id]
            # we need to establish if the listing will show specs that have
            # been decided only, or will include proposed specs.
            if (
                SpecificationFilter.ALL not in filter
                and SpecificationFilter.PROPOSED not in filter
            ):
                # this will show only decided specs so use the date the spec
                # was accepted or declined for the sprint
                order = (Desc(SprintSpecification.date_decided),) + order
                distinct = [SprintSpecification.date_decided] + distinct
            results = results.order_by(*order)
        else:
            assert sort is None or sort == SpecificationSort.PRIORITY
            # fall back to default, which is priority, descending.
            distinct = True
        if quantity is not None:
            results = results[:quantity]
        return results.config(distinct=distinct)

    def specificationLinks(self, filter=None):
        """See `ISprint`."""
        tables, query = self.spec_filter_clause(None, filter=filter)
        t_set = Store.of(self).using(*tables)
        return t_set.find(SprintSpecification, *query).config(distinct=True)

    def getSpecificationLink(self, speclink_id):
        """See `ISprint`.

        NB: we expose the horrible speclink.id because there is no unique
        way to refer to a specification outside of a product or distro
        context. Here we are a sprint that could cover many products and/or
        distros.
        """
        speclink = Store.of(self).get(SprintSpecification, speclink_id)
        assert speclink.sprint.id == self.id
        return speclink

    def acceptSpecificationLinks(self, idlist, decider):
        """See `ISprint`."""
        for sprintspec in idlist:
            speclink = self.getSpecificationLink(sprintspec)
            speclink.acceptBy(decider)

        # we need to flush all the changes we have made to disk, then try
        # the query again to see if we have any specs remaining in this
        # queue
        flush_database_updates()

        return self.specifications(
            decider, filter=[SpecificationFilter.PROPOSED]
        ).count()

    def declineSpecificationLinks(self, idlist, decider):
        """See `ISprint`."""
        for sprintspec in idlist:
            speclink = self.getSpecificationLink(sprintspec)
            speclink.declineBy(decider)

        # we need to flush all the changes we have made to disk, then try
        # the query again to see if we have any specs remaining in this
        # queue
        flush_database_updates()

        return self.specifications(
            decider, filter=[SpecificationFilter.PROPOSED]
        ).count()

    # attendance
    def attend(self, person, time_starts, time_ends, is_physical):
        """See `ISprint`."""
        # First see if a relevant attendance exists, and if so, update it.
        attendance = (
            Store.of(self)
            .find(
                SprintAttendance,
                SprintAttendance.sprint == self,
                SprintAttendance.attendee == person,
            )
            .one()
        )
        if attendance is None:
            # Since no previous attendance existed, create a new one.
            attendance = SprintAttendance(sprint=self, attendee=person)
        attendance.time_starts = time_starts
        attendance.time_ends = time_ends
        attendance._is_physical = is_physical
        return attendance

    def removeAttendance(self, person):
        """See `ISprint`."""
        Store.of(self).find(
            SprintAttendance,
            SprintAttendance.sprint == self,
            SprintAttendance.attendee == person,
        ).remove()

    @property
    def attendances(self):
        result = list(
            Store.of(self).find(
                SprintAttendance, SprintAttendance.sprint == self
            )
        )
        people = [a.attendeeID for a in result]
        # In order to populate the person cache we need to materialize the
        # result set.  Listification should do.
        list(
            getUtility(IPersonSet).getPrecachedPersonsFromIDs(
                people, need_validity=True
            )
        )
        return sorted(result, key=lambda a: a.attendee.displayname.lower())

    def isDriver(self, user):
        """See `ISprint`."""
        admins = getUtility(ILaunchpadCelebrities).admin
        return (
            user.inTeam(self.owner)
            or user.inTeam(self.driver)
            or user.inTeam(admins)
        )

    def destroySelf(self):
        Store.of(self).find(
            SprintSpecification, SprintSpecification.sprint == self
        ).remove()
        Store.of(self).find(
            SprintAttendance, SprintAttendance.sprint == self
        ).remove()
        Store.of(self).remove(self)


@implementer(ISprintSet)
class SprintSet:
    """The set of sprints."""

    def __init__(self):
        """See `ISprintSet`."""
        self.title = "Sprints and meetings"

    def __getitem__(self, name):
        """See `ISprintSet`."""
        return IStore(Sprint).find(Sprint, name=name).one()

    def __iter__(self):
        """See `ISprintSet`."""
        return iter(
            IStore(Sprint)
            .find(Sprint, Sprint.time_ends > UTC_NOW)
            .order_by(Sprint.time_starts)
        )

    @property
    def all(self):
        return IStore(Sprint).find(Sprint).order_by(Sprint.time_starts)

    def new(
        self,
        owner,
        name,
        title,
        time_zone,
        time_starts,
        time_ends,
        summary,
        address=None,
        driver=None,
        home_page=None,
        mugshot=None,
        logo=None,
        icon=None,
        is_physical=True,
    ):
        """See `ISprintSet`."""
        return Sprint(
            owner=owner,
            name=name,
            title=title,
            time_zone=time_zone,
            time_starts=time_starts,
            time_ends=time_ends,
            summary=summary,
            driver=driver,
            home_page=home_page,
            mugshot=mugshot,
            icon=icon,
            logo=logo,
            address=address,
            is_physical=is_physical,
        )


class HasSprintsMixin:
    """A mixin class implementing the common methods for any class
    implementing IHasSprints.
    """

    def _getBaseClausesForQueryingSprints(self):
        """Return the base Storm clauses to be used when querying sprints
        related to this object.

        Subclasses must overwrite this method if it doesn't suit them.
        """
        try:
            table = getattr(self, "__storm_table__")
        except AttributeError:
            # XXX cjwatson 2020-09-10: Remove this once all inheritors have
            # been converted from SQLObject to Storm.
            table = getattr(self, "_table")
        return [
            getattr(Specification, table.lower()) == self,
            Specification.id == SprintSpecification.specification_id,
            SprintSpecification.sprint == Sprint.id,
            SprintSpecification.status == SprintSpecificationStatus.ACCEPTED,
        ]

    def getSprints(self):
        clauses = self._getBaseClausesForQueryingSprints()
        return (
            IStore(Sprint)
            .find(Sprint, *clauses)
            .order_by(Desc(Sprint.time_starts))
            .config(distinct=True)
        )

    @cachedproperty
    def sprints(self):
        """See IHasSprints."""
        return list(self.getSprints())

    def getComingSprints(self):
        clauses = self._getBaseClausesForQueryingSprints()
        clauses.append(Sprint.time_ends > UTC_NOW)
        return (
            IStore(Sprint)
            .find(Sprint, *clauses)
            .order_by(Sprint.time_starts)
            .config(distinct=True, limit=5)
        )

    @cachedproperty
    def coming_sprints(self):
        """See IHasSprints."""
        return list(self.getComingSprints())

    @property
    def past_sprints(self):
        """See IHasSprints."""
        clauses = self._getBaseClausesForQueryingSprints()
        clauses.append(Sprint.time_ends <= UTC_NOW)
        return (
            IStore(Sprint)
            .find(Sprint, *clauses)
            .order_by(Desc(Sprint.time_starts))
            .config(distinct=True)
        )
