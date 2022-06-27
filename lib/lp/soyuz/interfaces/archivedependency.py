# Copyright 2009-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""ArchiveDependency interface."""

__all__ = [
    'IArchiveDependency',
    ]

from lazr.restful.declarations import (
    exported,
    exported_as_webservice_entry,
    )
from lazr.restful.fields import Reference
from zope.interface import (
    Attribute,
    Interface,
    )
from zope.schema import (
    Choice,
    Datetime,
    Int,
    TextLine,
    )

from lp import _
from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.soyuz.interfaces.archive import IArchive


@exported_as_webservice_entry(as_of="beta", publish_web_link=False)
class IArchiveDependency(Interface):
    """ArchiveDependency interface."""

    id = Int(title=_("The archive ID."), readonly=True)

    date_created = exported(
        Datetime(
            title=_("Instant when the dependency was created."),
            required=False, readonly=True))

    # The object that has the dependency: exactly one of archive or
    # snap_base is required (enforced by DB constraints).

    archive = exported(
        Reference(
            schema=IArchive, required=False, readonly=True,
            title=_('Target archive'),
            description=_("The archive that has this dependency.")))

    snap_base = exported(
        Reference(
            # Really ISnapBase, patched in _schema_circular_imports.py.
            schema=Interface, required=False, readonly=True,
            title=_('Target snap base'),
            description=_("The snap base that has this dependency.")))

    parent = Attribute("The object that has this dependency.")

    dependency = exported(
        Reference(
            schema=IArchive, required=False, readonly=True,
            title=_("The archive set as a dependency.")))

    pocket = exported(
        Choice(
            title=_("Pocket"), required=True, readonly=True,
            vocabulary=PackagePublishingPocket))

    component = Choice(
        title=_("Component"), required=False, readonly=True,
        vocabulary='Component')

    # We don't want to export IComponent, so the name is exported specially.
    component_name = exported(
        TextLine(
            title=_("Component name"),
            required=False, readonly=True))

    title = exported(
        TextLine(title=_("Archive dependency title."), readonly=True))
