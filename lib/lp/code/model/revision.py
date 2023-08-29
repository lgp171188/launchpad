# Copyright 2009-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "Revision",
    "RevisionAuthor",
    "RevisionCache",
    "RevisionParent",
    "RevisionProperty",
    "RevisionSet",
]

import email
from datetime import datetime, timedelta, timezone
from operator import itemgetter

from breezy.revision import NULL_REVISION
from storm.expr import And, Asc, Desc, Join, Or, Select
from storm.locals import (
    Bool,
    DateTime,
    Int,
    Min,
    Reference,
    ReferenceSet,
    Unicode,
)
from storm.store import Store
from zope.component import getUtility
from zope.interface import implementer
from zope.security.proxy import removeSecurityProxy

from lp.app.enums import PUBLIC_INFORMATION_TYPES
from lp.code.interfaces.branch import DEFAULT_BRANCH_STATUS_IN_LISTING
from lp.code.interfaces.revision import (
    IRevision,
    IRevisionAuthor,
    IRevisionParent,
    IRevisionProperty,
    IRevisionSet,
)
from lp.registry.interfaces.person import validate_public_person
from lp.registry.interfaces.product import IProduct
from lp.registry.interfaces.projectgroup import IProjectGroup
from lp.services.database.bulk import create
from lp.services.database.constants import DEFAULT, UTC_NOW
from lp.services.database.decoratedresultset import DecoratedResultSet
from lp.services.database.interfaces import IPrimaryStore, IStore
from lp.services.database.stormbase import StormBase
from lp.services.helpers import shortlist
from lp.services.identity.interfaces.emailaddress import (
    EmailAddressStatus,
    IEmailAddressSet,
)


@implementer(IRevision)
class Revision(StormBase):
    """See IRevision."""

    __storm_table__ = "Revision"

    id = Int(primary=True)

    date_created = DateTime(
        name="date_created",
        allow_none=False,
        default=DEFAULT,
        tzinfo=timezone.utc,
    )
    log_body = Unicode(name="log_body", allow_none=False)

    revision_author_id = Int(name="revision_author", allow_none=False)
    revision_author = Reference(revision_author_id, "RevisionAuthor.id")

    revision_id = Unicode(name="revision_id", allow_none=False)
    revision_date = DateTime(
        name="revision_date", allow_none=True, tzinfo=timezone.utc
    )

    karma_allocated = Bool(
        name="karma_allocated", default=False, allow_none=False
    )

    properties = ReferenceSet("id", "RevisionProperty.revision_id")

    def __init__(
        self,
        log_body,
        revision_author,
        revision_id,
        revision_date=None,
        date_created=DEFAULT,
    ):
        super().__init__()
        self.log_body = log_body
        self.revision_author = revision_author
        self.revision_id = revision_id
        self.revision_date = revision_date
        self.date_created = date_created

    @property
    def parents(self):
        """See IRevision.parents"""
        return shortlist(
            IStore(RevisionParent)
            .find(RevisionParent, revision=self)
            .order_by(RevisionParent.sequence)
        )

    @property
    def parent_ids(self):
        """Sequence of globally unique ids for the parents of this revision.

        The corresponding Revision objects can be retrieved, if they are
        present in the database, using the RevisionSet Zope utility.
        """
        return [parent.parent_id for parent in self.parents]

    def getLefthandParent(self):
        if len(self.parent_ids) == 0:
            parent_id = NULL_REVISION
        else:
            parent_id = self.parent_ids[0]
        return RevisionSet().getByRevisionId(parent_id)

    def getProperties(self):
        """See `IRevision`."""
        return {prop.name: prop.value for prop in self.properties}

    def allocateKarma(self, branch):
        """See `IRevision`."""
        # Always set karma_allocated to True so that Lp does not reprocess
        # junk and invalid user branches because they do not get karma.
        self.karma_allocated = True
        # If we know who the revision author is, give them karma.
        author = self.revision_author.person
        if author is not None and branch is not None:
            # Backdate the karma to the time the revision was created.  If the
            # revision_date on the revision is in future (for whatever weird
            # reason) we will use the date_created from the revision (which
            # will be now) as the karma date created.  Having future karma
            # events is both wrong, as the revision has been created (and it
            # is lying), and a problem with the way the Launchpad code
            # currently does its karma degradation over time.
            karma_date = min(self.revision_date, self.date_created)
            karma = branch.target.assignKarma(
                author, "revisionadded", karma_date
            )
            return karma
        else:
            return None

    def getBranch(self, allow_private=False, allow_junk=True):
        """See `IRevision`."""
        from lp.code.model.branch import Branch
        from lp.code.model.branchrevision import BranchRevision

        store = Store.of(self)

        query = And(
            self.id == BranchRevision.revision_id,
            BranchRevision.branch_id == Branch.id,
        )
        if not allow_private:
            query = And(
                query, Branch.information_type.is_in(PUBLIC_INFORMATION_TYPES)
            )
        if not allow_junk:
            query = And(
                query,
                # Not-junk branches are either associated with a product
                # or with a source package.
                Or(
                    (Branch.product != None),
                    And(
                        Branch.sourcepackagename != None,
                        Branch.distroseries != None,
                    ),
                ),
            )
        result_set = store.find(Branch, query)
        if self.revision_author.person is None:
            result_set.order_by(Asc(BranchRevision.sequence))
        else:
            result_set.order_by(
                Branch.owner_id != self.revision_author.person_id,
                Asc(BranchRevision.sequence),
            )

        return result_set.first()


@implementer(IRevisionAuthor)
class RevisionAuthor(StormBase):
    __storm_table__ = "RevisionAuthor"

    id = Int(primary=True)

    name = Unicode(name="name", allow_none=False)

    email = Unicode(name="email", allow_none=True, default=None)

    person_id = Int(
        name="person",
        allow_none=True,
        validator=validate_public_person,
        default=None,
    )
    person = Reference(person_id, "Person.id")

    def __init__(self, name, email=None):
        super().__init__()
        self.name = name
        self.email = email

    @property
    def name_without_email(self):
        """Return the name of the revision author without the email address.

        If there is no name information (i.e. when the revision author only
        supplied their email address), return None.
        """
        if "@" not in self.name:
            return self.name
        return email.utils.parseaddr(self.name)[0]

    def linkToLaunchpadPerson(self):
        """See `IRevisionAuthor`."""
        if self.person is not None or self.email is None:
            return False
        lp_email = getUtility(IEmailAddressSet).getByEmail(self.email)
        # If not found, we didn't link this person.
        if lp_email is None:
            return False
        # Only accept an email address that is validated.
        if lp_email.status != EmailAddressStatus.NEW:
            self.person_id = lp_email.person_id
            return True
        else:
            return False


@implementer(IRevisionParent)
class RevisionParent(StormBase):
    """The association between a revision and its parent."""

    __storm_table__ = "RevisionParent"

    id = Int(primary=True)

    revision_id = Int(name="revision", allow_none=False)
    revision = Reference(revision_id, "Revision.id")

    sequence = Int(allow_none=False)
    parent_id = Unicode(allow_none=False)

    def __init__(self, revision, sequence, parent_id):
        super().__init__()
        self.revision = revision
        self.sequence = sequence
        self.parent_id = parent_id


@implementer(IRevisionProperty)
class RevisionProperty(StormBase):
    """A property on a revision. See IRevisionProperty."""

    __storm_table__ = "RevisionProperty"

    id = Int(primary=True)

    revision_id = Int(name="revision", allow_none=False)
    revision = Reference(revision_id, "Revision.id")

    name = Unicode(allow_none=False)
    value = Unicode(allow_none=False)

    def __init__(self, revision, name, value):
        super().__init__()
        self.revision = revision
        self.name = name
        self.value = value


@implementer(IRevisionSet)
class RevisionSet:
    def getByRevisionId(self, revision_id):
        return IStore(Revision).find(Revision, revision_id=revision_id).one()

    def _createRevisionAuthor(self, revision_author):
        """Extract out the email and check to see if it matches a Person."""
        email_address = email.utils.parseaddr(revision_author)[1]
        # If there is no @, then it isn't a real email address.
        if "@" not in email_address:
            email_address = None

        store = IPrimaryStore(RevisionAuthor)
        author = RevisionAuthor(name=revision_author, email=email_address)
        store.add(author)
        author.linkToLaunchpadPerson()
        store.flush()
        return author

    def new(
        self,
        revision_id,
        log_body,
        revision_date,
        revision_author,
        parent_ids,
        properties,
        _date_created=None,
    ):
        """See IRevisionSet.new()"""
        if properties is None:
            properties = {}
        if _date_created is None:
            _date_created = UTC_NOW
        authors = self.acquireRevisionAuthors([revision_author])

        revision = Revision(
            revision_id=revision_id,
            log_body=log_body,
            revision_date=revision_date,
            revision_author=authors[revision_author],
            date_created=_date_created,
        )
        # Don't create future revisions.
        if revision.revision_date > revision.date_created:
            revision.revision_date = revision.date_created

        seen_parents = set()
        for sequence, parent_id in enumerate(parent_ids):
            if parent_id in seen_parents:
                continue
            seen_parents.add(parent_id)
            RevisionParent(
                revision=revision, sequence=sequence, parent_id=parent_id
            )

        # Create revision properties.
        for name, value in properties.items():
            RevisionProperty(revision=revision, name=name, value=value)

        return revision

    def acquireRevisionAuthors(self, author_names):
        """Find or create the RevisionAuthors with the specified names.

        A name may be any arbitrary string, but if it is an email-id, and
        its email address is a verified email address, it will be
        automatically linked to the corresponding Person.

        Email-ids come in two major forms:
            "Foo Bar" <foo@bar.com>
            foo@bar.com (Foo Bar)
        :return: a dict of name -> RevisionAuthor
        """
        store = IPrimaryStore(Revision)
        author_names = set(author_names)
        authors = {}
        for author in store.find(
            RevisionAuthor, RevisionAuthor.name.is_in(author_names)
        ):
            authors[author.name] = author
        missing = author_names - set(authors.keys())
        # create missing RevisionAuthors
        for name in missing:
            authors[name] = self._createRevisionAuthor(name)
        return authors

    def _timestampToDatetime(self, timestamp):
        """Convert the given timestamp to a datetime object.

        This works around a bug in Python that causes datetime.fromtimestamp
        to raise an exception if it is given a negative, fractional timestamp.

        :param timestamp: A timestamp from a breezy.revision.Revision
        :type timestamp: float

        :return: A datetime corresponding to the given timestamp.
        """
        # Work around Python bug #1646728.
        # See https://launchpad.net/bugs/81544.
        int_timestamp = int(timestamp)
        revision_date = datetime.fromtimestamp(int_timestamp, tz=timezone.utc)
        revision_date += timedelta(seconds=timestamp - int_timestamp)
        return revision_date

    def newFromBazaarRevisions(self, revisions):
        """See `IRevisionSet`."""

        # Find all author names for these revisions.
        author_names = []
        for bzr_revision in revisions:
            authors = bzr_revision.get_apparent_authors()
            try:
                author = authors[0]
            except IndexError:
                author = None
            author_names.append(author)
        # Get or make every RevisionAuthor for these revisions.
        revision_authors = {
            name: author.id
            for name, author in self.acquireRevisionAuthors(
                author_names
            ).items()
        }

        # Collect all data for making Revision objects.
        data = []
        for bzr_revision, author_name in zip(revisions, author_names):
            revision_id = bzr_revision.revision_id.decode()
            revision_date = self._timestampToDatetime(bzr_revision.timestamp)
            revision_author = revision_authors[author_name]

            data.append(
                (
                    revision_id,
                    bzr_revision.message,
                    revision_date,
                    revision_author,
                )
            )
        # Create all Revision objects.
        db_revisions = create(
            (
                Revision.revision_id,
                Revision.log_body,
                Revision.revision_date,
                Revision.revision_author_id,
            ),
            data,
            get_objects=True,
        )

        # Map revision_id to Revision database ID.
        revision_db_id = {rev.revision_id: rev.id for rev in db_revisions}

        # Collect all data for making RevisionParent and RevisionProperty
        # objects.
        parent_data = []
        property_data = []
        for bzr_revision in revisions:
            db_id = revision_db_id[bzr_revision.revision_id.decode()]
            # Property data: revision DB id, name, value.
            for name, value in bzr_revision.properties.items():
                # pristine-tar properties can be huge, and storing them
                # in the database provides no value. Exclude them.
                if name.startswith("deb-pristine-delta"):
                    continue
                property_data.append((db_id, name, value))
            parent_ids = [
                parent_id.decode() for parent_id in bzr_revision.parent_ids
            ]
            # Parent data: revision DB id, sequence, revision_id
            seen_parents = set()
            for sequence, parent_id in enumerate(parent_ids):
                if parent_id in seen_parents:
                    continue
                seen_parents.add(parent_id)
                parent_data.append((db_id, sequence, parent_id))
        # Create all RevisionParent objects.
        create(
            (
                RevisionParent.revision_id,
                RevisionParent.sequence,
                RevisionParent.parent_id,
            ),
            parent_data,
        )

        # Create all RevisionProperty objects.
        create(
            (
                RevisionProperty.revision_id,
                RevisionProperty.name,
                RevisionProperty.value,
            ),
            property_data,
        )

    @staticmethod
    def onlyPresent(revids):
        """See `IRevisionSet`."""
        store = IStore(Revision)
        clause = Revision.revision_id.is_in(revids)
        present = store.find(Revision.revision_id, clause)
        return set(present)

    def getTipRevisionsForBranches(self, branches):
        """See `IRevisionSet`."""
        # Circular import.
        from lp.code.model.branch import Branch

        # If there are no branch_ids, then return None.
        branch_ids = [branch.id for branch in branches]
        if not branch_ids:
            return None
        return DecoratedResultSet(
            IStore(Revision).find(
                (Revision, RevisionAuthor),
                Branch.id.is_in(branch_ids),
                Revision.revision_id == Branch.last_scanned_id,
                Revision.revision_author_id == RevisionAuthor.id,
            ),
            result_decorator=itemgetter(0),
        )

    @staticmethod
    def getRecentRevisionsForProduct(product, days):
        """See `IRevisionSet`."""
        # Here to stop circular imports.
        from lp.code.model.branch import Branch
        from lp.code.model.branchrevision import BranchRevision

        revision_subselect = Select(
            Min(Revision.id), revision_time_limit(days)
        )
        # Only look in active branches.
        result_set = Store.of(product).find(
            (Revision, RevisionAuthor),
            Revision.revision_author == RevisionAuthor.id,
            revision_time_limit(days),
            BranchRevision.revision == Revision.id,
            BranchRevision.branch == Branch.id,
            Branch.product == product,
            Branch.lifecycle_status.is_in(DEFAULT_BRANCH_STATUS_IN_LISTING),
            BranchRevision.revision_id >= revision_subselect,
        )
        result_set.config(distinct=True)
        return result_set.order_by(Desc(Revision.revision_date))

    @staticmethod
    def getRevisionsNeedingKarmaAllocated(limit=None):
        """See `IRevisionSet`."""
        store = IStore(Revision)
        results = store.find(Revision, Revision.karma_allocated == False)[
            :limit
        ]
        return results

    @staticmethod
    def getPublicRevisionsForPerson(person, day_limit=30):
        """See `IRevisionSet`."""
        # Here to stop circular imports.
        from lp.code.model.branch import Branch
        from lp.code.model.branchrevision import BranchRevision
        from lp.registry.model.teammembership import TeamParticipation

        store = Store.of(person)

        origin = [
            Revision,
            Join(BranchRevision, BranchRevision.revision == Revision.id),
            Join(Branch, BranchRevision.branch == Branch.id),
            Join(
                RevisionAuthor, Revision.revision_author == RevisionAuthor.id
            ),
        ]

        if person.is_team:
            origin.append(
                Join(
                    TeamParticipation,
                    RevisionAuthor.person_id == TeamParticipation.person_id,
                )
            )
            person_condition = TeamParticipation.team == person
        else:
            person_condition = RevisionAuthor.person == person

        result_set = store.using(*origin).find(
            Revision,
            And(
                revision_time_limit(day_limit),
                person_condition,
                Branch.information_type.is_in(PUBLIC_INFORMATION_TYPES),
            ),
        )
        result_set.config(distinct=True)
        return result_set.order_by(Desc(Revision.revision_date))

    @staticmethod
    def _getPublicRevisionsHelper(obj, day_limit):
        """Helper method for Products and ProjectGroups."""
        # Here to stop circular imports.
        from lp.code.model.branch import Branch
        from lp.code.model.branchrevision import BranchRevision
        from lp.registry.model.product import Product

        origin = [
            Revision,
            Join(BranchRevision, BranchRevision.revision == Revision.id),
            Join(Branch, BranchRevision.branch == Branch.id),
        ]

        conditions = And(
            revision_time_limit(day_limit),
            Branch.information_type.is_in(PUBLIC_INFORMATION_TYPES),
        )

        if IProduct.providedBy(obj):
            conditions = And(conditions, Branch.product == obj)
        elif IProjectGroup.providedBy(obj):
            origin.append(Join(Product, Branch.product == Product.id))
            conditions = And(conditions, Product.projectgroup == obj)
        else:
            raise AssertionError("Not an IProduct or IProjectGroup: %r" % obj)

        result_set = Store.of(obj).using(*origin).find(Revision, conditions)
        result_set.config(distinct=True)
        return result_set.order_by(Desc(Revision.revision_date))

    @classmethod
    def getPublicRevisionsForProduct(cls, product, day_limit=30):
        """See `IRevisionSet`."""
        return cls._getPublicRevisionsHelper(product, day_limit)

    @classmethod
    def getPublicRevisionsForProjectGroup(cls, project, day_limit=30):
        """See `IRevisionSet`."""
        return cls._getPublicRevisionsHelper(project, day_limit)

    @staticmethod
    def updateRevisionCacheForBranch(branch):
        """See `IRevisionSet`."""
        # Hand crafting the sql insert statement as storm doesn't handle the
        # INSERT INTO ... SELECT ... syntax.  Also there is no public api yet
        # for storm to get the select statement.

        # Remove the security proxy to get access to the ID columns.
        naked_branch = removeSecurityProxy(branch)

        insert_columns = ["Revision.id", "revision_author", "revision_date"]
        subselect_clauses = []
        if branch.product is None:
            insert_columns.append("NULL")
            subselect_clauses.append("product IS NULL")
        else:
            insert_columns.append(str(naked_branch.product_id))
            subselect_clauses.append("product = %s" % naked_branch.product_id)

        if branch.distroseries is None:
            insert_columns.extend(["NULL", "NULL"])
            subselect_clauses.extend(
                ["distroseries IS NULL", "sourcepackagename IS NULL"]
            )
        else:
            insert_columns.extend(
                [
                    str(naked_branch.distroseries_id),
                    str(naked_branch.sourcepackagename_id),
                ]
            )
            subselect_clauses.extend(
                [
                    "distroseries = %s" % naked_branch.distroseries_id,
                    "sourcepackagename = %s"
                    % naked_branch.sourcepackagename_id,
                ]
            )

        insert_columns.append(str(branch.private))
        if branch.private:
            subselect_clauses.append("private IS TRUE")
        else:
            subselect_clauses.append("private IS FALSE")

        insert_statement = """
            INSERT INTO RevisionCache
            (revision, revision_author, revision_date,
             product, distroseries, sourcepackagename, private)
            SELECT %(columns)s FROM Revision
            JOIN BranchRevision ON BranchRevision.revision = Revision.id
            WHERE Revision.revision_date > (
                CURRENT_TIMESTAMP AT TIME ZONE 'UTC' - interval '30 days')
            AND BranchRevision.branch = %(branch_id)s
            AND Revision.id NOT IN (
                SELECT revision FROM RevisionCache
                WHERE %(subselect_where)s)
            """ % {
            "columns": ", ".join(insert_columns),
            "branch_id": branch.id,
            "subselect_where": " AND ".join(subselect_clauses),
        }
        Store.of(branch).execute(insert_statement)

    @staticmethod
    def pruneRevisionCache(limit):
        """See `IRevisionSet`."""
        # Storm doesn't handle remove a limited result set:
        #    FeatureError: Can't remove a sliced result set
        store = IPrimaryStore(RevisionCache)
        epoch = datetime.now(tz=timezone.utc) - timedelta(days=30)
        subquery = Select(
            [RevisionCache.id],
            RevisionCache.revision_date < epoch,
            limit=limit,
        )
        store.find(RevisionCache, RevisionCache.id.is_in(subquery)).remove()


def revision_time_limit(day_limit):
    """The storm fragment to limit the revision_date field of the Revision."""
    now = datetime.now(timezone.utc)
    earliest = now - timedelta(days=day_limit)

    return And(
        Revision.revision_date <= now, Revision.revision_date > earliest
    )


class RevisionCache(StormBase):
    """A cached version of a recent revision."""

    __storm_table__ = "RevisionCache"

    id = Int(primary=True)

    revision_id = Int(name="revision", allow_none=False)
    revision = Reference(revision_id, "Revision.id")

    revision_author_id = Int(name="revision_author", allow_none=False)
    revision_author = Reference(revision_author_id, "RevisionAuthor.id")

    revision_date = DateTime(allow_none=False, tzinfo=timezone.utc)

    product_id = Int(name="product", allow_none=True)
    product = Reference(product_id, "Product.id")

    distroseries_id = Int(name="distroseries", allow_none=True)
    distroseries = Reference(distroseries_id, "DistroSeries.id")

    sourcepackagename_id = Int(name="sourcepackagename", allow_none=True)
    sourcepackagename = Reference(sourcepackagename_id, "SourcePackageName.id")

    private = Bool(allow_none=False, default=False)

    def __init__(self, revision):
        # Make the revision_author assignment first as traversing to the
        # revision_author of the revision does a query which causes a store
        # flush.  If an assignment has been done already, the RevisionCache
        # object would have been implicitly added to the store, and fails
        # with an integrity check.
        self.revision_author = revision.revision_author
        self.revision = revision
        self.revision_date = revision.revision_date
