# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Charm recipe build job interfaces."""

__metaclass__ = type
__all__ = [
    'ICharmRecipeBuildJob',
    'ICharmhubUploadJob',
    'ICharmhubUploadJobSource',
    ]

from lazr.restful.fields import Reference
from zope.interface import (
    Attribute,
    Interface,
    )
from zope.schema import (
    Int,
    TextLine,
    )

from lp import _
from lp.charms.interfaces.charmrecipebuild import ICharmRecipeBuild
from lp.services.job.interfaces.job import (
    IJob,
    IJobSource,
    IRunnableJob,
    )


class ICharmRecipeBuildJob(Interface):
    """A job related to a charm recipe build."""

    job = Reference(
        title=_("The common Job attributes."), schema=IJob,
        required=True, readonly=True)

    build = Reference(
        title=_("The charm recipe build to use for this job."),
        schema=ICharmRecipeBuild, required=True, readonly=True)

    metadata = Attribute(_("A dict of data about the job."))


class ICharmhubUploadJob(IRunnableJob):
    """A Job that uploads a charm recipe build to Charmhub."""

    store_metadata = Attribute(
        _("Combined metadata for this job and the matching build"))

    error_message = TextLine(
        title=_("Error message"), required=False, readonly=True)

    error_detail = TextLine(
        title=_("Error message detail"), required=False, readonly=True)

    store_revision = Int(
        title=_("The revision assigned to this build by Charmhub"),
        required=False, readonly=True)

    status_url = TextLine(
        title=_("The URL on Charmhub to get the status of this build"),
        required=False, readonly=True)


class ICharmhubUploadJobSource(IJobSource):

    def create(build):
        """Upload a charm recipe build to Charmhub.

        :param build: The charm recipe build to upload.
        """
