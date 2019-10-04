import unittest

from lp.registry.model.ocirecipename import OCIRecipeName
from lp.testing.layers import DatabaseFunctionalLayer


class OCIRecipeNameTest(unittest.TestCase):

    layer = DatabaseFunctionalLayer

    def test_create(self):
        ocirecipename = OCIRecipeName(name=u'test')
        self.assertTrue(ocirecipename)
