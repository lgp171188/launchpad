# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""OCI Recipe Target interfaces."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    'IOCIProject',
    'IOCIProjectSet',
    ]

from lazr.restful.declarations import (
    export_as_webservice_entry,
    exported,
    )
from lazr.restful.fields import Reference
from zope.interface import Interface
from zope.schema import (
    Datetime,
    Int,
    Text,
    )

from lp import _
from lp.bugs.interfaces.bugtarget import IBugTarget
from lp.registry.interfaces.distribution import IDistribution
from lp.registry.interfaces.ociprojectname import IOCIProjectName
from lp.registry.interfaces.person import IPerson
from lp.registry.interfaces.role import IHasOwner


class IOCIProjectView(Interface):
    """IOCIProject attributes that require launchpad.View permission."""

    id = Int(title=_("OCI Recipe Target ID"), required=True, readonly=True)
    date_created = Datetime(title=_("Date created"), required=True)
    date_last_modified = Datetime(title=_("Date last modified"), required=True)

    registrant = exported(Reference(
        IPerson,
        title=_("The person that registered this recipe."),
        required=True,
        readonly=True))


class IOCIProjectEditableAttributes(IBugTarget, IHasOwner):
    """IOCIProject attributes that can be edited.

    These attributes need launchpad.View to see, and launchpad.Edit to change.
    """

    distribution = exported(Reference(
        IDistribution,
        title=_("The distribution that this recipe is associated with.")))
    ociprojectname = exported(Reference(
        IOCIProjectName,
        title=_("The name of this recipe."),
        required=True,
        readonly=True))
    description = exported(Text(title=_("The description for this recipe.")))


class IOCIProject(IOCIProjectView,
                       IOCIProjectEditableAttributes):
    """A target (pillar and name) for Open Container Initiative recipes."""

    export_as_webservice_entry()


class IOCIProjectSet(Interface):
    """A utility to create and access OCI recipe targets."""

    def new(registrant, pillar, ociprojectname,
            date_created=None, description=None, bug_supervisor=None,
            bug_reporting_guidelines=None, bug_reported_acknowledgement=None,
            bugfiling_duplicate_search=False):
        """Create an `IOCIProject`."""

    def getByDistributionAndName(distribution, name):
        """Get the OCIProjects for a given distribution."""
