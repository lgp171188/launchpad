# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""References from binary packages to source packages."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    'BinarySourceReference',
    'BinarySourceReferenceSet',
    ]

import warnings

from debian.deb822 import PkgRelation
from storm.expr import (
    Column,
    Table,
    )
from storm.locals import (
    And,
    Int,
    Join,
    Reference,
    )
from zope.interface import implementer

from lp.registry.model.sourcepackagename import SourcePackageName
from lp.services.database.bulk import (
    create,
    dbify_value,
    )
from lp.services.database.enumcol import DBEnum
from lp.services.database.interfaces import IStore
from lp.services.database.stormbase import StormBase
from lp.services.database.stormexpr import Values
from lp.soyuz.adapters.archivedependencies import expand_dependencies
from lp.soyuz.enums import (
    BinarySourceReferenceType,
    PackagePublishingStatus,
    )
from lp.soyuz.interfaces.binarysourcereference import (
    IBinarySourceReference,
    IBinarySourceReferenceSet,
    UnparsableBuiltUsing,
    )
from lp.soyuz.model.publishing import SourcePackagePublishingHistory
from lp.soyuz.model.sourcepackagerelease import SourcePackageRelease


@implementer(IBinarySourceReference)
class BinarySourceReference(StormBase):
    """See `IBinarySourceReference`."""

    __storm_table__ = "BinarySourceReference"

    id = Int(primary=True)

    binary_package_release_id = Int(
        name="binary_package_release", allow_none=False)
    binary_package_release = Reference(
        binary_package_release_id, "BinaryPackageRelease.id")

    source_package_release_id = Int(
        name="source_package_release", allow_none=False)
    source_package_release = Reference(
        source_package_release_id, "SourcePackageRelease.id")

    reference_type = DBEnum(enum=BinarySourceReferenceType, allow_none=False)

    def __init__(self, binary_package_release, source_package_release,
                 reference_type):
        """Construct a `BinarySourceReference`."""
        super(BinarySourceReference, self).__init__()
        self.binary_package_release = binary_package_release
        self.source_package_release = source_package_release
        self.reference_type = reference_type


@implementer(IBinarySourceReferenceSet)
class BinarySourceReferenceSet:
    """See `IBinarySourceReferenceSet`."""

    @classmethod
    def createFromRelationship(cls, bpr, relationship, reference_type):
        """See `IBinarySourceReferenceSet`."""
        if not relationship:
            return []

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error")
                parsed_rel = PkgRelation.parse_relations(relationship)
        except Warning as error:
            raise UnparsableBuiltUsing(
                "Invalid Built-Using field; cannot be parsed by deb822: %s"
                % (error,))

        build = bpr.build
        dependencies = expand_dependencies(
            build.archive, build.distro_arch_series, build.pocket,
            build.current_component, bpr.sourcepackagename)

        values = []
        for or_rel in parsed_rel:
            if len(or_rel) != 1:
                raise UnparsableBuiltUsing(
                    "Alternatives are not allowed in Built-Using field: %s"
                    % (PkgRelation.str([or_rel]),))
            rel = or_rel[0]
            if rel["version"] is None or rel["version"][0] != "=":
                raise UnparsableBuiltUsing(
                    "Built-Using must contain strict dependencies: %s"
                    % (PkgRelation.str([or_rel]),))
            # "source-package-name (= version)" might refer to any of
            # several SPRs, for example if the same source package was
            # uploaded to a PPA and then uploaded separately (not copied -
            # copies add new references to the same SPR) to the
            # distribution's primary archive.  We need to disambiguate this
            # and find an actual SPR so that we can efficiently look up
            # references for a given source publication.  As an
            # approximation, try this build's archive dependencies in order.
            # This may go wrong, but rarely.
            SPPH = SourcePackagePublishingHistory
            SPN = SourcePackageName
            SPR = SourcePackageRelease
            dependencies_values = Values(
                "dependencies",
                [("index", "integer"),
                 ("archive", "integer"),
                 ("distroseries", "integer"),
                 ("pocket", "integer")],
                [
                    (i, archive.id, das.distroseries.id,
                     dbify_value(SPPH.pocket, pocket))
                    for i, (archive, das, pocket, _) in enumerate(
                        dependencies)])
            dependencies_table = Table("dependencies")
            tables = [
                SPPH,
                Join(
                    dependencies_values,
                    And(
                        SPPH.archive == Column("archive", dependencies_table),
                        SPPH.distroseries ==
                            Column("distroseries", dependencies_table),
                        SPPH.pocket == Column("pocket", dependencies_table))),
                Join(SPN, SPPH.sourcepackagename == SPN.id),
                Join(SPR, SPPH.sourcepackagerelease == SPR.id),
                ]
            closest_spr_id = IStore(SPPH).using(*tables).find(
                SPPH.sourcepackagereleaseID,
                SPN.name == rel["name"],
                SPR.version == rel["version"][1],
                SPPH.status.is_in((
                    PackagePublishingStatus.PENDING,
                    PackagePublishingStatus.PUBLISHED,
                    PackagePublishingStatus.SUPERSEDED)),
                ).order_by(Column("index", dependencies_table)).first()
            if closest_spr_id is None:
                raise UnparsableBuiltUsing(
                    "Built-Using refers to unknown or deleted source package "
                    "%s (= %s)" % (rel["name"], rel["version"][1]))
            values.append((bpr.id, closest_spr_id, reference_type))

        return create(
            (BinarySourceReference.binary_package_release_id,
             BinarySourceReference.source_package_release_id,
             BinarySourceReference.reference_type),
            values, get_objects=True)

    @classmethod
    def makeRelationship(cls, references):
        """See `IBinarySourceReferenceSet`."""
        return PkgRelation.str([
            [{
                "name": reference.source_package_release.name,
                "version": ("=", reference.source_package_release.version),
                }]
            for reference in references])

    @classmethod
    def findByBinaryPackageRelease(cls, bpr, reference_type):
        """See `IBinarySourceReferenceSet`."""
        return IStore(BinarySourceReference).find(
            BinarySourceReference,
            BinarySourceReference.binary_package_release == bpr,
            BinarySourceReference.reference_type == reference_type)
