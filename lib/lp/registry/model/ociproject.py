# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""OCI Project implementation."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    'OCIProject',
    'OCIProjectSet',
    ]

import pytz
from storm.locals import (
    Bool,
    DateTime,
    Int,
    Reference,
    Unicode,
    )
from zope.interface import implementer

from lp.bugs.model.bugtarget import BugTargetBase
from lp.registry.interfaces.distribution import IDistribution
from lp.registry.interfaces.ociproject import (
    IOCIProject,
    IOCIProjectSet,
    )
from lp.registry.model.ociprojectname import OCIProjectName
from lp.registry.model.ociprojectseries import OCIProjectSeries
from lp.registry.interfaces.series import SeriesStatus
from lp.services.database.constants import DEFAULT
from lp.services.database.interfaces import (
    IMasterStore,
    IStore,
    )
from lp.services.database.stormbase import StormBase


@implementer(IOCIProject)
class OCIProject(BugTargetBase, StormBase):
    """See `IOCIProject` and `IOCIProjectSet`."""

    __storm_table__ = "OCIProject"

    id = Int(primary=True)
    date_created = DateTime(
        name="date_created", tzinfo=pytz.UTC, allow_none=False)
    date_last_modified = DateTime(
        name="date_last_modified", tzinfo=pytz.UTC, allow_none=False)

    registrant_id = Int(name='registrant', allow_none=False)
    registrant = Reference(registrant_id, "Person.id")

    distribution_id = Int(name="distribution", allow_none=True)
    distribution = Reference(distribution_id, "Distribution.id")

    ociprojectname_id = Int(name="ociprojectname", allow_none=False)
    ociprojectname = Reference(ociprojectname_id, "OCIProjectName.id")

    description = Unicode(name="description")

    bug_reporting_guidelines = Unicode(name="bug_reporting_guidelines")
    bug_reported_acknowledgement = Unicode(name="bug_reported_acknowledgement")
    enable_bugfiling_duplicate_search = Bool(
        name="enable_bugfiling_duplicate_search")

    @property
    def pillar(self):
        """See `IBugTarget`."""
        return self.distribution

    @property
    def bugtargetname(self):
        """See `IBugTarget`."""
        return "OCI project %s for %s" % (
            self.ociprojectname.name, self.pillar.name)

    @property
    def bugtargetdisplayname(self):
        """See `IBugTarget`."""
        return "OCI project %s for %s" % (
            self.ociprojectname.name, self.pillar.name)

    def newSeries(self, name, summary, registrant,
                  status=SeriesStatus.DEVELOPMENT, date_created=DEFAULT):
        """See `IOCIProject`."""
        series = OCIProjectSeries(
            ociproject=self,
            name=name,
            summary=summary,
            registrant=registrant,
            status=status,
        )
        return series

    @property
    def series(self):
        """See `IOCIProject`."""
        ret = IStore(OCIProjectSeries).find(
            OCIProjectSeries,
            OCIProjectSeries.ociproject == self
            ).order_by(OCIProjectSeries.date_created)
        return ret



@implementer(IOCIProjectSet)
class OCIProjectSet:

    def new(self, registrant, pillar, ociprojectname,
            date_created=DEFAULT, description=None,
            bug_reporting_guidelines=None,
            bug_reported_acknowledgement=None,
            bugfiling_duplicate_search=False):
        """See `IOCIProjectSet`."""
        store = IMasterStore(OCIProject)
        target = OCIProject()
        target.date_created = date_created
        target.date_last_modified = date_created

        # XXX twom 2019-10-10 This needs to have IProduct support
        # when the model supports it
        if IDistribution.providedBy(pillar):
            target.distribution = pillar
        else:
            raise ValueError(
                'The target of an OCIProject must be an '
                'IDistribution instance.')

        target.registrant = registrant
        target.ociprojectname = ociprojectname
        target.description = description
        target.bug_reporting_guidelines = bug_reporting_guidelines
        target.enable_bugfiling_duplicate_search = bugfiling_duplicate_search
        store.add(target)
        return target

    def getByDistributionAndName(self, distribution, name):
        """See `IOCIProjectSet`."""
        target = IStore(OCIProject).find(
            OCIProject,
            OCIProject.distribution == distribution,
            OCIProject.ociprojectname == OCIProjectName.id,
            OCIProjectName.name == name).one()
        return target
