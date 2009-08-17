# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

from unittest import TestLoader

from zope.security.proxy import removeSecurityProxy

from lp.testing import TestCaseWithFactory
from canonical.testing import LaunchpadZopelessLayer

from canonical.launchpad.webapp import canonical_url
from canonical.launchpad.webapp.servers import LaunchpadTestRequest
from lp.services.worlddata.model.language import LanguageSet
from lp.translations.browser.person import PersonTranslationView
from lp.translations.model.productserieslanguage import ProductSeriesLanguage
from lp.translations.model.translator import TranslatorSet


class TestPersonTranslationView(TestCaseWithFactory):
    """Test `PersonTranslationView`."""

    layer = LaunchpadZopelessLayer

    def setUp(self):
        super(TestPersonTranslationView, self).setUp()
        person = removeSecurityProxy(self.factory.makePerson())
        self.view = PersonTranslationView(person, LaunchpadTestRequest())

    def _makeReviewer(self):
        """Set up the person we're looking at as a reviewer."""
        owner = self.factory.makePerson()
        self.translationgroup = self.factory.makeTranslationGroup(owner=owner)
        dutch = LanguageSet().getLanguageByCode('nl')
        TranslatorSet().new(
            translationgroup=self.translationgroup, language=dutch,
            translator=self.view.context)

    def test_translation_groups(self):
        # translation_groups lists the translation groups a person is
        # in.
        self._makeReviewer()
        self.assertEqual(
            [self.translationgroup], self.view.translation_groups)

    def test_person_is_reviewer_false(self):
        # A regular person is not a reviewer.
        self.assertFalse(self.view.person_is_reviewer)

    def test_person_is_reviewer_true(self):
        # A person who's in a translation group is a reviewer.
        self._makeReviewer()
        self.assertTrue(self.view.person_is_reviewer)

    def test_findBestCommonReviewLinks_single_pofile(self):
        # If passed a single POFile, _findBestCommonReviewLinks returns
        # a list of just that POFile.
        pofile = self.factory.makePOFile(language_code='lua')
        links = self.view._findBestCommonReviewLinks([pofile])
        self.assertEqual(self.view._composeReviewLinks([pofile]), links)

    def test_findBestCommonReviewLinks_product_wild_mix(self):
        # A combination of wildly different POFiles in the same product
        # yields links to the individual POFiles.
        pofile1 = self.factory.makePOFile(language_code='sux')
        product = pofile1.potemplate.productseries.product
        series2 = self.factory.makeProductSeries(product)
        template2 = self.factory.makePOTemplate(productseries=series2)
        pofile2 = self.factory.makePOFile(
            potemplate=template2, language_code='la')

        links = self.view._findBestCommonReviewLinks([pofile1, pofile2])

        expected_links = self.view._composeReviewLinks([pofile1, pofile2])
        self.assertEqual(expected_links, links)

    def test_findBestCommonReviewLinks_different_templates(self):
        # A combination of POFiles in the same language but different
        # templates of the same productseries is represented as a link
        # to the ProductSeriesLanguage.
        pofile1 = self.factory.makePOFile(language_code='nl')
        series = pofile1.potemplate.productseries
        template2 = self.factory.makePOTemplate(productseries=series)
        pofile2 = self.factory.makePOFile(
            potemplate=template2, language_code='nl')

        links = self.view._findBestCommonReviewLinks([pofile1, pofile2])

        productserieslanguage = ProductSeriesLanguage(
            series, pofile1.language)
        self.assertEqual([canonical_url(productserieslanguage)], links)

    def test_findBestCommonReviewLinks_different_languages(self):
        # If the POFiles differ only in language, we get a link to the
        # overview for the template.
        pofile1 = self.factory.makePOFile(language_code='nl')
        template = pofile1.potemplate
        pofile2 = self.factory.makePOFile(
            potemplate=template, language_code='lo')

        links = self.view._findBestCommonReviewLinks([pofile1, pofile2])

        self.assertEqual([canonical_url(template)], links)

    def test_findBestCommonReviewLinks_sharing_pofiles(self):
        # In a Product, two POFiles may share their translations.  For
        # now, we link to each individually.  We may want to make this
        # more clever in the future.
        pofile1 = self.factory.makePOFile(language_code='nl')
        template1 = pofile1.potemplate
        series1 = template1.productseries
        series2 = self.factory.makeProductSeries(product=series1.product)
        template2 = self.factory.makePOTemplate(
            productseries=series2, name=template1.name,
            translation_domain=template1.translation_domain)
        pofile2 = template2.getPOFileByLang('nl')

        pofiles = [pofile1, pofile2]
        links = self.view._findBestCommonReviewLinks(pofiles)

        self.assertEqual(self.view._composeReviewLinks(pofiles), links)

    def test_findBestCommonReviewLinks_package_different_languages(self):
        # For package POFiles in the same template but different
        # languages, we link to the template.
        package = self.factory.makeSourcePackage()
        package.distroseries.distribution.official_rosetta = True
        template = self.factory.makePOTemplate(
            distroseries=package.distroseries,
            sourcepackagename=package.sourcepackagename)
        pofile1 = self.factory.makePOFile(
            potemplate=template, language_code='nl')
        pofile2 = self.factory.makePOFile(
            potemplate=template, language_code='ka')

        links = self.view._findBestCommonReviewLinks([pofile1, pofile2])
        self.assertEqual([canonical_url(template)], links)

    def test_findBestCommonReviewLinks_package_different_templates(self):
        # For package POFiles in different templates, we to the
        # package's template list.  There is no "source package series
        # language" page.
        package = self.factory.makeSourcePackage()
        package.distroseries.distribution.official_rosetta = True
        template1 = self.factory.makePOTemplate(
            distroseries=package.distroseries,
            sourcepackagename=package.sourcepackagename)
        template2 = self.factory.makePOTemplate(
            distroseries=package.distroseries,
            sourcepackagename=package.sourcepackagename)
        pofile1 = self.factory.makePOFile(
            potemplate=template1, language_code='nl')
        pofile2 = self.factory.makePOFile(
            potemplate=template2, language_code='nl')

        links = self.view._findBestCommonReviewLinks([pofile1, pofile2])

        self.assertEqual([canonical_url(package)], links)


def test_suite():
    return TestLoader().loadTestsFromName(__name__)
