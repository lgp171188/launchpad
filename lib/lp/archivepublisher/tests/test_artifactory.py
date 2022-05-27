# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Artifactory pool tests."""

from pathlib import PurePath

import transaction
from zope.component import getUtility

from lp.archivepublisher.artifactory import ArtifactoryPool
from lp.archivepublisher.tests.artifactory_fixture import (
    FakeArtifactoryFixture,
    )
from lp.archivepublisher.tests.test_pool import (
    FakeArchive,
    FakeReleaseType,
    PoolTestingFile,
    )
from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.registry.interfaces.sourcepackage import SourcePackageFileType
from lp.services.log.logger import BufferLogger
from lp.soyuz.enums import (
    ArchivePurpose,
    ArchiveRepositoryFormat,
    BinaryPackageFileType,
    )
from lp.soyuz.interfaces.publishing import (
    IPublishingSet,
    PoolFileOverwriteError,
    )
from lp.testing import (
    TestCase,
    TestCaseWithFactory,
    )
from lp.testing.layers import (
    BaseLayer,
    LaunchpadZopelessLayer,
    )


class ArtifactoryPoolTestingFile(PoolTestingFile):
    """`PoolTestingFile` variant for Artifactory.

    Artifactory publishing doesn't use the component to form paths, and has
    some additional features.
    """

    def addToPool(self, component=None):
        return super().addToPool(None)

    def removeFromPool(self, component=None):
        return super().removeFromPool(None)

    def checkExists(self, component=None):
        return super().checkExists(None)

    def checkIsLink(self, component=None):
        return super().checkIsLink(None)

    def checkIsFile(self, component=None):
        return super().checkIsFile(None)

    def getProperties(self):
        path = self.pool.pathFor(
            None, self.source_name, self.source_version, self.filename)
        return path.properties


class TestArtifactoryPool(TestCase):

    layer = BaseLayer

    def setUp(self):
        super().setUp()
        self.base_url = "https://foo.example.com/artifactory"
        self.repository_name = "repository"
        self.artifactory = self.useFixture(
            FakeArtifactoryFixture(self.base_url, self.repository_name))
        root_url = "%s/%s/pool" % (self.base_url, self.repository_name)
        self.pool = ArtifactoryPool(FakeArchive(), root_url, BufferLogger())

    def test_addFile(self):
        foo = ArtifactoryPoolTestingFile(
            self.pool, "foo", "1.0", "foo-1.0.deb",
            release_type=FakeReleaseType.BINARY, release_id=1)
        self.assertFalse(foo.checkIsFile())
        result = foo.addToPool()
        self.assertEqual(self.pool.results.FILE_ADDED, result)
        self.assertTrue(foo.checkIsFile())
        self.assertEqual(
            {
                "launchpad.release-id": ["binary:1"],
                "launchpad.source-name": ["foo"],
                "launchpad.source-version": ["1.0"],
                },
            foo.getProperties())

    def test_addFile_exists_identical(self):
        foo = ArtifactoryPoolTestingFile(
            self.pool, "foo", "1.0", "foo-1.0.deb",
            release_type=FakeReleaseType.BINARY, release_id=1)
        foo.addToPool()
        self.assertTrue(foo.checkIsFile())
        result = foo.addToPool()
        self.assertEqual(self.pool.results.NONE, result)
        self.assertTrue(foo.checkIsFile())

    def test_addFile_exists_overwrite(self):
        foo = ArtifactoryPoolTestingFile(
            self.pool, "foo", "1.0", "foo-1.0.deb",
            release_type=FakeReleaseType.BINARY, release_id=1)
        foo.addToPool()
        self.assertTrue(foo.checkIsFile())
        foo.contents = b"different"
        self.assertRaises(PoolFileOverwriteError, foo.addToPool)

    def test_removeFile(self):
        foo = ArtifactoryPoolTestingFile(
            self.pool, "foo", "1.0", "foo-1.0.deb")
        foo.addToPool()
        self.assertTrue(foo.checkIsFile())
        size = foo.removeFromPool()
        self.assertFalse(foo.checkExists())
        self.assertEqual(3, size)

    def test_getArtifactPatterns_debian(self):
        self.assertEqual(
            [
                "*.ddeb",
                "*.deb",
                "*.diff.*",
                "*.dsc",
                "*.tar.*",
                "*.udeb",
                ],
            self.pool.getArtifactPatterns(ArchiveRepositoryFormat.DEBIAN))

    def test_getArtifactPatterns_python(self):
        self.assertEqual(
            ["*.whl"],
            self.pool.getArtifactPatterns(ArchiveRepositoryFormat.PYTHON))

    def test_getAllArtifacts(self):
        # getAllArtifacts mostly relies on constructing a correct AQL query,
        # which we can't meaningfully test without a real Artifactory
        # instance, although `FakeArtifactoryFixture` tries to do something
        # with it.  This test mainly ensures that we transform the response
        # correctly.
        ArtifactoryPoolTestingFile(
            self.pool, "foo", "1.0", "foo-1.0.deb",
            release_type=FakeReleaseType.BINARY, release_id=1).addToPool()
        ArtifactoryPoolTestingFile(
            self.pool, "foo", "1.1", "foo-1.1.deb",
            release_type=FakeReleaseType.BINARY, release_id=2).addToPool()
        ArtifactoryPoolTestingFile(
            self.pool, "bar", "1.0", "bar-1.0.whl",
            release_type=FakeReleaseType.BINARY, release_id=3).addToPool()
        self.assertEqual(
            {
                PurePath("pool/f/foo/foo-1.0.deb"): {
                    "launchpad.release-id": ["binary:1"],
                    "launchpad.source-name": ["foo"],
                    "launchpad.source-version": ["1.0"],
                    },
                PurePath("pool/f/foo/foo-1.1.deb"): {
                    "launchpad.release-id": ["binary:2"],
                    "launchpad.source-name": ["foo"],
                    "launchpad.source-version": ["1.1"],
                    },
                },
            self.pool.getAllArtifacts(
                self.repository_name, ArchiveRepositoryFormat.DEBIAN))
        self.assertEqual(
            {
                PurePath("pool/b/bar/bar-1.0.whl"): {
                    "launchpad.release-id": ["binary:3"],
                    "launchpad.source-name": ["bar"],
                    "launchpad.source-version": ["1.0"],
                    },
                },
            self.pool.getAllArtifacts(
                self.repository_name, ArchiveRepositoryFormat.PYTHON))


class TestArtifactoryPoolFromLibrarian(TestCaseWithFactory):

    layer = LaunchpadZopelessLayer

    def setUp(self):
        super().setUp()
        self.base_url = "https://foo.example.com/artifactory"
        self.repository_name = "repository"
        self.artifactory = self.useFixture(
            FakeArtifactoryFixture(self.base_url, self.repository_name))
        root_url = "%s/%s/pool" % (self.base_url, self.repository_name)
        self.archive = self.factory.makeArchive(purpose=ArchivePurpose.PPA)
        self.pool = ArtifactoryPool(self.archive, root_url, BufferLogger())

    def test_updateProperties_debian_source(self):
        dses = [
            self.factory.makeDistroSeries(
                distribution=self.archive.distribution)
            for _ in range(2)]
        spph = self.factory.makeSourcePackagePublishingHistory(
            archive=self.archive, distroseries=dses[0],
            pocket=PackagePublishingPocket.RELEASE, component="main",
            sourcepackagename="foo", version="1.0")
        spr = spph.sourcepackagerelease
        sprf = self.factory.makeSourcePackageReleaseFile(
            sourcepackagerelease=spr,
            library_file=self.factory.makeLibraryFileAlias(
                filename="foo_1.0.dsc"),
            filetype=SourcePackageFileType.DSC)
        spphs = [spph]
        spphs.append(spph.copyTo(
            dses[1], PackagePublishingPocket.RELEASE, self.archive))
        transaction.commit()
        self.pool.addFile(
            None, spr.name, spr.version, sprf.libraryfile.filename, sprf)
        path = self.pool.rootpath / "f" / "foo" / "foo_1.0.dsc"
        self.assertTrue(path.exists())
        self.assertFalse(path.is_symlink())
        self.assertEqual(
            {
                "launchpad.release-id": ["source:%d" % spr.id],
                "launchpad.source-name": ["foo"],
                "launchpad.source-version": ["1.0"],
                },
            path.properties)
        self.pool.updateProperties(
            spr.name, spr.version, sprf.libraryfile.filename, spphs)
        self.assertEqual(
            {
                "launchpad.release-id": ["source:%d" % spr.id],
                "launchpad.source-name": ["foo"],
                "launchpad.source-version": ["1.0"],
                "deb.distribution": list(sorted(ds.name for ds in dses)),
                "deb.component": ["main"],
                },
            path.properties)

    def test_updateProperties_debian_binary_multiple_series(self):
        dses = [
            self.factory.makeDistroSeries(
                distribution=self.archive.distribution)
            for _ in range(2)]
        processor = self.factory.makeProcessor()
        dases = [
            self.factory.makeDistroArchSeries(
                distroseries=ds, architecturetag=processor.name)
            for ds in dses]
        spr = self.factory.makeSourcePackageRelease(
            archive=self.archive, sourcepackagename="foo", version="1.0")
        bpph = self.factory.makeBinaryPackagePublishingHistory(
            archive=self.archive, distroarchseries=dases[0],
            pocket=PackagePublishingPocket.RELEASE, component="main",
            source_package_release=spr, binarypackagename="foo",
            architecturespecific=True)
        bpr = bpph.binarypackagerelease
        bpf = self.factory.makeBinaryPackageFile(
            binarypackagerelease=bpr,
            library_file=self.factory.makeLibraryFileAlias(
                filename="foo_1.0_%s.deb" % processor.name),
            filetype=BinaryPackageFileType.DEB)
        bpphs = [bpph]
        bpphs.append(bpph.copyTo(
            dses[1], PackagePublishingPocket.RELEASE, self.archive)[0])
        transaction.commit()
        self.pool.addFile(
            None, bpr.sourcepackagename, bpr.sourcepackageversion,
            bpf.libraryfile.filename, bpf)
        path = (
            self.pool.rootpath / "f" / "foo" /
            ("foo_1.0_%s.deb" % processor.name))
        self.assertTrue(path.exists())
        self.assertFalse(path.is_symlink())
        self.assertEqual(
            {
                "launchpad.release-id": ["binary:%d" % bpr.id],
                "launchpad.source-name": ["foo"],
                "launchpad.source-version": ["1.0"],
                },
            path.properties)
        self.pool.updateProperties(
            bpr.sourcepackagename, bpr.sourcepackageversion,
            bpf.libraryfile.filename, bpphs)
        self.assertEqual(
            {
                "launchpad.release-id": ["binary:%d" % bpr.id],
                "launchpad.source-name": ["foo"],
                "launchpad.source-version": ["1.0"],
                "deb.distribution": list(sorted(ds.name for ds in dses)),
                "deb.component": ["main"],
                "deb.architecture": [processor.name],
                },
            path.properties)

    def test_updateProperties_debian_binary_multiple_architectures(self):
        ds = self.factory.makeDistroSeries(
            distribution=self.archive.distribution)
        dases = [
            self.factory.makeDistroArchSeries(distroseries=ds)
            for _ in range(2)]
        spr = self.factory.makeSourcePackageRelease(
            archive=self.archive, sourcepackagename="foo", version="1.0")
        bpb = self.factory.makeBinaryPackageBuild(
            archive=self.archive, source_package_release=spr,
            distroarchseries=dases[0], pocket=PackagePublishingPocket.RELEASE)
        bpr = self.factory.makeBinaryPackageRelease(
            binarypackagename="foo", build=bpb, component="main",
            architecturespecific=False)
        bpf = self.factory.makeBinaryPackageFile(
            binarypackagerelease=bpr,
            library_file=self.factory.makeLibraryFileAlias(
                filename="foo_1.0_all.deb"),
            filetype=BinaryPackageFileType.DEB)
        bpphs = getUtility(IPublishingSet).publishBinaries(
            self.archive, ds, PackagePublishingPocket.RELEASE,
            {bpr: (bpr.component, bpr.section, bpr.priority, None)})
        transaction.commit()
        self.pool.addFile(
            None, bpr.sourcepackagename, bpr.sourcepackageversion,
            bpf.libraryfile.filename, bpf)
        path = self.pool.rootpath / "f" / "foo" / "foo_1.0_all.deb"
        self.assertTrue(path.exists())
        self.assertFalse(path.is_symlink())
        self.assertEqual(
            {
                "launchpad.release-id": ["binary:%d" % bpr.id],
                "launchpad.source-name": ["foo"],
                "launchpad.source-version": ["1.0"],
                },
            path.properties)
        self.pool.updateProperties(
            bpr.sourcepackagename, bpr.sourcepackageversion,
            bpf.libraryfile.filename, bpphs)
        self.assertEqual(
            {
                "launchpad.release-id": ["binary:%d" % bpr.id],
                "launchpad.source-name": ["foo"],
                "launchpad.source-version": ["1.0"],
                "deb.distribution": [ds.name],
                "deb.component": ["main"],
                "deb.architecture": list(sorted(
                    das.architecturetag for das in dases)),
                },
            path.properties)

    def test_updateProperties_preserves_externally_set_properties(self):
        # Artifactory sets some properties by itself as part of scanning
        # packages.  We leave those untouched.
        ds = self.factory.makeDistroSeries(
            distribution=self.archive.distribution)
        das = self.factory.makeDistroArchSeries(distroseries=ds)
        spr = self.factory.makeSourcePackageRelease(
            archive=self.archive, sourcepackagename="foo", version="1.0")
        bpb = self.factory.makeBinaryPackageBuild(
            archive=self.archive, source_package_release=spr,
            distroarchseries=das, pocket=PackagePublishingPocket.RELEASE)
        bpr = self.factory.makeBinaryPackageRelease(
            binarypackagename="foo", build=bpb, component="main",
            architecturespecific=False)
        bpf = self.factory.makeBinaryPackageFile(
            binarypackagerelease=bpr,
            library_file=self.factory.makeLibraryFileAlias(
                filename="foo_1.0_all.deb"),
            filetype=BinaryPackageFileType.DEB)
        bpphs = getUtility(IPublishingSet).publishBinaries(
            self.archive, ds, PackagePublishingPocket.RELEASE,
            {bpr: (bpr.component, bpr.section, bpr.priority, None)})
        transaction.commit()
        self.pool.addFile(
            None, bpr.sourcepackagename, bpr.sourcepackageversion,
            bpf.libraryfile.filename, bpf)
        path = self.pool.rootpath / "f" / "foo" / "foo_1.0_all.deb"
        path.set_properties({"deb.version": ["1.0"]}, recursive=False)
        self.assertEqual(
            {
                "launchpad.release-id": ["binary:%d" % bpr.id],
                "launchpad.source-name": ["foo"],
                "launchpad.source-version": ["1.0"],
                "deb.version": ["1.0"],
                },
            path.properties)
        self.pool.updateProperties(
            bpr.sourcepackagename, bpr.sourcepackageversion,
            bpf.libraryfile.filename, bpphs)
        self.assertEqual(
            {
                "launchpad.release-id": ["binary:%d" % bpr.id],
                "launchpad.source-name": ["foo"],
                "launchpad.source-version": ["1.0"],
                "deb.distribution": [ds.name],
                "deb.component": ["main"],
                "deb.architecture": [das.architecturetag],
                "deb.version": ["1.0"],
                },
            path.properties)
