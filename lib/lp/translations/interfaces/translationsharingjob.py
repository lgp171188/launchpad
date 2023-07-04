# Copyright 2009-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from lazr.restful.fields import Reference
from zope.interface import Attribute

from lp import _
from lp.services.job.interfaces.job import IJob


class ITranslationSharingJob(IJob):
    job = Reference(
        title=_("The common Job attributes."),
        schema=IJob,
        required=True,
        readonly=True,
    )

    productseries = Attribute(_("The productseries of the Packaging."))

    distroseries = Attribute(_("The distroseries of the Packaging."))

    sourcepackagename = Attribute(_("The sourcepackagename of the Packaging."))

    potemplate = Attribute(
        _("The POTemplate to pass around as the relevant template.")
    )
