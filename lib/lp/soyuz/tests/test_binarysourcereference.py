# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test references from binary packages to source packages."""

import re

from testtools.matchers import MatchesSetwise, MatchesStructure
from testtools.testcase import ExpectedException
from zope.component import getUtility

from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.soyuz.enums import ArchivePurpose, BinarySourceReferenceType
from lp.soyuz.interfaces.binarysourcereference import (
    IBinarySourceReferenceSet,
    UnparsableBuiltUsing,
)
from lp.testing import TestCaseWithFactory
from lp.testing.layers import DatabaseFunctionalLayer


class TestBinarySourceReference(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.reference_set = getUtility(IBinarySourceReferenceSet)

    def test_createFromRelationship_empty(self):
        bpr = self.factory.makeBinaryPackageRelease()
        self.assertEqual(
            [],
            self.reference_set.createFromRelationship(
                bpr, "", BinarySourceReferenceType.BUILT_USING
            ),
        )

    def test_createFromRelationship_nonsense(self):
        bpr = self.factory.makeBinaryPackageRelease()
        expected_message = (
            r"Invalid Built-Using field; cannot be parsed by deb822: .*"
        )
        with ExpectedException(UnparsableBuiltUsing, expected_message):
            self.reference_set.createFromRelationship(
                bpr, "nonsense (", BinarySourceReferenceType.BUILT_USING
            )
        with ExpectedException(UnparsableBuiltUsing, expected_message):
            self.reference_set.createFromRelationship(
                bpr, "nonsense )= 1(", BinarySourceReferenceType.BUILT_USING
            )
        with ExpectedException(UnparsableBuiltUsing, expected_message):
            self.reference_set.createFromRelationship(
                bpr,
                "nonsense (nonsense)",
                BinarySourceReferenceType.BUILT_USING,
            )

    def test_createFromRelationship_alternatives(self):
        bpr = self.factory.makeBinaryPackageRelease()
        expected_message = (
            r"Alternatives are not allowed in Built-Using field: "
            r"foo \(= 1\) \| bar \(= 2\)"
        )
        with ExpectedException(UnparsableBuiltUsing, expected_message):
            self.reference_set.createFromRelationship(
                bpr,
                "foo (= 1) | bar (= 2)",
                BinarySourceReferenceType.BUILT_USING,
            )

    def test_createFromRelationship_no_version(self):
        bpr = self.factory.makeBinaryPackageRelease()
        expected_message = r"Built-Using must contain strict dependencies: foo"
        with ExpectedException(UnparsableBuiltUsing, expected_message):
            self.reference_set.createFromRelationship(
                bpr, "foo", BinarySourceReferenceType.BUILT_USING
            )

    def test_createFromRelationship_inequality(self):
        bpr = self.factory.makeBinaryPackageRelease()
        expected_message = (
            r"Built-Using must contain strict dependencies: foo \(>= 1\)"
        )
        with ExpectedException(UnparsableBuiltUsing, expected_message):
            self.reference_set.createFromRelationship(
                bpr, "foo (>= 1)", BinarySourceReferenceType.BUILT_USING
            )

    def test_createFromRelationship_unknown_source_package_name(self):
        bpr = self.factory.makeBinaryPackageRelease()
        relationship = "nonexistent (= 1)"
        expected_message = (
            r"Built-Using refers to source package %s, which is not known in "
            r"%s in %s"
            % (
                re.escape(relationship),
                bpr.build.distro_series.name,
                bpr.build.archive.reference,
            )
        )
        with ExpectedException(UnparsableBuiltUsing, expected_message):
            self.reference_set.createFromRelationship(
                bpr, relationship, BinarySourceReferenceType.BUILT_USING
            )

    def test_createFromRelationship_unknown_source_package_version(self):
        bpr = self.factory.makeBinaryPackageRelease()
        spph = self.factory.makeSourcePackagePublishingHistory(
            archive=bpr.build.archive,
            distroseries=bpr.build.distro_series,
            component=bpr.build.current_component,
        )
        spr = spph.sourcepackagerelease
        relationship = "%s (= %s.1)" % (spr.name, spr.version)
        expected_message = (
            r"Built-Using refers to source package %s, which is not known in "
            r"%s in %s"
            % (
                re.escape(relationship),
                bpr.build.distro_series.name,
                bpr.build.archive.reference,
            )
        )
        with ExpectedException(UnparsableBuiltUsing, expected_message):
            self.reference_set.createFromRelationship(
                bpr, relationship, BinarySourceReferenceType.BUILT_USING
            )

    def test_createFromRelationship_simple(self):
        bpr = self.factory.makeBinaryPackageRelease()
        spphs = [
            self.factory.makeSourcePackagePublishingHistory(
                archive=bpr.build.archive,
                distroseries=bpr.build.distro_series,
                pocket=bpr.build.pocket,
            )
            for _ in range(3)
        ]
        sprs = [spph.sourcepackagerelease for spph in spphs]
        # Create a few more SPPHs with slight mismatches to ensure that
        # createFromRelationship matches correctly.
        self.factory.makeSourcePackagePublishingHistory(
            archive=bpr.build.archive,
            pocket=bpr.build.pocket,
            sourcepackagename=sprs[0].name,
            version=sprs[0].version,
        )
        self.factory.makeSourcePackagePublishingHistory(
            archive=bpr.build.archive,
            distroseries=bpr.build.distro_series,
            pocket=PackagePublishingPocket.BACKPORTS,
            sourcepackagename=sprs[0].name,
            version=sprs[0].version,
        )
        self.factory.makeSourcePackagePublishingHistory(
            archive=bpr.build.archive,
            distroseries=bpr.build.distro_series,
            pocket=bpr.build.pocket,
            sourcepackagename=sprs[0].name,
        )
        self.factory.makeSourcePackagePublishingHistory(
            archive=bpr.build.archive,
            distroseries=bpr.build.distro_series,
            pocket=bpr.build.pocket,
            version=sprs[0].version,
        )
        self.factory.makeSourcePackagePublishingHistory()
        relationship = "%s (= %s), %s (= %s)" % (
            sprs[0].name,
            sprs[0].version,
            sprs[1].name,
            sprs[1].version,
        )
        bsrs = self.reference_set.createFromRelationship(
            bpr, relationship, BinarySourceReferenceType.BUILT_USING
        )
        self.assertThat(
            bsrs,
            MatchesSetwise(
                *(
                    MatchesStructure.byEquality(
                        binary_package_release=bpr,
                        source_package_release=spr,
                        reference_type=BinarySourceReferenceType.BUILT_USING,
                    )
                    for spr in sprs[:2]
                )
            ),
        )

    def test_createFromRelationship_foreign_archive(self):
        # createFromRelationship only considers SPRs found in the same
        # archive as the build.
        archive = self.factory.makeArchive(purpose=ArchivePurpose.PPA)
        build = self.factory.makeBinaryPackageBuild(archive=archive)
        bpr = self.factory.makeBinaryPackageRelease(build=build)
        spph = self.factory.makeSourcePackagePublishingHistory(
            archive=build.distro_series.main_archive,
            distroseries=build.distro_series,
            pocket=build.pocket,
        )
        spr = spph.sourcepackagerelease
        relationship = "%s (= %s)" % (spr.name, spr.version)
        expected_message = (
            r"Built-Using refers to source package %s, which is not known in "
            r"%s in %s"
            % (
                re.escape(relationship),
                build.distro_series.name,
                build.archive.reference,
            )
        )
        with ExpectedException(UnparsableBuiltUsing, expected_message):
            self.reference_set.createFromRelationship(
                bpr, relationship, BinarySourceReferenceType.BUILT_USING
            )

    def test_findByBinaryPackageRelease_empty(self):
        bpr = self.factory.makeBinaryPackageRelease()
        self.assertContentEqual(
            [],
            self.reference_set.findByBinaryPackageRelease(
                bpr, BinarySourceReferenceType.BUILT_USING
            ),
        )

    def test_findByBinaryPackageRelease(self):
        bprs = [self.factory.makeBinaryPackageRelease() for _ in range(2)]
        all_sprs = []
        for bpr in bprs:
            spphs = [
                self.factory.makeSourcePackagePublishingHistory(
                    archive=bpr.build.archive,
                    distroseries=bpr.build.distro_series,
                    pocket=bpr.build.pocket,
                )
                for _ in range(2)
            ]
            sprs = [spph.sourcepackagerelease for spph in spphs]
            all_sprs.extend(sprs)
            self.reference_set.createFromSourcePackageReleases(
                bpr, sprs, BinarySourceReferenceType.BUILT_USING
            )
        other_bpr = self.factory.makeBinaryPackageRelease()
        self.assertThat(
            self.reference_set.findByBinaryPackageRelease(
                bprs[0], BinarySourceReferenceType.BUILT_USING
            ),
            MatchesSetwise(
                *(
                    MatchesStructure.byEquality(
                        binary_package_release=bprs[0],
                        source_package_release=spr,
                        reference_type=BinarySourceReferenceType.BUILT_USING,
                    )
                    for spr in all_sprs[:2]
                )
            ),
        )
        self.assertThat(
            self.reference_set.findByBinaryPackageRelease(
                bprs[1], BinarySourceReferenceType.BUILT_USING
            ),
            MatchesSetwise(
                *(
                    MatchesStructure.byEquality(
                        binary_package_release=bprs[1],
                        source_package_release=spr,
                        reference_type=BinarySourceReferenceType.BUILT_USING,
                    )
                    for spr in all_sprs[2:]
                )
            ),
        )
        self.assertContentEqual(
            [],
            self.reference_set.findByBinaryPackageRelease(
                other_bpr, BinarySourceReferenceType.BUILT_USING
            ),
        )
