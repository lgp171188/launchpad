# Copyright 2010-2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Unit tests for DistroSourcePackageRelease pages."""

from zope.security.proxy import removeSecurityProxy

from lp.soyuz.model.distributionsourcepackagerelease import (
    DistributionSourcePackageRelease,
)
from lp.soyuz.tests.test_publishing import SoyuzTestPublisher
from lp.testing import TestCaseWithFactory
from lp.testing.layers import LaunchpadFunctionalLayer
from lp.testing.views import create_initialized_view


class TestDistroSourcePackageReleaseFiles(TestCaseWithFactory):
    # Distro Source package release files should be rendered correctly.

    layer = LaunchpadFunctionalLayer

    def setUp(self):
        super().setUp()
        # The package must be published for the page to render.
        stp = SoyuzTestPublisher()
        distroseries = stp.setUpDefaultDistroSeries()
        source_package_release = stp.getPubSource().sourcepackagerelease
        self.dspr = DistributionSourcePackageRelease(
            distroseries.distribution, source_package_release
        )
        self.library_file = self.factory.makeLibraryFileAlias(
            filename="test_file.dsc", content="0123456789"
        )
        source_package_release.addFile(self.library_file)

    def test_spr_files_one(self):
        # The snippet links to the file when present.
        view = create_initialized_view(self.dspr, "+index")
        html = view.__call__()
        self.assertIn("test_file.dsc", html)

    def test_spr_files_deleted(self):
        # The snippet handles deleted files too.
        removeSecurityProxy(self.library_file).content = None
        view = create_initialized_view(self.dspr, "+index")
        html = view.__call__()
        self.assertIn("test_file.dsc (deleted)", html)
