# Copyright 2019-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Interfaces for bases for snaps."""

__metaclass__ = type
__all__ = [
    "CannotDeleteSnapBase",
    "ISnapBase",
    "ISnapBaseSet",
    "NoSuchSnapBase",
    ]

from lazr.restful.declarations import (
    call_with,
    collection_default_content,
    error_status,
    export_destructor_operation,
    export_factory_operation,
    export_operation_as,
    export_read_operation,
    export_write_operation,
    exported,
    exported_as_webservice_collection,
    exported_as_webservice_entry,
    operation_for_version,
    operation_parameters,
    operation_returns_entry,
    REQUEST_USER,
    )
from lazr.restful.fields import (
    CollectionField,
    Reference,
    )
from lazr.restful.interface import copy_field
import six
from six.moves import http_client
from zope.component import getUtility
from zope.interface import Interface
from zope.schema import (
    Bool,
    Datetime,
    Dict,
    Int,
    List,
    TextLine,
    )

from lp import _
from lp.app.errors import NameLookupFailed
from lp.app.validators.name import name_validator
from lp.buildmaster.interfaces.processor import IProcessor
from lp.registry.interfaces.distroseries import IDistroSeries
from lp.services.fields import (
    ContentNameField,
    PublicPersonChoice,
    )
from lp.soyuz.interfaces.archive import IArchive
from lp.soyuz.interfaces.archivedependency import IArchiveDependency


class NoSuchSnapBase(NameLookupFailed):
    """The requested `SnapBase` does not exist."""

    _message_prefix = "No such base"


@error_status(http_client.BAD_REQUEST)
class CannotDeleteSnapBase(Exception):
    """The base cannot be deleted at this time."""


class SnapBaseNameField(ContentNameField):
    """Ensure that `ISnapBase` has unique names."""

    errormessage = _("%s is already in use by another base.")

    @property
    def _content_iface(self):
        """See `UniqueField`."""
        return ISnapBase

    def _getByName(self, name):
        """See `ContentNameField`."""
        try:
            return getUtility(ISnapBaseSet).getByName(name)
        except NoSuchSnapBase:
            return None


class ISnapBaseView(Interface):
    """`ISnapBase` attributes that anyone can view."""

    id = Int(title=_("ID"), required=True, readonly=True)

    date_created = exported(Datetime(
        title=_("Date created"), required=True, readonly=True))

    registrant = exported(PublicPersonChoice(
        title=_("Registrant"), required=True, readonly=True,
        vocabulary="ValidPersonOrTeam",
        description=_("The person who registered this base.")))

    is_default = exported(Bool(
        title=_("Is default?"), required=True, readonly=True,
        description=_(
            "Whether this base is the default for snaps that do not specify a "
            "base.")))

    dependencies = exported(CollectionField(
        title=_("Archive dependencies for this snap base."),
        value_type=Reference(schema=IArchiveDependency),
        readonly=True))

    @operation_parameters(dependency=Reference(schema=IArchive))
    @operation_returns_entry(schema=IArchiveDependency)
    @export_read_operation()
    @operation_for_version("devel")
    def getArchiveDependency(dependency):
        """Return the `IArchiveDependency` object for the given dependency.

        :param dependency: an `IArchive`.

        :return: an `IArchiveDependency`, or None if a corresponding object
            could not be found.
        """

    processors = exported(CollectionField(
        title=_("Processors"),
        description=_("The architectures that the snap base supports."),
        value_type=Reference(schema=IProcessor),
        readonly=True))


class ISnapBaseEditableAttributes(Interface):
    """`ISnapBase` attributes that can be edited.

    Anyone can view these attributes, but they need launchpad.Edit to change.
    """

    name = exported(SnapBaseNameField(
        title=_("Name"), required=True, readonly=False,
        constraint=name_validator))

    display_name = exported(TextLine(
        title=_("Display name"), required=True, readonly=False))

    distro_series = exported(Reference(
        IDistroSeries, title=_("Distro series"),
        required=True, readonly=False))

    build_channels = exported(Dict(
        title=_("Source snap channels for builds"),
        key_type=TextLine(), required=True, readonly=False,
        description=_(
            "A dictionary mapping snap names to channels to use when building "
            "snaps that specify this base.")))


class ISnapBaseEdit(Interface):
    """`ISnapBase` methods that require launchpad.Edit permission."""

    def addArchiveDependency(dependency, pocket, component=None):
        """Add an archive dependency for this snap base.

        :param dependency: an `IArchive`.
        :param pocket: a `PackagePublishingPocket`.
        :param component: an optional `IComponent` object; if not given, the
            archive dependency will use the component used for dependencies
            on the primary archive.

        :raise: `ArchiveDependencyError` if the given `dependency` does not
            fit this snap base.
        :return: an `IArchiveDependency`.
        """

    @operation_parameters(
        component=copy_field(IArchiveDependency["component_name"]))
    @export_operation_as(six.ensure_str("addArchiveDependency"))
    @export_factory_operation(IArchiveDependency, ["dependency", "pocket"])
    @operation_for_version("devel")
    def _addArchiveDependency(dependency, pocket, component=None):
        """Add an archive dependency for this snap base.

        :param dependency: an `IArchive`.
        :param pocket: a `PackagePublishingPocket`.
        :param component: an optional component name; if not given, the
            archive dependency will use the component used for dependencies
            on the primary archive.

        :raise: `ArchiveDependencyError` if the given `dependency` does not
            fit this snap base.
        :return: an `IArchiveDependency`.
        """

    @operation_parameters(
        dependency=Reference(schema=IArchive, required=True))
    @export_write_operation()
    @operation_for_version("devel")
    def removeArchiveDependency(dependency):
        """Remove the archive dependency on the given archive.

        :param dependency: an `IArchive`.
        """

    @operation_parameters(
        processors=List(
            value_type=Reference(schema=IProcessor), required=True))
    @export_write_operation()
    @operation_for_version("devel")
    def setProcessors(processors):
        """Set the architectures that the snap base supports."""

    @export_destructor_operation()
    @operation_for_version("devel")
    def destroySelf():
        """Delete the specified base.

        :raises CannotDeleteSnapBase: if the base cannot be deleted.
        """


# XXX cjwatson 2019-01-28 bug=760849: "beta" is a lie to get WADL
# generation working.  Individual attributes must set their version to
# "devel".
@exported_as_webservice_entry(as_of="beta")
class ISnapBase(ISnapBaseView, ISnapBaseEditableAttributes, ISnapBaseEdit):
    """A base for snaps."""


class ISnapBaseSetEdit(Interface):
    """`ISnapBaseSet` methods that require launchpad.Edit permission."""

    @call_with(registrant=REQUEST_USER)
    @operation_parameters(
        processors=List(
            value_type=Reference(schema=IProcessor), required=False))
    @export_factory_operation(
        ISnapBase, ["name", "display_name", "distro_series", "build_channels"])
    @operation_for_version("devel")
    def new(registrant, name, display_name, distro_series, build_channels,
            processors=None, date_created=None):
        """Create an `ISnapBase`."""

    @operation_parameters(
        snap_base=Reference(title=_("Base"), required=True, schema=ISnapBase))
    @export_write_operation()
    @operation_for_version("devel")
    def setDefault(snap_base):
        """Set the default base.

        This will be used to pick the default distro series for snaps that
        do not specify a base.

        :param snap_base: An `ISnapBase`, or None to unset the default base.
        """


@exported_as_webservice_collection(ISnapBase)
class ISnapBaseSet(ISnapBaseSetEdit):
    """Interface representing the set of bases for snaps."""

    def __iter__():
        """Iterate over `ISnapBase`s."""

    def __getitem__(name):
        """Return the `ISnapBase` with this name."""

    @operation_parameters(
        name=TextLine(title=_("Base name"), required=True))
    @operation_returns_entry(ISnapBase)
    @export_read_operation()
    @operation_for_version("devel")
    def getByName(name):
        """Return the `ISnapBase` with this name.

        :raises NoSuchSnapBase: if no base exists with this name.
        """

    @operation_returns_entry(ISnapBase)
    @export_read_operation()
    @operation_for_version("devel")
    def getDefault():
        """Get the default base.

        This will be used to pick the default distro series for snaps that
        do not specify a base.
        """

    @collection_default_content()
    def getAll():
        """Return all `ISnapBase`s."""
