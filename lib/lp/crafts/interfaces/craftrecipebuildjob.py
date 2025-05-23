# Copyright 2025 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Interfaces for craft recipe build jobs."""

__all__ = [
    "ICraftPublishingJob",
    "ICraftPublishingJobSource",
    "ICraftRecipeBuildJob",
]

from lazr.restful.fields import Reference
from zope.interface import Attribute, Interface

from lp import _
from lp.crafts.interfaces.craftrecipebuild import ICraftRecipeBuild
from lp.services.job.interfaces.job import IJob, IJobSource, IRunnableJob


class ICraftRecipeBuildJob(Interface):
    """A job related to a craft recipe build."""

    job = Reference(
        title=_("The common Job attributes."),
        schema=IJob,
        required=True,
        readonly=True,
    )
    build = Reference(
        title=_("The craft recipe build to use for this job."),
        schema=ICraftRecipeBuild,
        required=True,
        readonly=True,
    )
    metadata = Attribute(_("A dict of data about the job."))


class ICraftPublishingJob(IRunnableJob):
    """
    A job that publishes craft recipe build artifacts to external repositories.
    """

    error_message = Attribute("The error message if the publishing failed.")

    def create(build):
        """Create a new CraftPublishingJob."""


class ICraftPublishingJobSource(IJobSource):
    """A source for creating and finding CraftPublishingJobs."""

    def create(build):
        """
        Publish artifacts from a craft recipe build to external repositories.

        :param build: The build to publish.
        """
