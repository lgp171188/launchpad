# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""NameBlocklist interfaces."""

__all__ = [
    "INameBlocklist",
    "INameBlocklistSet",
]

from zope.interface import Interface
from zope.schema import Choice, Int, Text, TextLine

from lp import _


class INameBlocklist(Interface):
    """The interface for the NameBlocklist table."""

    id = Int(title=_("ID"), required=True, readonly=True)
    regexp = TextLine(title=_("Regular expression"), required=True)
    comment = Text(
        title=_("Comment"),
        description=_(
            "Why is the name blocklisted? Does the namespace belong to an "
            "organization or is the namespace reserved by the application?"
        ),
        required=False,
    )
    admin = Choice(
        title=_("Admin"),
        description=_(
            "The team that is exempt from this restriction because it "
            "administers this namespace for an organisation."
        ),
        vocabulary="ValidPersonOrTeam",
        required=False,
    )


class INameBlocklistSet(Interface):
    """The set of INameBlocklist objects."""

    def getAll():
        """Return all the name blocklist expressions."""

    def create(regexp, comment=None):
        """Create and return a new NameBlocklist with given arguments."""

    def get(id):
        """Return the NameBlocklist with the given id or None."""

    def getByRegExp(regexp):
        """Return the NameBlocklist with the given regexp or None."""
