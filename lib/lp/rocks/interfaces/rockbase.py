# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Interfaces for bases for rocks."""

__all__ = [
    "DuplicateRockBase",
    "IRockBase",
    "IRockBaseSet",
    "NoSuchRockBase",
]

import http.client

from lazr.restful.declarations import (
    REQUEST_USER,
    call_with,
    collection_default_content,
    error_status,
    export_destructor_operation,
    export_factory_operation,
    export_read_operation,
    export_write_operation,
    exported,
    exported_as_webservice_collection,
    exported_as_webservice_entry,
    operation_for_version,
    operation_parameters,
    operation_returns_entry,
)
from lazr.restful.fields import CollectionField, Reference
from zope.interface import Interface
from zope.schema import Datetime, Dict, Int, List, TextLine

from lp import _
from lp.app.errors import NotFoundError
from lp.buildmaster.interfaces.processor import IProcessor
from lp.registry.interfaces.distroseries import IDistroSeries
from lp.services.fields import PublicPersonChoice


@error_status(http.client.BAD_REQUEST)
class DuplicateRockBase(Exception):
    """Raised for rock bases with duplicate distro series."""

    def __init__(self, distro_series):
        super().__init__(
            "%s is already in use by another base." % distro_series
        )


class NoSuchRockBase(NotFoundError):
    """The requested `RockBase` does not exist."""

    def __init__(self, distro_series):
        self.message = "No base for %s." % distro_series
        super().__init__(self.message)

    def __str__(self):
        return self.message


class IRockBaseView(Interface):
    """`IRockBase` attributes that anyone can view."""

    id = Int(title=_("ID"), required=True, readonly=True)

    date_created = exported(
        Datetime(title=_("Date created"), required=True, readonly=True)
    )

    registrant = exported(
        PublicPersonChoice(
            title=_("Registrant"),
            required=True,
            readonly=True,
            vocabulary="ValidPersonOrTeam",
            description=_("The person who registered this base."),
        )
    )

    distro_series = exported(
        Reference(
            IDistroSeries,
            title=_("Distro series"),
            required=True,
            readonly=True,
        )
    )

    processors = exported(
        CollectionField(
            title=_("Processors"),
            description=_("The architectures that the rock base supports."),
            value_type=Reference(schema=IProcessor),
            readonly=True,
        )
    )


class IRockBaseEditableAttributes(Interface):
    """`IRockBase` attributes that can be edited.

    Anyone can view these attributes, but they need launchpad.Edit to change.
    """

    build_channels = exported(
        Dict(
            title=_("Source snap channels for builds"),
            key_type=TextLine(),
            required=True,
            readonly=False,
            description=_(
                "A dictionary mapping snap names to channels to use when "
                "building rock recipes that specify this base.  The special "
                "'_byarch' key may have a mapping of architecture names to "
                "mappings of snap names to channels, which if present "
                "override the channels declared at the top level when "
                "building for those architectures."
            ),
        )
    )


class IRockBaseEdit(Interface):
    """`IRockBase` methods that require launchpad.Edit permission."""

    @operation_parameters(
        processors=List(value_type=Reference(schema=IProcessor), required=True)
    )
    @export_write_operation()
    @operation_for_version("devel")
    def setProcessors(processors):
        """Set the architectures that the rock base supports."""

    @export_destructor_operation()
    @operation_for_version("devel")
    def destroySelf():
        """Delete the specified base."""


# XXX jugmac00 2024-09-17 bug=760849: "beta" is a lie to get WADL
# generation working.  Individual attributes must set their version to
# "devel".
@exported_as_webservice_entry(as_of="beta")
class IRockBase(IRockBaseView, IRockBaseEditableAttributes, IRockBaseEdit):
    """A base for rocks."""


class IRockBaseSetEdit(Interface):
    """`IRockBaseSet` methods that require launchpad.Edit permission."""

    @call_with(registrant=REQUEST_USER)
    @operation_parameters(
        processors=List(
            value_type=Reference(schema=IProcessor), required=False
        )
    )
    @export_factory_operation(IRockBase, ["distro_series", "build_channels"])
    @operation_for_version("devel")
    def new(
        registrant,
        distro_series,
        build_channels,
        processors=None,
        date_created=None,
    ):
        """Create an `IRockBase`."""


@exported_as_webservice_collection(IRockBase)
class IRockBaseSet(IRockBaseSetEdit):
    """Interface representing the set of bases for rocks."""

    def __iter__():
        """Iterate over `IRockBase`s."""

    def getByID(id):
        """Return the `IRockBase` with this ID, or None."""

    @operation_parameters(
        distro_series=Reference(
            schema=IDistroSeries, title=_("Distro series"), required=True
        )
    )
    @operation_returns_entry(IRockBase)
    @export_read_operation()
    @operation_for_version("devel")
    def getByDistroSeries(distro_series):
        """Return the `IRockBase` for this distro series.

        :raises NoSuchRockBase: if no base exists for this distro series.
        """

    @collection_default_content()
    def getAll():
        """Return all `IRockBase`s."""
