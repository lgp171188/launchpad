from unittest import TestCase

from lp.app.validators import LaunchpadValidationError
from lp.app.validators.path import path_within_repo


class TestPaths(TestCase):

    def test_valid_path(self):
        self.assertTrue(path_within_repo('Buildfile'))

    def test_invalid_path_parent(self):
        self.assertRaises(
            LaunchpadValidationError,
            path_within_repo,
            '../Buildfile')

    def test_invalid_path_elsewhere(self):
        self.assertRaises(
            LaunchpadValidationError,
            path_within_repo,
            '/var/foo/Buildfile')
