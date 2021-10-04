# Copyright 2019-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""OCIRecipe build job interfaces"""

__all__ = [
    'IOCIRecipeBuildJob',
    'IOCIRegistryUploadJob',
    'IOCIRegistryUploadJobSource',
    ]

from lazr.restful.fields import Reference
from zope.interface import (
    Attribute,
    Interface,
    )
from zope.schema import (
    Dict,
    List,
    TextLine,
    )

from lp import _
from lp.oci.interfaces.ocirecipebuild import IOCIRecipeBuild
from lp.services.job.interfaces.job import (
    IJob,
    IJobSource,
    IRunnableJob,
    )


class IOCIRecipeBuildJob(Interface):
    """A job related to an OCI image."""
    job = Reference(
        title=_("The common Job attributes."), schema=IJob,
        required=True, readonly=True)

    build = Reference(
        title=_("The OCI Recipe Build to use for this job."),
        schema=IOCIRecipeBuild, required=True, readonly=True)

    json_data = Attribute(_("A dict of data about the job."))


class IOCIRegistryUploadJob(IRunnableJob):
    """A Job that uploads an OCI image to a registry."""

    error_summary = TextLine(
        title=_("Error summary"), required=False, readonly=True)

    errors = List(
        title=_("Detailed registry upload errors"),
        description=_(
            "A list of errors, as described in "
            "https://docs.docker.com/registry/spec/api/#errors, from the last "
            "attempt to run this job."),
        value_type=Dict(key_type=TextLine()),
        required=False, readonly=True)


class IOCIRegistryUploadJobSource(IJobSource):

    def create(build):
        """Upload an OCI image to a registry.

        :param build: The OCI recipe build to upload.
        """
