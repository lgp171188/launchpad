# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test the Person/OCIProject non-database class."""

from zope.component import getUtility

from lp.registry.interfaces.personociproject import IPersonOCIProjectFactory
from lp.services.webapp.publisher import canonical_url
from lp.testing import TestCaseWithFactory
from lp.testing.layers import DatabaseFunctionalLayer


class TestPersonOCIProject(TestCaseWithFactory):
    """Tests for `IPersonOCIProject`s."""

    layer = DatabaseFunctionalLayer

    def _makePersonOCIProject(self):
        person = self.factory.makePerson()
        oci_project = self.factory.makeOCIProject()
        return getUtility(IPersonOCIProjectFactory).create(person, oci_project)

    def test_canonical_url(self):
        # The canonical_url of a person OCIProject is
        # ~person/pillar/+oci/ociprojectname.
        pocip = self._makePersonOCIProject()
        expected = "http://launchpad.test/~%s/%s/+oci/%s" % (
            pocip.person.name,
            pocip.oci_project.pillar.name,
            pocip.oci_project.name,
        )
        self.assertEqual(expected, canonical_url(pocip))
