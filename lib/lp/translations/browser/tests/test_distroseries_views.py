# Copyright 2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the translations views on a distroseries."""

from urllib.parse import urlsplit

from testtools.matchers import (
    EndsWith,
    MatchesAll,
    MatchesListwise,
    StartsWith,
)
from zope.component import getUtility

from lp.services.beautifulsoup import BeautifulSoup
from lp.services.config import config
from lp.services.webapp import canonical_url
from lp.testing import TestCaseWithFactory, person_logged_in
from lp.testing.layers import LaunchpadFunctionalLayer
from lp.testing.pages import extract_link_from_tag
from lp.testing.views import create_initialized_view
from lp.translations.enums import LanguagePackType
from lp.translations.interfaces.languagepack import ILanguagePackSet


def get_librarian_download_links_on_page(page_content):
    librarian_download_links = []
    librarian_base_domain = urlsplit(config.librarian.download_url).netloc

    soup = BeautifulSoup(page_content)
    for anchor_tag in soup.find_all("a"):
        href = extract_link_from_tag(anchor_tag)
        if urlsplit(href).netloc == librarian_base_domain:
            librarian_download_links.append(href)

    return librarian_download_links


class TestLanguagePacksView(TestCaseWithFactory):
    """Test language packs view."""

    layer = LaunchpadFunctionalLayer

    def set_up_language_packs_for_distroseries(self, distroseries):
        language_pack_set = getUtility(ILanguagePackSet)
        language_pack_set.addLanguagePack(
            distroseries,
            self.factory.makeLibraryFileAlias(
                filename="test-translations-unused.tar.gz"
            ),
            LanguagePackType.FULL,
        )
        with person_logged_in(distroseries.owner):
            distroseries.language_pack_base = (
                language_pack_set.addLanguagePack(
                    distroseries,
                    self.factory.makeLibraryFileAlias(
                        filename="test-translations.tar.gz"
                    ),
                    LanguagePackType.FULL,
                )
            )
            delta_pack = language_pack_set.addLanguagePack(
                distroseries,
                self.factory.makeLibraryFileAlias(
                    filename="test-translations-update.tar.gz"
                ),
                LanguagePackType.DELTA,
            )
            distroseries.language_pack_delta = delta_pack
            distroseries.language_pack_proposed = delta_pack

    def test_unused_language_packs_many_language_packs(self):
        distroseries = self.factory.makeUbuntuDistroSeries()
        # This is one more than the default for shortlist.
        number_of_language_packs = 16
        for _ in range(number_of_language_packs):
            self.factory.makeLanguagePack(distroseries)

        view = create_initialized_view(
            distroseries, "+language-packs", rootsite="translations"
        )
        # This should not trigger a shortlist warning.
        self.assertEqual(
            number_of_language_packs, len(view.unused_language_packs)
        )

    def test_unused_language_packs_identical_base_proposed_pack(self):
        distroseries = self.factory.makeUbuntuDistroSeries()
        pack = self.factory.makeLanguagePack(distroseries)
        with person_logged_in(distroseries.distribution.owner):
            distroseries.language_pack_base = pack
            distroseries.language_pack_proposed = pack

        view = create_initialized_view(
            distroseries, "+language-packs", rootsite="translations"
        )
        self.assertEqual(0, len(view.unused_language_packs))

    def test_unused_language_packs_identical_delta_proposed_pack(self):
        distroseries = self.factory.makeUbuntuDistroSeries()
        with person_logged_in(distroseries.distribution.owner):
            distroseries.language_pack_base = self.factory.makeLanguagePack(
                distroseries
            )
            delta_pack = self.factory.makeLanguagePack(
                distroseries, LanguagePackType.DELTA
            )
            distroseries.language_pack_delta = delta_pack
            distroseries.language_pack_proposed = delta_pack

        view = create_initialized_view(
            distroseries, "+language-packs", rootsite="translations"
        )
        self.assertEqual(0, len(view.unused_language_packs))

    def test_languagepack_urls_use_http_when_librarian_uses_http(self):
        distroseries = self.factory.makeUbuntuDistroSeries()
        self.set_up_language_packs_for_distroseries(distroseries)

        url = canonical_url(
            distroseries, view_name="+language-packs", rootsite="translations"
        )
        browser = self.getUserBrowser(user=self.factory.makePerson())
        browser.open(url)

        download_urls = get_librarian_download_links_on_page(browser.contents)
        expected_scheme = "http://"

        # In the test environment, librarian defaults to http.
        # There is a link each for the unused, base, delta,
        # and proposed language packs in this page.
        self.assertThat(
            download_urls,
            MatchesListwise(
                [
                    MatchesAll(
                        StartsWith(expected_scheme),
                        EndsWith("test-translations.tar.gz"),
                    ),
                    MatchesAll(
                        StartsWith(expected_scheme),
                        EndsWith("test-translations-update.tar.gz"),
                    ),
                    MatchesAll(
                        StartsWith(expected_scheme),
                        EndsWith("test-translations-update.tar.gz"),
                    ),
                    MatchesAll(
                        StartsWith(expected_scheme),
                        EndsWith("test-translations-unused.tar.gz"),
                    ),
                ]
            ),
        )

    def test_languagepack_urls_use_https_when_librarian_uses_https(self):
        self.pushConfig("librarian", use_https=True)

        distroseries = self.factory.makeUbuntuDistroSeries()
        self.set_up_language_packs_for_distroseries(distroseries)

        url = canonical_url(
            distroseries, view_name="+language-packs", rootsite="translations"
        )

        browser = self.getUserBrowser(user=self.factory.makePerson())
        browser.open(url)

        download_urls = get_librarian_download_links_on_page(browser.contents)

        expected_scheme = "https://"

        # There is a link each for the unused, base, delta,
        # and proposed language packs.
        self.assertThat(
            download_urls,
            MatchesListwise(
                [
                    MatchesAll(
                        StartsWith(expected_scheme),
                        EndsWith("test-translations.tar.gz"),
                    ),
                    MatchesAll(
                        StartsWith(expected_scheme),
                        EndsWith("test-translations-update.tar.gz"),
                    ),
                    MatchesAll(
                        StartsWith(expected_scheme),
                        EndsWith("test-translations-update.tar.gz"),
                    ),
                    MatchesAll(
                        StartsWith(expected_scheme),
                        EndsWith("test-translations-unused.tar.gz"),
                    ),
                ]
            ),
        )


class TestDistroseriesTranslationsView(TestCaseWithFactory):
    """Test the distroseries translations view."""

    layer = LaunchpadFunctionalLayer

    def set_up_language_packs_for_distroseries(self, distroseries):
        language_pack_set = getUtility(ILanguagePackSet)
        with person_logged_in(distroseries.owner):
            distroseries.language_pack_base = (
                language_pack_set.addLanguagePack(
                    distroseries,
                    self.factory.makeLibraryFileAlias(
                        filename="test-translations.tar.gz"
                    ),
                    LanguagePackType.FULL,
                )
            )
            delta_pack = language_pack_set.addLanguagePack(
                distroseries,
                self.factory.makeLibraryFileAlias(
                    filename="test-translations-update.tar.gz"
                ),
                LanguagePackType.DELTA,
            )
            distroseries.language_pack_delta = delta_pack

    def test_languagepack_urls_use_http_when_librarian_uses_http(self):
        distroseries = self.factory.makeUbuntuDistroSeries()
        self.set_up_language_packs_for_distroseries(distroseries)

        url = canonical_url(
            distroseries, view_name="+translations", rootsite="translations"
        )
        browser = self.getUserBrowser(user=self.factory.makePerson())
        browser.open(url)

        download_urls = get_librarian_download_links_on_page(browser.contents)
        expected_scheme = "http://"

        # In the test environment, librarian defaults to http.
        # There is a link each for the base and delta language packs
        # in this page.
        self.assertThat(
            download_urls,
            MatchesListwise(
                [
                    MatchesAll(
                        StartsWith(expected_scheme),
                        EndsWith("test-translations.tar.gz"),
                    ),
                    MatchesAll(
                        StartsWith(expected_scheme),
                        EndsWith("test-translations-update.tar.gz"),
                    ),
                ]
            ),
        )

    def test_languagepack_urls_use_https_when_librarian_uses_https(self):
        self.pushConfig("librarian", use_https=True)

        distroseries = self.factory.makeUbuntuDistroSeries()
        self.set_up_language_packs_for_distroseries(distroseries)

        url = canonical_url(
            distroseries, view_name="+translations", rootsite="translations"
        )

        browser = self.getUserBrowser(user=self.factory.makePerson())
        browser.open(url)

        download_urls = get_librarian_download_links_on_page(browser.contents)

        expected_scheme = "https://"

        # There is a link each for the unused, base, delta,
        # and proposed language packs.
        self.assertThat(
            download_urls,
            MatchesListwise(
                [
                    MatchesAll(
                        StartsWith(expected_scheme),
                        EndsWith("test-translations.tar.gz"),
                    ),
                    MatchesAll(
                        StartsWith(expected_scheme),
                        EndsWith("test-translations-update.tar.gz"),
                    ),
                ]
            ),
        )
