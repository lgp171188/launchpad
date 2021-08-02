# Copyright 2019-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Interfaces to allow bug filing on multiple versions of an OCI Project."""

__metaclass__ = type
__all__ = [
    'IOCIProjectSeries',
    'IOCIProjectSeriesEditableAttributes',
    'IOCIProjectSeriesView',
    ]

from lazr.restful.declarations import (
    exported,
    exported_as_webservice_entry,
    )
from lazr.restful.fields import Reference
from zope.interface import Interface
from zope.schema import (
    Choice,
    Datetime,
    Int,
    Text,
    TextLine,
    )

from lp import _
from lp.app.validators.name import name_validator
from lp.registry.interfaces.ociproject import IOCIProject
from lp.registry.interfaces.series import SeriesStatus
from lp.services.fields import PublicPersonChoice


class IOCIProjectSeriesView(Interface):
    """IOCIProjectSeries attributes that require launchpad.View permission."""

    id = Int(title=_("ID"), required=True, readonly=True)

    oci_project = exported(Reference(
        IOCIProject,
        title=_("The OCI project that this series belongs to."),
        required=True, readonly=True))

    date_created = exported(Datetime(
        title=_("Date created"), required=True, readonly=True,
        description=_(
            "The date on which this series was created in Launchpad.")))

    registrant = exported(PublicPersonChoice(
        title=_("Registrant"),
        description=_("The person that registered this series."),
        vocabulary='ValidPersonOrTeam', required=True, readonly=True))


class IOCIProjectSeriesEditableAttributes(Interface):
    """IOCIProjectSeries attributes that can be edited.

    These attributes need launchpad.View to see, and launchpad.Edit to change.
    """

    name = exported(TextLine(
        title=_("Name"), constraint=name_validator,
        required=True, readonly=False,
        description=_("The name of this series.")))

    summary = exported(Text(
        title=_("Summary"), required=True, readonly=False,
        description=_("A brief summary of this series.")))

    status = exported(Choice(
        title=_("Status"), required=True, readonly=False,
        vocabulary=SeriesStatus))


class IOCIProjectSeriesEdit(Interface):
    """IOCIProjectSeries attributes that require launchpad.Edit permission."""

    def destroySelf():
        """Delete this OCI project series."""


@exported_as_webservice_entry(
    publish_web_link=True, as_of="devel", singular_name="oci_project_series")
class IOCIProjectSeries(IOCIProjectSeriesView, IOCIProjectSeriesEdit,
                        IOCIProjectSeriesEditableAttributes):
    """A series of an Open Container Initiative project.

    This is used to allow tracking bugs against multiple versions of images.
    """
