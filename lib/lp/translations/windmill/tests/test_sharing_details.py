# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for sharing details page."""

__metaclass__ = type


import transaction

from canonical.launchpad.webapp import canonical_url
from lp.testing import (
    feature_flags,
    set_feature_flag,
    WindmillTestCase,
)
from lp.testing.windmill import (
    lpuser,
)
from lp.testing.windmill.constants import (
    FOR_ELEMENT,
    PAGE_LOAD,
)
from lp.translations.windmill.testing import (
    TranslationsWindmillLayer,
)



class TestSharingDetails(WindmillTestCase):

    layer = TranslationsWindmillLayer

    def test_set_branch(self):
        packaging = self.factory.makePackagingLink()
        self.useContext(feature_flags())
        set_feature_flag(u'translations.sharing_information.enabled', u'on')
        transaction.commit()
        url = canonical_url(
            packaging.sourcepackage, rootsite='translations',
            view_name='+sharing-details')
        self.client.open(url=url)
        self.client.waits.forPageLoad(timeout=PAGE_LOAD)
        lpuser.TRANSLATIONS_ADMIN.ensure_login(self.client)
        self.client.waits.forElement(id='branch', timeout=FOR_ELEMENT)
        self.client.click(
            xpath='//*[@id="branch"]/*[contains(@class, "incomplete")]/*'
                '[@class="pickbranch"]/a')
        self.client.type(
            text='firefox', xpath='//input[@class="yui3-picker-search"]')
        self.client.click(xpath='//button[@class="lazr-search lazr-btn"]')
        self.client.click(xpath='//span[@class="yui3-picker-result-title"]')
        self.client.waits.forElement(
            xpath='//*[@id="branch"]/*[@class="complete sprite yes"]')
        transaction.commit()
        branch = packaging.productseries
        self.assertEqual('~name12/firefox/main', branch.unique_name)
