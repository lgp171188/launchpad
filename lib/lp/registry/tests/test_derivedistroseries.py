# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test initialising a distroseries using
IDistroSeries.deriveDistroSeries."""

__metaclass__ = type

from canonical.testing.layers import LaunchpadFunctionalLayer
from lp.registry.interfaces.distroseries import DerivationError
from lp.testing import (
    login,
    logout,
    TestCaseWithFactory,
    )

class TestDeriveDistroSeries(TestCaseWithFactory):

    layer = LaunchpadFunctionalLayer

    def setUp(self):
        super(TestDeriveDistroSeries, self).setUp()
        self.owner = self.factory.makePerson()
        self.soyuz = self.factory.makeTeam(
            name='soyuz-team', owner=self.owner)
        self.parent = self.factory.makeDistroSeries()
        self.child = self.factory.makeDistroSeries(
            parent_series=self.parent)
    
    def test_no_distroseries_and_no_arguments(self):
        """Test that calling deriveDistroSeries() when the distroseries
        doesn't exist, and not enough arguments are specified that the
        function errors."""
        self.assertRaisesWithContent(
            DerivationError,
            'Display Name, Summary, Description and Version all need to '
            'be set when creating a distroseries',
            self.parent.deriveDistroSeries, self.owner, 'foobuntu')

    def test_parent_is_not_self(self):
        login('admin@canonical.com')
        other = self.factory.makeDistroSeries()
        logout()
        self.assertRaisesWithContent(
            DerivationError,
            "DistroSeries %s parent series isn't %s" % (
                self.child.name, other.name),
            other.deriveDistroSeries, self.owner, self.child.name)

    def test_create_new_distroseries(self):
        job = self.parent.deriveDistroSeries(self.owner, self.child.name)
        print job

