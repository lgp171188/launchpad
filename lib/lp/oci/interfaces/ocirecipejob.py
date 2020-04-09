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

from formencode.interfaces import Interface, Attribute
from lazr.restful.fields import Reference
from lp.oci.interfaces.ocirecipe import IOCIRecipe, IOCIRecipeBuildRequest
from lp.oci.interfaces.ocirecipebuild import IOCIRecipeBuild
from lp.registry.interfaces.person import IPerson
from lp.services.job.interfaces.job import IRunnableJob, IJobSource, IJob
from lp import _
from zope.schema import List
from zope.schema._bootstrapfields import TextLine
from zope.schema._field import Datetime


class IOCIRecipeJob(Interface):
    """A job related to an OCI Recipe."""

    job = Reference(
        title=_("The common Job attributes."), schema=IJob,
        required=True, readonly=True)

    oci_recipe = Reference(
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


class IOCIRecipeRequestBuildsJobSource(IJobSource):

    requester = Reference(
        title=_("The person requesting the builds."), schema=IPerson,
        required=True, readonly=True)

    date_created = Datetime(
        title=_("Time when this job was created."),
        required=True, readonly=True)

    date_finished = Datetime(
        title=_("Time when this job finished."),
        required=True, readonly=True)

    error_message = TextLine(
        title=_("Error message resulting from running this job."),
        required=False, readonly=True)

    build_request = Reference(
        title=_("The build request corresponding to this job."),
        schema=IOCIRecipeBuildRequest, required=True, readonly=True)

    builds = List(
        title=_("The builds created by this request."),
        value_type=Reference(schema=IOCIRecipeBuild), required=True,
        readonly=True)
