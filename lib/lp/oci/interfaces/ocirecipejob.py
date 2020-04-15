# Copyright 2019-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Interfaces related to OCI recipe jobs."""

from __future__ import absolute_import, print_function, unicode_literals

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

    oci_recipe = Reference(
        title=_("The OCI Recipe being built."), schema=IOCIRecipe,
        required=True, readonly=True)

    build_request = Reference(
        title=_("The build request corresponding to this job."),
        schema=IOCIRecipeBuildRequest, required=True, readonly=True)

    builds = List(
        title=_("The builds created by this request."),
        value_type=Reference(schema=IOCIRecipeBuild), required=True,
        readonly=True)

    error_message = TextLine(
        title=_("Error message"), required=False, readonly=True)


class IOCIRecipeRequestBuildsJobSource(IJobSource):

    def create(oci_recipe, requester):
        """Request builds of an OCI Recipe.

        :param oci_recipe: The OCI recipe to build.
        :param requester: The person requesting the builds.
        """

    def getByOCIRecipeAndID(self, oci_recipe, job_id):
        """Retrieve the build job by OCI recipe and the given job ID.
        """
