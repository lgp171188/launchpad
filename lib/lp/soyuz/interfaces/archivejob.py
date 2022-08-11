# Copyright 2010-2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""ArchiveJob interfaces."""

__all__ = [
    "IArchiveJob",
    "IArchiveJobSource",
    "ICIBuildUploadJob",
    "ICIBuildUploadJobSource",
    "IPackageUploadNotificationJob",
    "IPackageUploadNotificationJobSource",
]


from lazr.restful.fields import Reference
from zope.interface import Attribute, Interface
from zope.schema import Choice, Int, Object, TextLine

from lp import _
from lp.code.interfaces.cibuild import ICIBuild
from lp.registry.interfaces.distroseries import IDistroSeries
from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.services.job.interfaces.job import IJob, IJobSource, IRunnableJob
from lp.soyuz.interfaces.archive import IArchive


class IArchiveJob(Interface):
    """A Job related to an Archive."""

    id = Int(
        title=_("DB ID"),
        required=True,
        readonly=True,
        description=_("The tracking number for this job."),
    )

    archive = Object(
        title=_("The archive this job is about."),
        schema=IArchive,
        required=True,
    )

    job = Object(
        title=_("The common Job attributes"), schema=IJob, required=True
    )

    metadata = Attribute("A dict of data about the job.")

    def destroySelf():
        """Destroy this object."""


class IArchiveJobSource(IJobSource):
    """An interface for acquiring IArchiveJobs."""

    def create(archive):
        """Create a new IArchiveJob for an archive."""


class IPackageUploadNotificationJob(IRunnableJob):
    """A Job to send package upload notifications."""


class IPackageUploadNotificationJobSource(IArchiveJobSource):
    """Interface for acquiring PackageUploadNotificationJobs."""


class ICIBuildUploadJob(IRunnableJob):
    """A Job to upload a CI build to an archive."""

    ci_build = Reference(
        schema=ICIBuild,
        title=_("CI build to copy"),
        required=True,
        readonly=True,
    )

    target_distroseries = Reference(
        schema=IDistroSeries,
        title=_("Target distroseries"),
        required=True,
        readonly=True,
    )

    target_pocket = Choice(
        title=_("Target pocket"),
        vocabulary=PackagePublishingPocket,
        required=True,
        readonly=True,
    )

    target_channel = TextLine(
        title=_("Target channel"), required=False, readonly=True
    )


class ICIBuildUploadJobSource(IArchiveJobSource):
    """Interface for acquiring `CIBuildUploadJob`s."""
