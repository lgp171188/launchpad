# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import re

from lp.services.webapp.publisher import canonical_url
from lp.testing import TestCaseWithFactory
from lp.testing.layers import LaunchpadFunctionalLayer
from lp.testing.pages import find_tags_by_class


class TestHasTranslationImportsView(TestCaseWithFactory):
    layer = LaunchpadFunctionalLayer

    def test_https(self):
        self.pushConfig("librarian", use_https=True)
        distroseries = self.factory.makeUbuntuDistroSeries()
        entry = self.factory.makeTranslationImportQueueEntry(
            distroseries=distroseries
        )
        queue_url = canonical_url(distroseries, view_name="+imports")
        browser = self.getUserBrowser(url=queue_url)
        import_sources = find_tags_by_class(browser.contents, "import_source")
        self.assertRegex(
            import_sources[0].a["href"],
            r"^https://.*/" + re.escape(entry.path),
        )
