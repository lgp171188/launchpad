# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""References from binary packages to source packages."""

__all__ = [
    "BinarySourceReference",
    "BinarySourceReferenceSet",
]

import warnings

from debian.deb822 import PkgRelation
from storm.locals import Int, Reference
from zope.interface import implementer

from lp.services.database.bulk import create
from lp.services.database.enumcol import DBEnum
from lp.services.database.interfaces import IStore
from lp.services.database.stormbase import StormBase
from lp.soyuz.adapters.archivedependencies import pocket_dependencies
from lp.soyuz.enums import BinarySourceReferenceType
from lp.soyuz.interfaces.binarysourcereference import (
    IBinarySourceReference,
    IBinarySourceReferenceSet,
    UnparsableBuiltUsing,
)


@implementer(IBinarySourceReference)
class BinarySourceReference(StormBase):
    """See `IBinarySourceReference`."""

    __storm_table__ = "BinarySourceReference"

    id = Int(primary=True)

    binary_package_release_id = Int(
        name="binary_package_release", allow_none=False
    )
    binary_package_release = Reference(
        binary_package_release_id, "BinaryPackageRelease.id"
    )

    source_package_release_id = Int(
        name="source_package_release", allow_none=False
    )
    source_package_release = Reference(
        source_package_release_id, "SourcePackageRelease.id"
    )

    reference_type = DBEnum(enum=BinarySourceReferenceType, allow_none=False)

    def __init__(
        self, binary_package_release, source_package_release, reference_type
    ):
        """Construct a `BinarySourceReference`."""
        super().__init__()
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
                % (error,)
            )

        build = bpr.build
        values = []
        for or_rel in parsed_rel:
            if len(or_rel) != 1:
                raise UnparsableBuiltUsing(
                    "Alternatives are not allowed in Built-Using field: %s"
                    % (PkgRelation.str([or_rel]),)
                )
            rel = or_rel[0]
            if rel["version"] is None or rel["version"][0] != "=":
                raise UnparsableBuiltUsing(
                    "Built-Using must contain strict dependencies: %s"
                    % (PkgRelation.str([or_rel]),)
                )

            # "source-package-name (= version)" might refer to any of
            # several SPRs, for example if the same source package was
            # uploaded to a PPA and then uploaded separately (not copied -
            # copies reuse the same SPR) to the distribution's primary
            # archive.  We need to disambiguate this and find an actual SPR
            # so that we can efficiently look up references for a given
            # source publication.
            #
            # However, allowing cross-archive references would make the
            # dominator's job much harder and have other undesirable
            # properties, such as being able to pin a source in Published in
            # a foreign archive just by adding it as a dependency and
            # declaring a Built-Using relationship on it.
            #
            # Therefore, as a safe approximation, try this build's pocket
            # dependencies within its archive and series.  Within this
            # constraint, a name and version should uniquely identify an
            # SPR, although we pick the latest by ID just in case that
            # somehow ends up not being true.
            closest_spph = build.archive.getPublishedSources(
                name=rel["name"],
                version=rel["version"][1],
                distroseries=build.distro_series,
                pocket=pocket_dependencies[build.pocket],
                exact_match=True,
            ).first()
            if closest_spph is None:
                raise UnparsableBuiltUsing(
                    "Built-Using refers to source package %s (= %s), which is "
                    "not known in %s in %s"
                    % (
                        rel["name"],
                        rel["version"][1],
                        build.distro_series.name,
                        build.archive.reference,
                    )
                )
            values.append(
                (bpr.id, closest_spph.sourcepackagerelease_id, reference_type)
            )

        return create(
            (
                BinarySourceReference.binary_package_release_id,
                BinarySourceReference.source_package_release_id,
                BinarySourceReference.reference_type,
            ),
            values,
            get_objects=True,
        )

    @classmethod
    def createFromSourcePackageReleases(cls, bpr, sprs, reference_type):
        """See `IBinarySourceReferenceSet`."""
        relationship = ", ".join(
            ["%s (= %s)" % (spr.name, spr.version) for spr in sprs]
        )
        return cls.createFromRelationship(bpr, relationship, reference_type)

    @classmethod
    def findByBinaryPackageRelease(cls, bpr, reference_type):
        """See `IBinarySourceReferenceSet`."""
        return IStore(BinarySourceReference).find(
            BinarySourceReference,
            BinarySourceReference.binary_package_release == bpr,
            BinarySourceReference.reference_type == reference_type,
        )
