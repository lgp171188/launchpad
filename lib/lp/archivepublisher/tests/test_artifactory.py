# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Artifactory pool tests."""

from pathlib import PurePath

from artifactory import ArtifactoryPath
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
from lp.registry.interfaces.sourcepackage import (
    SourcePackageFileType,
    SourcePackageType,
    )
from lp.services.log.logger import BufferLogger
from lp.soyuz.enums import (
    ArchivePurpose,
    ArchiveRepositoryFormat,
    BinaryPackageFileType,
    BinaryPackageFormat,
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

    def makePool(self, repository_format=ArchiveRepositoryFormat.DEBIAN):
        # Matches behaviour of lp.archivepublisher.config.getPubConfig.
        root_url = "%s/%s" % (self.base_url, self.repository_name)
        if repository_format == ArchiveRepositoryFormat.DEBIAN:
            root_url += "/pool"
        return ArtifactoryPool(
            FakeArchive(repository_format), root_url, BufferLogger())

    def test_pathFor_debian_without_file(self):
        pool = self.makePool()
        self.assertEqual(
            ArtifactoryPath(
                "https://foo.example.com/artifactory/repository/pool/f/foo"),
            pool.pathFor(None, "foo", "1.0"))

    def test_pathFor_debian_with_file(self):
        pool = self.makePool()
        self.assertEqual(
            ArtifactoryPath(
                "https://foo.example.com/artifactory/repository/pool/f/foo/"
                "foo-1.0.deb"),
            pool.pathFor(None, "foo", "1.0", "foo-1.0.deb"))

    def test_pathFor_python_without_file(self):
        pool = self.makePool(ArchiveRepositoryFormat.PYTHON)
        self.assertEqual(
            ArtifactoryPath(
                "https://foo.example.com/artifactory/repository/foo/1.0"),
            pool.pathFor(None, "foo", "1.0"))

    def test_pathFor_python_with_file(self):
        pool = self.makePool(ArchiveRepositoryFormat.PYTHON)
        self.assertEqual(
            ArtifactoryPath(
                "https://foo.example.com/artifactory/repository/foo/1.0/"
                "foo-1.0.whl"),
            pool.pathFor(None, "foo", "1.0", "foo-1.0.whl"))

    def test_addFile(self):
        pool = self.makePool()
        foo = ArtifactoryPoolTestingFile(
            pool=pool, source_name="foo", source_version="1.0",
            filename="foo-1.0.deb", release_type=FakeReleaseType.BINARY,
            release_id=1)
        self.assertFalse(foo.checkIsFile())
        result = foo.addToPool()
        self.assertEqual(pool.results.FILE_ADDED, result)
        self.assertTrue(foo.checkIsFile())
        self.assertEqual(
            {
                "launchpad.release-id": ["binary:1"],
                "launchpad.source-name": ["foo"],
                "launchpad.source-version": ["1.0"],
                },
            foo.getProperties())

    def test_addFile_exists_identical(self):
        pool = self.makePool()
        foo = ArtifactoryPoolTestingFile(
            pool=pool, source_name="foo", source_version="1.0",
            filename="foo-1.0.deb", release_type=FakeReleaseType.BINARY,
            release_id=1)
        foo.addToPool()
        self.assertTrue(foo.checkIsFile())
        result = foo.addToPool()
        self.assertEqual(pool.results.NONE, result)
        self.assertTrue(foo.checkIsFile())

    def test_addFile_exists_overwrite(self):
        pool = self.makePool()
        foo = ArtifactoryPoolTestingFile(
            pool=pool, source_name="foo", source_version="1.0",
            filename="foo-1.0.deb", release_type=FakeReleaseType.BINARY,
            release_id=1)
        foo.addToPool()
        self.assertTrue(foo.checkIsFile())
        foo.contents = b"different"
        self.assertRaises(PoolFileOverwriteError, foo.addToPool)

    def test_removeFile(self):
        pool = self.makePool()
        foo = ArtifactoryPoolTestingFile(
            pool=pool, source_name="foo", source_version="1.0",
            filename="foo-1.0.deb")
        foo.addToPool()
        self.assertTrue(foo.checkIsFile())
        size = foo.removeFromPool()
        self.assertFalse(foo.checkExists())
        self.assertEqual(3, size)

    def test_getArtifactPatterns_debian(self):
        pool = self.makePool()
        self.assertEqual(
            [
                "*.ddeb",
                "*.deb",
                "*.diff.*",
                "*.dsc",
                "*.tar.*",
                "*.udeb",
                ],
            pool.getArtifactPatterns(ArchiveRepositoryFormat.DEBIAN))

    def test_getArtifactPatterns_python(self):
        pool = self.makePool()
        self.assertEqual(
            ["*.whl"],
            pool.getArtifactPatterns(ArchiveRepositoryFormat.PYTHON))

    def test_getAllArtifacts(self):
        # getAllArtifacts mostly relies on constructing a correct AQL query,
        # which we can't meaningfully test without a real Artifactory
        # instance, although `FakeArtifactoryFixture` tries to do something
        # with it.  This test mainly ensures that we transform the response
        # correctly.
        pool = self.makePool()
        ArtifactoryPoolTestingFile(
            pool=pool, source_name="foo", source_version="1.0",
            filename="foo-1.0.deb", release_type=FakeReleaseType.BINARY,
            release_id=1).addToPool()
        ArtifactoryPoolTestingFile(
            pool=pool, source_name="foo", source_version="1.1",
            filename="foo-1.1.deb", release_type=FakeReleaseType.BINARY,
            release_id=2).addToPool()
        ArtifactoryPoolTestingFile(
            pool=pool, source_name="bar", source_version="1.0",
            filename="bar-1.0.whl", release_type=FakeReleaseType.BINARY,
            release_id=3).addToPool()
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
            pool.getAllArtifacts(
                self.repository_name, ArchiveRepositoryFormat.DEBIAN))
        self.assertEqual(
            {
                PurePath("pool/b/bar/bar-1.0.whl"): {
                    "launchpad.release-id": ["binary:3"],
                    "launchpad.source-name": ["bar"],
                    "launchpad.source-version": ["1.0"],
                    },
                },
            pool.getAllArtifacts(
                self.repository_name, ArchiveRepositoryFormat.PYTHON))


class TestArtifactoryPoolFromLibrarian(TestCaseWithFactory):

    layer = LaunchpadZopelessLayer

    def setUp(self):
        super().setUp()
        self.base_url = "https://foo.example.com/artifactory"
        self.repository_name = "repository"
        self.artifactory = self.useFixture(
            FakeArtifactoryFixture(self.base_url, self.repository_name))

    def makePool(self, repository_format=ArchiveRepositoryFormat.DEBIAN):
        # Matches behaviour of lp.archivepublisher.config.getPubConfig.
        root_url = "%s/%s" % (self.base_url, self.repository_name)
        if repository_format == ArchiveRepositoryFormat.DEBIAN:
            root_url += "/pool"
        archive = self.factory.makeArchive(
            purpose=ArchivePurpose.PPA, repository_format=repository_format)
        return ArtifactoryPool(archive, root_url, BufferLogger())

    def test_updateProperties_debian_source(self):
        pool = self.makePool()
        dses = [
            self.factory.makeDistroSeries(
                distribution=pool.archive.distribution)
            for _ in range(2)]
        spph = self.factory.makeSourcePackagePublishingHistory(
            archive=pool.archive, distroseries=dses[0],
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
            dses[1], PackagePublishingPocket.RELEASE, pool.archive))
        transaction.commit()
        pool.addFile(
            None, spr.name, spr.version, sprf.libraryfile.filename, sprf)
        path = pool.rootpath / "f" / "foo" / "foo_1.0.dsc"
        self.assertTrue(path.exists())
        self.assertFalse(path.is_symlink())
        self.assertEqual(
            {
                "launchpad.release-id": ["source:%d" % spr.id],
                "launchpad.source-name": ["foo"],
                "launchpad.source-version": ["1.0"],
                },
            path.properties)
        pool.updateProperties(
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
        pool = self.makePool()
        dses = [
            self.factory.makeDistroSeries(
                distribution=pool.archive.distribution)
            for _ in range(2)]
        processor = self.factory.makeProcessor()
        dases = [
            self.factory.makeDistroArchSeries(
                distroseries=ds, architecturetag=processor.name)
            for ds in dses]
        spr = self.factory.makeSourcePackageRelease(
            archive=pool.archive, sourcepackagename="foo", version="1.0")
        bpph = self.factory.makeBinaryPackagePublishingHistory(
            archive=pool.archive, distroarchseries=dases[0],
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
            dses[1], PackagePublishingPocket.RELEASE, pool.archive)[0])
        transaction.commit()
        pool.addFile(
            None, bpr.sourcepackagename, bpr.sourcepackageversion,
            bpf.libraryfile.filename, bpf)
        path = (
            pool.rootpath / "f" / "foo" / ("foo_1.0_%s.deb" % processor.name))
        self.assertTrue(path.exists())
        self.assertFalse(path.is_symlink())
        self.assertEqual(
            {
                "launchpad.release-id": ["binary:%d" % bpr.id],
                "launchpad.source-name": ["foo"],
                "launchpad.source-version": ["1.0"],
                },
            path.properties)
        pool.updateProperties(
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
        pool = self.makePool()
        ds = self.factory.makeDistroSeries(
            distribution=pool.archive.distribution)
        dases = [
            self.factory.makeDistroArchSeries(distroseries=ds)
            for _ in range(2)]
        spr = self.factory.makeSourcePackageRelease(
            archive=pool.archive, sourcepackagename="foo", version="1.0")
        bpb = self.factory.makeBinaryPackageBuild(
            archive=pool.archive, source_package_release=spr,
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
            pool.archive, ds, PackagePublishingPocket.RELEASE,
            {bpr: (bpr.component, bpr.section, bpr.priority, None)})
        transaction.commit()
        pool.addFile(
            None, bpr.sourcepackagename, bpr.sourcepackageversion,
            bpf.libraryfile.filename, bpf)
        path = pool.rootpath / "f" / "foo" / "foo_1.0_all.deb"
        self.assertTrue(path.exists())
        self.assertFalse(path.is_symlink())
        self.assertEqual(
            {
                "launchpad.release-id": ["binary:%d" % bpr.id],
                "launchpad.source-name": ["foo"],
                "launchpad.source-version": ["1.0"],
                },
            path.properties)
        pool.updateProperties(
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

    def test_updateProperties_python_sdist(self):
        pool = self.makePool(ArchiveRepositoryFormat.PYTHON)
        dses = [
            self.factory.makeDistroSeries(
                distribution=pool.archive.distribution)
            for _ in range(2)]
        spph = self.factory.makeSourcePackagePublishingHistory(
            archive=pool.archive, distroseries=dses[0],
            pocket=PackagePublishingPocket.RELEASE, component="main",
            sourcepackagename="foo", version="1.0", channel="edge",
            format=SourcePackageType.SDIST)
        spr = spph.sourcepackagerelease
        sprf = self.factory.makeSourcePackageReleaseFile(
            sourcepackagerelease=spr,
            library_file=self.factory.makeLibraryFileAlias(
                filename="foo-1.0.tar.gz"),
            filetype=SourcePackageFileType.SDIST)
        spphs = [spph]
        spphs.append(spph.copyTo(
            dses[1], PackagePublishingPocket.RELEASE, pool.archive))
        transaction.commit()
        pool.addFile(
            None, spr.name, spr.version, sprf.libraryfile.filename, sprf)
        path = pool.rootpath / "foo" / "1.0" / "foo-1.0.tar.gz"
        self.assertTrue(path.exists())
        self.assertFalse(path.is_symlink())
        self.assertEqual(
            {
                "launchpad.release-id": ["source:%d" % spr.id],
                "launchpad.source-name": ["foo"],
                "launchpad.source-version": ["1.0"],
                },
            path.properties)
        pool.updateProperties(
            spr.name, spr.version, sprf.libraryfile.filename, spphs)
        self.assertEqual(
            {
                "launchpad.release-id": ["source:%d" % spr.id],
                "launchpad.source-name": ["foo"],
                "launchpad.source-version": ["1.0"],
                "launchpad.channel": list(
                    sorted("%s:edge" % ds.name for ds in dses)),
                },
            path.properties)

    def test_updateProperties_python_wheel(self):
        pool = self.makePool(ArchiveRepositoryFormat.PYTHON)
        dses = [
            self.factory.makeDistroSeries(
                distribution=pool.archive.distribution)
            for _ in range(2)]
        processor = self.factory.makeProcessor()
        dases = [
            self.factory.makeDistroArchSeries(
                distroseries=ds, architecturetag=processor.name)
            for ds in dses]
        spr = self.factory.makeSourcePackageRelease(
            archive=pool.archive, sourcepackagename="foo", version="1.0",
            format=SourcePackageType.SDIST)
        bpph = self.factory.makeBinaryPackagePublishingHistory(
            archive=pool.archive, distroarchseries=dases[0],
            pocket=PackagePublishingPocket.RELEASE, component="main",
            source_package_release=spr, binarypackagename="foo",
            binpackageformat=BinaryPackageFormat.WHL,
            architecturespecific=False, channel="edge")
        bpr = bpph.binarypackagerelease
        bpf = self.factory.makeBinaryPackageFile(
            binarypackagerelease=bpr,
            library_file=self.factory.makeLibraryFileAlias(
                filename="foo-1.0-py3-none-any.whl"),
            filetype=BinaryPackageFileType.WHL)
        bpphs = [bpph]
        bpphs.append(
            getUtility(IPublishingSet).copyBinaries(
                pool.archive, dses[1], PackagePublishingPocket.RELEASE, [bpph],
                channel="edge")[0])
        transaction.commit()
        pool.addFile(
            None, bpr.sourcepackagename, bpr.sourcepackageversion,
            bpf.libraryfile.filename, bpf)
        path = pool.rootpath / "foo" / "1.0" / "foo-1.0-py3-none-any.whl"
        self.assertTrue(path.exists())
        self.assertFalse(path.is_symlink())
        self.assertEqual(
            {
                "launchpad.release-id": ["binary:%d" % bpr.id],
                "launchpad.source-name": ["foo"],
                "launchpad.source-version": ["1.0"],
                },
            path.properties)
        pool.updateProperties(
            bpr.sourcepackagename, bpr.sourcepackageversion,
            bpf.libraryfile.filename, bpphs)
        self.assertEqual(
            {
                "launchpad.release-id": ["binary:%d" % bpr.id],
                "launchpad.source-name": ["foo"],
                "launchpad.source-version": ["1.0"],
                "launchpad.channel": list(
                    sorted("%s:edge" % ds.name for ds in dses)),
                },
            path.properties)

    def test_updateProperties_preserves_externally_set_properties(self):
        # Artifactory sets some properties by itself as part of scanning
        # packages.  We leave those untouched.
        pool = self.makePool()
        ds = self.factory.makeDistroSeries(
            distribution=pool.archive.distribution)
        das = self.factory.makeDistroArchSeries(distroseries=ds)
        spr = self.factory.makeSourcePackageRelease(
            archive=pool.archive, sourcepackagename="foo", version="1.0")
        bpb = self.factory.makeBinaryPackageBuild(
            archive=pool.archive, source_package_release=spr,
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
            pool.archive, ds, PackagePublishingPocket.RELEASE,
            {bpr: (bpr.component, bpr.section, bpr.priority, None)})
        transaction.commit()
        pool.addFile(
            None, bpr.sourcepackagename, bpr.sourcepackageversion,
            bpf.libraryfile.filename, bpf)
        path = pool.rootpath / "f" / "foo" / "foo_1.0_all.deb"
        path.set_properties({"deb.version": ["1.0"]}, recursive=False)
        self.assertEqual(
            {
                "launchpad.release-id": ["binary:%d" % bpr.id],
                "launchpad.source-name": ["foo"],
                "launchpad.source-version": ["1.0"],
                "deb.version": ["1.0"],
                },
            path.properties)
        pool.updateProperties(
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
