# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for RDF main views."""

from zope.component import getUtility

from lp.services.webapp.interfaces import ILaunchpadApplication, ILaunchpadRoot
from lp.testing import TestCaseWithFactory
from lp.testing.layers import DatabaseFunctionalLayer
from lp.testing.views import create_view


class TestRootRDF(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_root_rdf(self):
        root = getUtility(ILaunchpadRoot)
        view = create_view(root, name="rdf")
        self.assertEqual("Launchpad RDF", view.page_title)

    def test_launchpad_owl(self):
        app = getUtility(ILaunchpadApplication)
        view = create_view(app, name="rdf-spec")
        owl = view.publishTraverse(view.request, "launchpad.owl")
        entity = b'ENTITY launchpad "https://launchpad.net/rdf-spec/launchpad#'
        self.assertIn(entity, owl())
        self.assertEqual(
            "application/rdf+xml",
            owl.request.response.getHeader("content-type"),
        )
