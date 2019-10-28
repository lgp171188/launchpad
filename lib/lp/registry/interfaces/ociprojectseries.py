# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Interfaces to allow bug filing on multiple versions of an OCI Project."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    'IOCIProjectSeries',
    'IOCIProjectSeriesEditableAttributes',
    'IOCIProjectSeriesView',
    ]

from lazr.restful.declarations import (
    export_as_webservice_entry,
    exported,
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
from lp.registry.interfaces.person import IPerson
from lp.registry.interfaces.series import SeriesStatus
from lp.services.fields import PublicPersonChoice


class IOCIProjectSeriesView(Interface):
    """IOCIProjectSeries attributes that require launchpad.View permission."""

    id = Int(title=_("ID"), required=True, readonly=True)

    ociproject = Reference(
        IOCIProject,
        title=_("The OCI project that this series belongs to."),
        required=True)

    date_created = Datetime(
        title=_("Date created"), required=True, readonly=True,
        description=_(
            "The date on which this series was created in Launchpad."))

    registrant = PublicPersonChoice(
        title=_("Registrant"),
        description=_("The person that registered this series."),
        vocabulary='ValidPersonOrTeam', required=True, readonly=True)


class IOCIProjectSeriesEditableAttributes(Interface):
    """IOCIProjectSeries attributes that can be edited.

    These attributes need launchpad.View to see, and launchpad.Edit to change.
    """

    name = TextLine(
        title=_("Name"), constraint=name_validator,
        required=True, readonly=False,
        description=_("The name of this series."))

    summary = Text(
        title=_("Summary"), required=True, readonly=False,
        description=_("A brief summary of this series."))

    status = Choice(
            title=_("Status"), required=True,
            vocabulary=SeriesStatus)


class IOCIProjectSeriesEdit(Interface):
    """IOCIProjectSeries attributes that require launchpad.Edit permission"""


class IOCIProjectSeries(IOCIProjectSeriesView, IOCIProjectSeriesEdit,
                        IOCIProjectSeriesEditableAttributes):
    """A series of an Open Container Initiative project,
       used to allow tracking bugs against multiple versions of images.
    """
