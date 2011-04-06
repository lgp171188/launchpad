# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for sharing details page."""


__metaclass__ = type


import transaction

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
)
from lp.testing.windmill.widgets import (
    search_and_select_picker_widget,
)
from lp.translations.windmill.testing import (
    TranslationsWindmillLayer,
)


class TestSharingDetails(WindmillTestCase):

    layer = TranslationsWindmillLayer

    def test_set_branch(self):
        packaging = self.factory.makePackagingLink()
        branch = self.factory.makeProductBranch(
            product=packaging.productseries.product, name='product-branch')
        self.useContext(feature_flags())
        set_feature_flag(u'translations.sharing_information.enabled', u'on')
        transaction.commit()

        client, start_url = self.getClientFor(
            packaging.sourcepackage, user=lpuser.TRANSLATIONS_ADMIN,
            view_name='+sharing-details')
        client.waits.forElement(
            id='branch-incomplete', timeout=FOR_ELEMENT)
        client.click(xpath='//*[@id="branch-incomplete-picker"]/a')
        search_and_select_picker_widget(client, 'product-branch', 1)
        client.waits.forElementProperty(
            id='branch-incomplete', option='className|sprite no unseen',
            timeout=FOR_ELEMENT)
        transaction.commit()
        self.assertEqual(branch, packaging.productseries.branch)
