# Copyright 2010-2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test BinaryPackageRelease."""

from lp.soyuz.enums import BinaryPackageFormat
from lp.soyuz.interfaces.binarypackagerelease import (
    BinaryPackageReleaseNameLinkageError,
    IBinaryPackageRelease,
    )
from lp.soyuz.interfaces.publishing import PackagePublishingPriority
from lp.testing import TestCaseWithFactory
from lp.testing.layers import DatabaseFunctionalLayer


class TestBinaryPackageRelease(TestCaseWithFactory):
    """Tests for BinaryPackageRelease."""

    layer = DatabaseFunctionalLayer

    def test_provides(self):
        build = self.factory.makeBinaryPackageBuild()
        release = build.createBinaryPackageRelease(
                binarypackagename=self.factory.makeBinaryPackageName(),
                version="0.1", summary="My package",
                description="My description",
                binpackageformat=BinaryPackageFormat.DEB,
                component=self.factory.makeComponent("main"),
                section=self.factory.makeSection("net"),
                priority=PackagePublishingPriority.OPTIONAL,
                installedsize=0, architecturespecific=False)
        self.assertProvides(release, IBinaryPackageRelease)

    def test_user_defined_fields(self):
        build = self.factory.makeBinaryPackageBuild()
        release = build.createBinaryPackageRelease(
                binarypackagename=self.factory.makeBinaryPackageName(),
                version="0.1", summary="My package",
                description="My description",
                binpackageformat=BinaryPackageFormat.DEB,
                component=self.factory.makeComponent("main"),
                section=self.factory.makeSection("net"),
                priority=PackagePublishingPriority.OPTIONAL,
                installedsize=0, architecturespecific=False,
                user_defined_fields=[
                    ("Python-Version", ">= 2.4"),
                    ("Other", "Bla")])
        self.assertEqual([
            ["Python-Version", ">= 2.4"],
            ["Other", "Bla"]], release.user_defined_fields)

    def test_homepage_default(self):
        # By default, no homepage is set.
        bpr = self.factory.makeBinaryPackageRelease()
        self.assertIsNone(bpr.homepage)

    def test_homepage_empty(self):
        # The homepage field can be empty.
        bpr = self.factory.makeBinaryPackageRelease(homepage="")
        self.assertEqual("", bpr.homepage)

    def test_homepage_set_invalid(self):
        # As the homepage field is inherited from the .deb, the URL
        # does not have to be valid.
        bpr = self.factory.makeBinaryPackageRelease(homepage="<invalid<url")
        self.assertEqual("<invalid<url", bpr.homepage)


class TestBinaryPackageReleaseNameConstraints(TestCaseWithFactory):
    """Test name constraints on binary packages of various formats."""

    layer = DatabaseFunctionalLayer

    def test_deb_name_allowed(self):
        self.factory.makeBinaryPackageRelease(binarypackagename="foo")

    def test_deb_name_underscore_disallowed(self):
        self.assertRaisesWithContent(
            BinaryPackageReleaseNameLinkageError,
            r"Invalid package name 'foo_bar'; must match "
            r"/^[a-z0-9][a-z0-9\+\.\-]+$/",
            self.factory.makeBinaryPackageRelease,
            binarypackagename="foo_bar")

    def test_wheel_name_allowed(self):
        self.factory.makeBinaryPackageRelease(
            binarypackagename="foo", binpackageformat=BinaryPackageFormat.WHL)
        self.factory.makeBinaryPackageRelease(
            binarypackagename="Foo_bar",
            binpackageformat=BinaryPackageFormat.WHL)

    def test_wheel_name_plus_disallowed(self):
        self.assertRaisesWithContent(
            BinaryPackageReleaseNameLinkageError,
            r"Invalid Python wheel name 'foo_bar+'; must match "
            r"/^([A-Z0-9]|[A-Z0-9][A-Z0-9._-]*[A-Z0-9])$/i",
            self.factory.makeBinaryPackageRelease,
            binarypackagename="foo_bar+",
            binpackageformat=BinaryPackageFormat.WHL)

    def test_conda_v1_name_allowed(self):
        self.factory.makeBinaryPackageRelease(
            binarypackagename="foo",
            binpackageformat=BinaryPackageFormat.CONDA_V1)
        self.factory.makeBinaryPackageRelease(
            binarypackagename="foo-bar_baz",
            binpackageformat=BinaryPackageFormat.CONDA_V1)
        self.factory.makeBinaryPackageRelease(
            binarypackagename="_foo",
            binpackageformat=BinaryPackageFormat.CONDA_V1)

    def test_conda_v1_name_capital_letter_disallowed(self):
        self.assertRaisesWithContent(
            BinaryPackageReleaseNameLinkageError,
            r"Invalid Conda package name 'Foo'; must match "
            r"/^[a-z0-9_][a-z0-9.+_-]*$/",
            self.factory.makeBinaryPackageRelease,
            binarypackagename="Foo",
            binpackageformat=BinaryPackageFormat.CONDA_V1)

    def test_conda_v1_name_hash_disallowed(self):
        self.assertRaisesWithContent(
            BinaryPackageReleaseNameLinkageError,
            r"Invalid Conda package name 'foo_bar#'; must match "
            r"/^[a-z0-9_][a-z0-9.+_-]*$/",
            self.factory.makeBinaryPackageRelease,
            binarypackagename="foo_bar#",
            binpackageformat=BinaryPackageFormat.CONDA_V1)

    def test_conda_v2_name_allowed(self):
        self.factory.makeBinaryPackageRelease(
            binarypackagename="foo",
            binpackageformat=BinaryPackageFormat.CONDA_V2)
        self.factory.makeBinaryPackageRelease(
            binarypackagename="foo-bar_baz",
            binpackageformat=BinaryPackageFormat.CONDA_V2)
        self.factory.makeBinaryPackageRelease(
            binarypackagename="_foo",
            binpackageformat=BinaryPackageFormat.CONDA_V2)

    def test_conda_v2_name_capital_letter_disallowed(self):
        self.assertRaisesWithContent(
            BinaryPackageReleaseNameLinkageError,
            r"Invalid Conda package name 'Foo'; must match "
            r"/^[a-z0-9_][a-z0-9.+_-]*$/",
            self.factory.makeBinaryPackageRelease,
            binarypackagename="Foo",
            binpackageformat=BinaryPackageFormat.CONDA_V2)

    def test_conda_v2_name_hash_disallowed(self):
        self.assertRaisesWithContent(
            BinaryPackageReleaseNameLinkageError,
            r"Invalid Conda package name 'foo_bar#'; must match "
            r"/^[a-z0-9_][a-z0-9.+_-]*$/",
            self.factory.makeBinaryPackageRelease,
            binarypackagename="foo_bar#",
            binpackageformat=BinaryPackageFormat.CONDA_V2)
