# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""OCI Project interfaces."""

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

    id = Int(title=_("ID"), required=True, readonly=True)
    date_created = exported(
        Datetime(title=_("Date created"), required=True), readonly=True)
    date_last_modified = exported(
        Datetime(title=_("Date last modified"), required=True), readonly=True)

    registrant = exported(Reference(
        IPerson,
        title=_("The person that registered this project."),
        required=True,
        readonly=True))


class IOCIProjectEditableAttributes(IBugTarget):
    """IOCIProject attributes that can be edited.

    These attributes need launchpad.View to see, and launchpad.Edit to change.
    """

    distribution = Reference(
        IDistribution,
        title=_("The distribution that this OCI project is associated with."))
    ociprojectname = exported(Reference(
        IOCIProjectName,
        title=_("The name of this OCI project."),
        required=True,
        readonly=True))
    description = exported(
        Text(title=_("The description for this OCI project.")))
    pillar = exported(
        Attribute("The pillar containing this target."), readonly=True)


class IOCIProject(IOCIProjectView,
                       IOCIProjectEditableAttributes):
    """A project containing Open Container Initiative recipes."""

    export_as_webservice_entry()


class IOCIProjectSet(Interface):
    """A utility to create and access OCI Projects."""

    def new(registrant, pillar, ociprojectname,
            date_created=None, description=None,
            bug_reporting_guidelines=None, bug_reported_acknowledgement=None,
            bugfiling_duplicate_search=False):
        """Create an `IOCIProject`."""

    def getByDistributionAndName(distribution, name):
        """Get the OCIProjects for a given distribution."""
