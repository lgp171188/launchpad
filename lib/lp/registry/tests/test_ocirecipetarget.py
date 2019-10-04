# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).
from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type

from lp.registry.model.ocirecipename import OCIRecipeName
from lp.registry.model.ocirecipetarget import OCIRecipeTarget
from lp.testing import TestCaseWithFactory
from lp.testing.layers import DatabaseLayer


class OCIRecipeTargetTest(TestCaseWithFactory):

    layer = DatabaseLayer

    def test_create(self):
        name = OCIRecipeName(name="Test OCI Recipe Name")
        registrant = self.factory.makePerson()
        project = self.factory.makeProduct()
        distribution = self.factory.makeDistribution()
        target = OCIRecipeTarget(registrant, project, distribution, name)
        print(target.date_created)
        self.assertTrue(target)
