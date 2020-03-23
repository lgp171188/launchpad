# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""OCIRecipe build job interfaces"""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    'IOCIRecipeBuildJob',
    ]

from lazr.restful.fields import Reference
from zope.interface import (
    Attribute,
    Interface,
    )
from zope.schema import TextLine

from lp import _
from lp.oci.interfaces.ocirecipebuild import IOCIRecipeBuild
from lp.services.job.interfaces.job import (
    IJob,
    IJobSource,
    IRunnableJob,
    )


class IOCIRecipeBuildJob(Interface):
    job = Reference(
        title=_("The common Job attributes."), schema=IJob,
        required=True, readonly=True)

    build = Reference(
        title=_("The OCI Recipe Build to use for this job."),
        schema=IOCIRecipeBuild, required=True, readonly=True)

    json_data = Attribute(_("A dict of data about the job."))
