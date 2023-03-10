# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""The content classes for links from source packages to branches.."""

__all__ = [
    "SeriesSourcePackageBranch",
    "SeriesSourcePackageBranchSet",
]

from datetime import datetime, timezone

from storm.locals import DateTime, Int, Reference
from zope.interface import implementer

from lp.code.interfaces.seriessourcepackagebranch import (
    IFindOfficialBranchLinks,
    ISeriesSourcePackageBranch,
)
from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.services.database.enumcol import DBEnum
from lp.services.database.interfaces import IPrimaryStore, IStore
from lp.services.database.stormbase import StormBase


@implementer(ISeriesSourcePackageBranch)
class SeriesSourcePackageBranch(StormBase):
    """See `ISeriesSourcePackageBranch`."""

    __storm_table__ = "SeriesSourcePackageBranch"

    id = Int(primary=True)
    distroseriesID = Int("distroseries")
    distroseries = Reference(distroseriesID, "DistroSeries.id")

    pocket = DBEnum(enum=PackagePublishingPocket)

    sourcepackagenameID = Int("sourcepackagename")
    sourcepackagename = Reference(sourcepackagenameID, "SourcePackageName.id")

    branchID = Int("branch")
    branch = Reference(branchID, "Branch.id")

    registrantID = Int("registrant")
    registrant = Reference(registrantID, "Person.id")

    date_created = DateTime(allow_none=False)

    def __init__(
        self,
        distroseries,
        pocket,
        sourcepackagename,
        branch,
        registrant,
        date_created,
    ):
        """Construct an `ISeriesSourcePackageBranch`."""
        self.distroseries = distroseries
        self.pocket = pocket
        self.sourcepackagename = sourcepackagename
        self.branch = branch
        self.registrant = registrant
        self.date_created = date_created

    @property
    def sourcepackage(self):
        return self.distroseries.getSourcePackage(self.sourcepackagename)

    @property
    def suite_sourcepackage(self):
        return self.sourcepackage.getSuiteSourcePackage(self.pocket)


@implementer(IFindOfficialBranchLinks)
class SeriesSourcePackageBranchSet:
    """See `ISeriesSourcePackageBranchSet`."""

    @staticmethod
    def new(
        distroseries,
        pocket,
        sourcepackagename,
        branch,
        registrant,
        date_created=None,
    ):
        """Link a source package in a distribution suite to a branch."""
        # Circular import.
        from lp.soyuz.model.distributionsourcepackagecache import (
            DistributionSourcePackageCache,
        )

        if date_created is None:
            date_created = datetime.now(timezone.utc)
        sspb = SeriesSourcePackageBranch(
            distroseries,
            pocket,
            sourcepackagename,
            branch,
            registrant,
            date_created,
        )
        IPrimaryStore(SeriesSourcePackageBranch).add(sspb)
        DistributionSourcePackageCache.updateOfficialBranches(
            distroseries.distribution, [sourcepackagename]
        )
        return sspb

    def findForBranch(self, branch):
        """See `IFindOfficialBranchLinks`."""
        return self.findForBranches([branch])

    def findForBranches(self, branches):
        """See `IFindOfficialBranchLinks`."""
        branch_ids = {branch.id for branch in branches}
        return IStore(SeriesSourcePackageBranch).find(
            SeriesSourcePackageBranch,
            SeriesSourcePackageBranch.branchID.is_in(branch_ids),
        )

    def findForSourcePackage(self, sourcepackage):
        """See `IFindOfficialBranchLinks`."""
        distroseries = sourcepackage.distroseries
        sourcepackagename = sourcepackage.sourcepackagename
        return IStore(SeriesSourcePackageBranch).find(
            SeriesSourcePackageBranch,
            SeriesSourcePackageBranch.distroseries == distroseries.id,
            SeriesSourcePackageBranch.sourcepackagename
            == sourcepackagename.id,
        )

    def findForDistributionSourcePackage(self, distrosourcepackage):
        """See `IFindOfficialBranchLinks`."""
        # To prevent circular imports.
        from lp.registry.model.distroseries import DistroSeries

        distro = distrosourcepackage.distribution
        sourcepackagename = distrosourcepackage.sourcepackagename
        return IStore(SeriesSourcePackageBranch).find(
            SeriesSourcePackageBranch,
            DistroSeries.distribution == distro.id,
            SeriesSourcePackageBranch.distroseries == DistroSeries.id,
            SeriesSourcePackageBranch.sourcepackagename
            == sourcepackagename.id,
        )

    @staticmethod
    def delete(sourcepackage, pocket):
        """Remove the SeriesSourcePackageBranch for sourcepackage and pocket.

        :param sourcepackage: An `ISourcePackage`.
        :param pocket: A `PackagePublishingPocket` enum item.
        """
        distroseries = sourcepackage.distroseries
        sourcepackagename = sourcepackage.sourcepackagename
        return (
            IPrimaryStore(SeriesSourcePackageBranch)
            .find(
                SeriesSourcePackageBranch,
                SeriesSourcePackageBranch.distroseries == distroseries.id,
                SeriesSourcePackageBranch.sourcepackagename
                == sourcepackagename.id,
                SeriesSourcePackageBranch.pocket == pocket,
            )
            .remove()
        )
