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
            version="0.1",
            summary="My package",
            description="My description",
            binpackageformat=BinaryPackageFormat.DEB,
            component=self.factory.makeComponent("main"),
            section=self.factory.makeSection("net"),
            priority=PackagePublishingPriority.OPTIONAL,
            installedsize=0,
            architecturespecific=False,
        )
        self.assertProvides(release, IBinaryPackageRelease)

    def test_user_defined_fields(self):
        build = self.factory.makeBinaryPackageBuild()
        release = build.createBinaryPackageRelease(
            binarypackagename=self.factory.makeBinaryPackageName(),
            version="0.1",
            summary="My package",
            description="My description",
            binpackageformat=BinaryPackageFormat.DEB,
            component=self.factory.makeComponent("main"),
            section=self.factory.makeSection("net"),
            priority=PackagePublishingPriority.OPTIONAL,
            installedsize=0,
            architecturespecific=False,
            user_defined_fields=[
                ("Python-Version", ">= 2.4"),
                ("Other", "Bla"),
            ],
        )
        self.assertEqual(
            [["Python-Version", ">= 2.4"], ["Other", "Bla"]],
            release.user_defined_fields,
        )

    def test_getUserDefinedField_no_fields(self):
        release = self.factory.makeBinaryPackageRelease()
        self.assertIsNone(release.getUserDefinedField("Missing"))

    def test_getUserDefinedField_present(self):
        release = self.factory.makeBinaryPackageRelease(
            user_defined_fields=[("Key", "value")]
        )
        self.assertEqual("value", release.getUserDefinedField("Key"))
        self.assertEqual("value", release.getUserDefinedField("key"))

    def test_getUserDefinedField_absent(self):
        release = self.factory.makeBinaryPackageRelease(
            user_defined_fields=[("Key", "value")]
        )
        self.assertIsNone(release.getUserDefinedField("Other-Key"))

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

    def assertNameAllowed(self, binarypackagename, binpackageformat):
        # Assertion passes if this returns without raising an exception.
        self.factory.makeBinaryPackageRelease(
            binarypackagename=binarypackagename,
            binpackageformat=binpackageformat,
        )

    def assertNameDisallowed(
        self, expected_message, binarypackagename, binpackageformat
    ):
        self.assertRaisesWithContent(
            BinaryPackageReleaseNameLinkageError,
            expected_message,
            self.factory.makeBinaryPackageRelease,
            binarypackagename=binarypackagename,
            binpackageformat=binpackageformat,
        )

    def test_deb_name_allowed(self):
        self.assertNameAllowed("foo", BinaryPackageFormat.DEB)

    def test_deb_name_underscore_disallowed(self):
        self.assertNameDisallowed(
            r"Invalid package name 'foo_bar'; must match "
            r"/^[a-z0-9][a-z0-9\+\.\-]+$/",
            "foo_bar",
            BinaryPackageFormat.DEB,
        )

    def test_wheel_name_allowed(self):
        self.assertNameAllowed("foo", BinaryPackageFormat.WHL)
        self.assertNameAllowed("Foo_bar", BinaryPackageFormat.WHL)

    def test_wheel_name_plus_disallowed(self):
        self.assertNameDisallowed(
            r"Invalid Python wheel name 'foo_bar+'; must match "
            r"/^([A-Z0-9]|[A-Z0-9][A-Z0-9._-]*[A-Z0-9])$/i",
            "foo_bar+",
            BinaryPackageFormat.WHL,
        )

    def test_conda_v1_name_allowed(self):
        self.assertNameAllowed("foo", BinaryPackageFormat.CONDA_V1)
        self.assertNameAllowed("foo-bar_baz", BinaryPackageFormat.CONDA_V1)
        self.assertNameAllowed("_foo", BinaryPackageFormat.CONDA_V1)

    def test_conda_v1_name_capital_letter_disallowed(self):
        self.assertNameDisallowed(
            r"Invalid Conda package name 'Foo'; must match "
            r"/^[a-z0-9_][a-z0-9.+_-]*$/",
            "Foo",
            BinaryPackageFormat.CONDA_V1,
        )

    def test_conda_v1_name_hash_disallowed(self):
        self.assertNameDisallowed(
            r"Invalid Conda package name 'foo_bar#'; must match "
            r"/^[a-z0-9_][a-z0-9.+_-]*$/",
            "foo_bar#",
            BinaryPackageFormat.CONDA_V1,
        )

    def test_conda_v2_name_allowed(self):
        self.assertNameAllowed("foo", BinaryPackageFormat.CONDA_V2)
        self.assertNameAllowed("foo-bar_baz", BinaryPackageFormat.CONDA_V2)
        self.assertNameAllowed("_foo", BinaryPackageFormat.CONDA_V2)

    def test_conda_v2_name_capital_letter_disallowed(self):
        self.assertNameDisallowed(
            r"Invalid Conda package name 'Foo'; must match "
            r"/^[a-z0-9_][a-z0-9.+_-]*$/",
            "Foo",
            BinaryPackageFormat.CONDA_V2,
        )

    def test_conda_v2_name_hash_disallowed(self):
        self.assertNameDisallowed(
            r"Invalid Conda package name 'foo_bar#'; must match "
            r"/^[a-z0-9_][a-z0-9.+_-]*$/",
            "foo_bar#",
            BinaryPackageFormat.CONDA_V2,
        )
