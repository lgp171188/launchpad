# Copyright 2019-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Interfaces related to OCI recipe jobs."""

__metaclass__ = type
__all__ = [
    'IOCIRecipeJob',
    'IOCIRecipeRequestBuildsJob',
    'IOCIRecipeRequestBuildsJobSource',
    ]

from lazr.restful.fields import Reference
from zope.interface import (
    Attribute,
    Interface,
    )
from zope.schema import (
    Datetime,
    Dict,
    Int,
    List,
    TextLine,
    )

from lp import _
from lp.oci.interfaces.ocirecipe import (
    IOCIRecipe,
    IOCIRecipeBuildRequest,
    )
from lp.oci.interfaces.ocirecipebuild import IOCIRecipeBuild
from lp.registry.interfaces.person import IPerson
from lp.services.job.interfaces.job import (
    IJob,
    IJobSource,
    IRunnableJob,
    )


class IOCIRecipeJob(Interface):
    """A job related to an OCI Recipe."""

    job = Reference(
        title=_("The common Job attributes."), schema=IJob,
        required=True, readonly=True)

    recipe = Reference(
        title=_("The OCI recipe to use for this job."),
        schema=IOCIRecipe, required=True, readonly=True)

    metadata = Attribute(_("A dict of data about the job."))


class IOCIRecipeRequestBuildsJob(IRunnableJob):
    """A Job that processes a request for builds of an OCI recipe."""

    requester = Reference(
        title=_("The person requesting the builds."), schema=IPerson,
        required=True, readonly=True)

    build_request = Reference(
        title=_("The build request corresponding to this job."),
        schema=IOCIRecipeBuildRequest, required=True, readonly=True)

    builds = List(
        title=_("The builds created by this request."),
        value_type=Reference(schema=IOCIRecipeBuild), required=True,
        readonly=True)

    date_created = Datetime(
        title=_("Time when this job was created."),
        required=True, readonly=True)

    date_finished = Datetime(
        title=_("Time when this job finished."),
        required=True, readonly=True)

    error_message = TextLine(
        title=_("Error message"), required=False, readonly=True)

    uploaded_manifests = Dict(
        title=_("A dict of manifest information per build."),
        key_type=Int(), value_type=Dict(),
        required=False, readonly=True)

    def addUploadedManifest(build_id, manifest_info):
        """Add the manifest information for one of the builds in this
        BuildRequest.
        """

    def build_status():
        """Return the status of the builds and the upload to a registry."""


class IOCIRecipeRequestBuildsJobSource(IJobSource):

    def create(oci_recipe, requester, architectures=None):
        """Request builds of an OCI Recipe.

        :param oci_recipe: The OCI recipe to build.
        :param requester: The person requesting the builds.
        :param architectures: Build only for this list of
            architectures, if they are available for the recipe. If
            None, build for all available architectures.
        """

    def getByOCIRecipeAndID(recipe, job_id):
        """Retrieve the build job by OCI recipe and the given job ID.
        """

    def findByOCIRecipe(recipe, statuses=None, job_ids=None):
        """Find jobs for an OCI recipe.

        :param oci_recipe: An OCI recipe to search for.
        :param statuses: An optional iterable of `JobStatus`es to search for.
        :param job_ids: An optional iterable of job IDs to search for.
        :return: A sequence of `OCIRecipeRequestBuildsJob`s with the specified
            OCI recipe.
        """
