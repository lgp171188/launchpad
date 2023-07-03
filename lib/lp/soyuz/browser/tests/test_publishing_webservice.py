# Copyright 2011-2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test webservice methods related to the publisher."""

from functools import partial

from testtools.matchers import ContainsDict, Equals, Is
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.registry.interfaces.sourcepackage import SourcePackageType
from lp.services.librarian.browser import ProxiedLibraryFileAlias
from lp.services.webapp.interfaces import OAuthPermission
from lp.soyuz.adapters.proxiedsourcefiles import ProxiedSourceLibraryFileAlias
from lp.soyuz.enums import BinaryPackageFormat
from lp.soyuz.interfaces.publishing import IPublishingSet
from lp.testing import (
    TestCaseWithFactory,
    api_url,
    login_person,
    person_logged_in,
    record_two_runs,
)
from lp.testing.layers import LaunchpadFunctionalLayer
from lp.testing.matchers import HasQueryCount
from lp.testing.pages import webservice_for_person


class SourcePackagePublishingHistoryWebserviceTests(TestCaseWithFactory):
    layer = LaunchpadFunctionalLayer

    def make_spph_for(self, person):
        with person_logged_in(person):
            spr = self.factory.makeSourcePackageRelease()
            self.factory.makeSourcePackageReleaseFile(sourcepackagerelease=spr)
            spph = self.factory.makeSourcePackagePublishingHistory(
                sourcepackagerelease=spr
            )
            return spph, api_url(spph)

    def test_sourceFileUrls(self):
        person = self.factory.makePerson()
        webservice = webservice_for_person(
            person, permission=OAuthPermission.READ_PUBLIC
        )
        spph, url = self.make_spph_for(person)

        response = webservice.named_get(
            url, "sourceFileUrls", api_version="devel"
        )

        self.assertEqual(200, response.status)
        urls = response.jsonBody()
        with person_logged_in(person):
            sprf = spph.sourcepackagerelease.files[0]
            expected_urls = [
                ProxiedSourceLibraryFileAlias(sprf.libraryfile, spph).http_url
            ]
        self.assertEqual(expected_urls, urls)

    def test_sourceFileUrls_include_meta(self):
        person = self.factory.makePerson()
        webservice = webservice_for_person(
            person, permission=OAuthPermission.READ_PUBLIC
        )
        spph, url = self.make_spph_for(person)

        def create_file():
            self.factory.makeSourcePackageReleaseFile(
                sourcepackagerelease=spph.sourcepackagerelease
            )

        def get_urls():
            return webservice.named_get(
                url, "sourceFileUrls", include_meta=True, api_version="devel"
            )

        recorder1, recorder2 = record_two_runs(
            get_urls,
            create_file,
            2,
            login_method=partial(login_person, person),
            record_request=True,
        )
        self.assertThat(recorder2, HasQueryCount.byEquality(recorder1))

        response = get_urls()
        self.assertEqual(200, response.status)
        info = response.jsonBody()
        with person_logged_in(person):
            expected_info = [
                {
                    "url": ProxiedSourceLibraryFileAlias(
                        sprf.libraryfile, spph
                    ).http_url,
                    "size": sprf.libraryfile.content.filesize,
                    "sha256": sprf.libraryfile.content.sha256,
                }
                for sprf in spph.sourcepackagerelease.files
            ]
        self.assertContentEqual(expected_info, info)

    def test_hasRestrictedFiles(self):
        person = self.factory.makePerson()
        webservice = webservice_for_person(
            person, permission=OAuthPermission.READ_PUBLIC
        )
        spph, url = self.make_spph_for(person)

        response = webservice.named_get(
            url, "hasRestrictedFiles", api_version="devel"
        )
        self.assertEqual(200, response.status)
        self.assertFalse(response.jsonBody())

        with person_logged_in(person):
            sprf = spph.sourcepackagerelease.files[0]
            removeSecurityProxy(sprf.libraryfile).restricted = True

        response = webservice.named_get(
            url, "hasRestrictedFiles", api_version="devel"
        )
        self.assertEqual(200, response.status)
        self.assertTrue(response.jsonBody())

    def test_ci_build(self):
        person = self.factory.makePerson()
        webservice = webservice_for_person(
            person, permission=OAuthPermission.READ_PUBLIC
        )
        with person_logged_in(person):
            distroseries = self.factory.makeDistroSeries()
            archive = self.factory.makeArchive(
                distribution=distroseries.distribution
            )
            build = self.factory.makeCIBuild()
            owner = build.git_repository.owner
            spn = self.factory.makeSourcePackageName()
            spr = build.createSourcePackageRelease(
                distroseries, spn, "1.0", creator=owner, archive=archive
            )
            spph = self.factory.makeSourcePackagePublishingHistory(
                sourcepackagerelease=spr,
                format=SourcePackageType.CI_BUILD,
            )
            url = api_url(spph)

        response = webservice.get(url, api_version="devel")

        self.assertEqual(200, response.status)
        with person_logged_in(person):
            self.assertThat(
                response.jsonBody(),
                ContainsDict(
                    {
                        "component_name": Is(None),
                        "section_name": Is(None),
                        "source_package_name": Equals(spn.name),
                        "source_package_version": Equals(spr.version),
                    }
                ),
            )


class BinaryPackagePublishingHistoryWebserviceTests(TestCaseWithFactory):
    layer = LaunchpadFunctionalLayer

    def make_bpph_for(self, person):
        with person_logged_in(person):
            bpr = self.factory.makeBinaryPackageRelease()
            self.factory.makeBinaryPackageFile(binarypackagerelease=bpr)
            bpph = self.factory.makeBinaryPackagePublishingHistory(
                binarypackagerelease=bpr
            )
            return bpph, api_url(bpph)

    def test_binaryFileUrls(self):
        person = self.factory.makePerson()
        webservice = webservice_for_person(
            person, permission=OAuthPermission.READ_PUBLIC
        )
        bpph, url = self.make_bpph_for(person)

        response = webservice.named_get(
            url, "binaryFileUrls", api_version="devel"
        )

        self.assertEqual(200, response.status)
        urls = response.jsonBody()
        with person_logged_in(person):
            bpf = bpph.binarypackagerelease.files[0]
            expected_urls = [
                ProxiedLibraryFileAlias(bpf.libraryfile, bpph.archive).http_url
            ]
        self.assertEqual(expected_urls, urls)

    def test_binaryFileUrls_include_meta(self):
        person = self.factory.makePerson()
        webservice = webservice_for_person(
            person, permission=OAuthPermission.READ_PUBLIC
        )
        bpph, url = self.make_bpph_for(person)

        def create_file():
            self.factory.makeBinaryPackageFile(
                binarypackagerelease=bpph.binarypackagerelease
            )

        def get_urls():
            return webservice.named_get(
                url, "binaryFileUrls", include_meta=True, api_version="devel"
            )

        recorder1, recorder2 = record_two_runs(
            get_urls,
            create_file,
            2,
            login_method=partial(login_person, person),
            record_request=True,
        )
        self.assertThat(recorder2, HasQueryCount.byEquality(recorder1))

        response = get_urls()
        self.assertEqual(200, response.status)
        info = response.jsonBody()
        with person_logged_in(person):
            expected_info = [
                {
                    "url": ProxiedLibraryFileAlias(
                        bpf.libraryfile, bpph.archive
                    ).http_url,
                    "size": bpf.libraryfile.content.filesize,
                    "sha1": bpf.libraryfile.content.sha1,
                    "sha256": bpf.libraryfile.content.sha256,
                }
                for bpf in bpph.binarypackagerelease.files
            ]
        self.assertContentEqual(expected_info, info)

    def test_ci_build(self):
        person = self.factory.makePerson()
        webservice = webservice_for_person(
            person, permission=OAuthPermission.READ_PUBLIC
        )
        with person_logged_in(person):
            das = self.factory.makeDistroArchSeries()
            archive = self.factory.makeArchive(
                distribution=das.distroseries.distribution
            )
            build = self.factory.makeCIBuild()
            bpn = self.factory.makeBinaryPackageName()
            bpr = build.createBinaryPackageRelease(
                bpn,
                "1.0",
                "test summary",
                "test description",
                BinaryPackageFormat.WHL,
                False,
            )
            [bpph] = getUtility(IPublishingSet).publishBinaries(
                archive,
                das.distroseries,
                PackagePublishingPocket.RELEASE,
                {bpr: (None, None, None, None)},
            )
            url = api_url(bpph)

        response = webservice.get(url, api_version="devel")

        self.assertEqual(200, response.status)
        with person_logged_in(person):
            self.assertThat(
                response.jsonBody(),
                ContainsDict(
                    {
                        "binary_package_name": Equals(bpn.name),
                        "binary_package_version": Equals(bpr.version),
                        "component_name": Is(None),
                        "section_name": Is(None),
                    }
                ),
            )
