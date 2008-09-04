# Copyright 2005 Canonical Ltd.  All rights reserved.
# pylint: disable-msg=E0211,E0213

"""Revision interfaces."""

__metaclass__ = type
__all__ = [
    'IRevision', 'IRevisionAuthor', 'IRevisionParent', 'IRevisionProperty',
    'IRevisionSet']

from zope.interface import Interface, Attribute
from zope.schema import Bool, Datetime, Int, Text, TextLine

from canonical.launchpad import _
from canonical.launchpad.fields import PublicPersonChoice


class IRevision(Interface):
    """Bazaar revision."""

    id = Int(title=_('The database revision ID'))

    date_created = Datetime(
        title=_("Date Created"), required=True, readonly=True)
    log_body = Attribute("The revision log message.")
    revision_author = Attribute("The revision author identifier.")
    gpgkey = Attribute("The OpenPGP key used to sign the revision.")
    revision_id = Attribute("The globally unique revision identifier.")
    revision_date = Datetime(
        title=_("The date the revision was committed."),
        required=True, readonly=True)
    karma_allocated = Bool(
        title=_("Has karma been allocated for this revision?"),
        required=True, default=False)
    parents = Attribute("The RevisionParents for this revision.")
    parent_ids = Attribute("The revision_ids of the parent Revisions.")
    properties = Attribute("The `RevisionProperty`s for this revision.")

    def getProperties():
        """Return the revision properties as a dict."""

    def allocateKarma(branch):
        """Allocate karma to the revision_author for this revision."""

    def getBranch(allow_private=False, allow_junk=True):
        """Return a branch associated with this revision.

        The chances are that there will be many branches with any revision
        that has landed on the trunk branch.  A branch owned by the revision
        author is chosen over a branch not owned by the author.  A branch with
        the revision in the history is chosen over a branch that just has the
        revision in the ancestry.

        :param allow_private: If True, a public or private branch may be
            returned.  Otherwise only a public branch may be returned.
        :param allow_junk: If True junk branches are acceptable, if False,
            only non-junk branches are returned.
        :return: A `Branch` or None if an appropriate branch cannot be found.
        """


class IRevisionAuthor(Interface):
    """Committer of a Bazaar revision."""

    name = TextLine(title=_("Revision Author Name"), required=True)
    name_without_email = Attribute(
        "Revision author name without email address.")
    email = Attribute("The email address extracted from the author text.")
    person = PublicPersonChoice(title=_('Author'), required=False,
        readonly=False, vocabulary='ValidPersonOrTeam')

    def linkToLaunchpadPerson():
        """Attempt to link the revision author to a Launchpad `Person`.

        This method looks to see if the `email` address used in the
        text of `RevisionAuthor.name` has been validated against a
        `Person`.

        :return: True if a valid link is made.
        """


class IRevisionParent(Interface):
    """The association between a revision and its parent revisions."""

    revision = Attribute("The child revision.")
    sequence = Attribute("The order of the parent of that revision.")
    parent_id = Attribute("The revision_id of the parent revision.")


class IRevisionProperty(Interface):
    """A property on a Bazaar revision."""

    revision = Attribute("The revision which has this property.")
    name = TextLine(title=_("The name of the property."), required=True)
    value = Text(title=_("The value of the property."), required=True)


class IRevisionSet(Interface):
    """The set of all revisions."""

    def getByRevisionId(revision_id):
        """Find a revision by revision_id.

        None if the revision is not known.
        """

    def new(revision_id, log_body, revision_date, revision_author,
            parent_ids, properties):
        """Create a new Revision with the given revision ID."""

    def newFromBazaarRevision(bzr_revision):
        """Create a new Revision from the given Bazaar Revision object."""

    def checkNewVerifiedEmail(email):
        """See if this email address has been used to commit revisions.

        If it has, then associate the RevisionAuthor with the Launchpad person
        who owns this email address.
        """

    def getTipRevisionsForBranches(branches):
        """Get the tip branch revisions for the specified branches.

        The revision_authors are prejoined in to reduce the number of
        database queries issued.

        :return: ResultSet containing `Revision` or None if no matching
            revisions found.
        """

    def getRecentRevisionsForProduct(product, days):
        """Get the revisions for product created within so many days.

        In order to get the time the revision was actually created, the time
        extracted from the revision properties is used.  While this may not
        be 100% accurate, it is much more accurate than using date created.
        """

    def getRevisionsNeedingKarmaAllocated():
        """Get the revisions needing karma allocated.

        Under normal circumstances karma is allocated for revisions by the
        branch scanner as it is scanning the revisions.

        There are a number of circumstances where this doesn't happen though:
          * The revision author is not linked to a Launchpad person
          * The branch is +junk

        :return: A ResultSet containing revisions where:
           * karma not allocated
           * revision author linked to a Launchpad person
           * revision in a branch associated with a product
        """

    def getPublicRevisionsForPerson(person, day_limit=30):
        """Get the public revisions for the person or team specified.

        :param person: A person or team.
        :param day_limit: A hard limit for the revision_date.
        :return: ResultSet containing all revisions that are in a public
            branch somewhere where the person is the revision author, or
            the revision author is in the team, where the revision_date is
            within `day_limit` number of days of now.  The results are ordered
            with the most recent revision_date first.
        """

    def getPublicRevisionsForProduct(product, day_limit=30):
        """Get the public revisions for the product specified.

        :param product: A valid `Product`.
        :param day_limit: A hard limit for the revision_date.
        :return: ResultSet containing all revisions that are in a public
            branch associated with the product, where the revision_date is
            within `day_limit` number of days of now.  The results are ordered
            with the most recent revision_date first.
        """

    def getPublicRevisionsForProject(project, day_limit=30):
        """Get the public revisions for the project specified.

        :param project: A valid `Project`.
        :param day_limit: A hard limit for the revision_date.
        :return: ResultSet containing all revisions that are in a public
            branch associated with a product that is associated with the
            project, where the revision_date is within `day_limit` number
            of days of now.  The results are ordered with the most recent
            revision_date first.
        """
