# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Classes to represent external packages in a distribution."""

__all__ = [
    "ExternalPackage",
]

from zope.interface import implementer

from lp.bugs.model.bugtarget import BugTargetBase
from lp.bugs.model.structuralsubscription import (
    StructuralSubscriptionTargetMixin,
)
from lp.registry.interfaces.externalpackage import IExternalPackage
from lp.registry.model.hasdrivers import HasDriversMixin
from lp.services.propertycache import cachedproperty

CHANNEL_FIELDS = ("track", "risk", "branch")


class ChannelFieldException(Exception):
    """Channel fields are strings.
    Track and Risk are required, Branch is optional.
    """


@implementer(IExternalPackage)
class ExternalPackage(
    BugTargetBase,
    HasDriversMixin,
    StructuralSubscriptionTargetMixin,
):
    """This is a "Magic External Package". It is not a Storm model, but instead
    it represents a package with a particular name, type and channel in a
    particular distribution.
    """

    def __init__(self, distribution, sourcepackagename, packagetype, channel):
        self.distribution = distribution
        self.sourcepackagename = sourcepackagename
        self.packagetype = packagetype

        self.channel = self.validate_channel(channel)

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} '{self.display_name}'>"

    def validate_channel(self, channel: dict) -> str:
        if channel is None:
            return None
        if not isinstance(channel, dict):
            raise ChannelFieldException("Channel should be a dict")
        if "track" not in channel:
            raise ChannelFieldException("Track is a required field in channel")
        if "risk" not in channel:
            raise ChannelFieldException("Risk is a required field in channel")

        for k, v in channel.items():
            if k not in CHANNEL_FIELDS:
                raise ChannelFieldException(
                    f"{k} is not part of {CHANNEL_FIELDS}"
                )
            if not isinstance(v, str):
                raise ChannelFieldException(
                    "All channel fields should be a string"
                )
        return channel

    @property
    def name(self):
        """See `IExternalPackage`."""
        return self.sourcepackagename.name

    @property
    def display_channel(self):
        """See `IExternalPackage`."""
        if not self.channel:
            return None

        channel_list = [self.channel.get("track"), self.channel.get("risk")]
        if (branch := self.channel.get("branch", "")) != "":
            channel_list.append(branch)

        return "/".join(channel_list)

    @cachedproperty
    def display_name(self):
        """See `IExternalPackage`."""
        if self.channel:
            return "%s - %s @%s in %s" % (
                self.sourcepackagename.name,
                self.packagetype,
                self.display_channel,
                self.distribution.display_name,
            )

        return "%s - %s in %s" % (
            self.sourcepackagename.name,
            self.packagetype,
            self.distribution.display_name,
        )

    # There are different places of launchpad codebase where they use different
    # display names
    @property
    def displayname(self):
        """See `IExternalPackage`."""
        return self.display_name

    @property
    def bugtargetdisplayname(self):
        """See `IExternalPackage`."""
        return self.display_name

    @property
    def bugtargetname(self):
        """See `IExternalPackage`."""
        return self.display_name

    @property
    def title(self):
        """See `IExternalPackage`."""
        return self.display_name

    def __eq__(self, other):
        """See `IExternalPackage`."""
        return (
            (IExternalPackage.providedBy(other))
            and (self.distribution.id == other.distribution.id)
            and (self.sourcepackagename.id == other.sourcepackagename.id)
            and (self.packagetype == other.packagetype)
            and (self.channel == other.channel)
        )

    def __hash__(self):
        """Return the combined attributes hash."""
        return hash(
            (
                self.distribution,
                self.sourcepackagename,
                self.packagetype,
                self.display_channel,
            )
        )

    @property
    def drivers(self):
        """See `IHasDrivers`."""
        return self.distribution.drivers

    @property
    def official_bug_tags(self):
        """See `IHasBugs`."""
        return self.distribution.official_bug_tags

    @property
    def pillar(self):
        """See `IBugTarget`."""
        return self.distribution

    def _getOfficialTagClause(self):
        """See `IBugTarget`."""
        return self.distribution._getOfficialTagClause()
