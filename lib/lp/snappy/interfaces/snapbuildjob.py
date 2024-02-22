# Copyright 2016-2017 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Snap build job interfaces."""

__all__ = [
    "ISnapBuildJob",
    "ISnapBuildStoreUploadStatusChangedEvent",
    "ISnapStoreUploadJob",
    "ISnapStoreUploadJobSource",
]

from lazr.restful.fields import Reference
from zope.interface import Attribute, Interface
from zope.interface.interfaces import IObjectEvent
from zope.schema import Dict, Int, TextLine

from lp import _
from lp.services.job.interfaces.job import IJob, IJobSource, IRunnableJob
from lp.snappy.interfaces.snapbuild import ISnapBuild


class ISnapBuildJob(Interface):
    """A job related to a snap package."""

    job = Reference(
        title=_("The common Job attributes."),
        schema=IJob,
        required=True,
        readonly=True,
    )

    snapbuild = Reference(
        title=_("The snap build to use for this job."),
        schema=ISnapBuild,
        required=True,
        readonly=True,
    )

    metadata = Attribute(_("A dict of data about the job."))


class ISnapBuildStoreUploadStatusChangedEvent(IObjectEvent):
    """The store upload status of a snap package build changed."""


class ISnapStoreUploadJob(IRunnableJob):
    """A Job that uploads a snap build to the store."""

    store_metadata = Attribute(
        _("Combined metadata for this job and matching snapbuild")
    )

    error_message = TextLine(
        title=_("Error message"), required=False, readonly=True
    )

    error_detail = TextLine(
        title=_("Error message detail"), required=False, readonly=True
    )

    upload_id = Int(
        title=_(
            "The ID returned by the store when uploading this build's snap "
            "file."
        ),
        required=False,
        readonly=True,
    )

    components_ids = Dict(
        title=_(
            "The IDs returned by the store when uploading snap components."
            "The key is the component name and the value is the related id."
        ),
        key_type=TextLine(),
        value_type=TextLine(),
        required=False,
        readonly=True,
    )

    status_url = TextLine(
        title=_("The URL on the store to get the status of this build"),
        required=False,
        readonly=True,
    )

    store_url = TextLine(
        title=_("The URL on the store corresponding to this build"),
        required=False,
        readonly=True,
    )

    store_revision = Int(
        title=_("The revision assigned to this build by the store"),
        required=False,
        readonly=True,
    )


class ISnapStoreUploadJobSource(IJobSource):
    def create(snapbuild):
        """Upload a snap build to the store.

        :param snapbuild: The snap build to upload.
        """
