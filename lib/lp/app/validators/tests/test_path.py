# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for path validators."""

from lp.app.validators import LaunchpadValidationError
from lp.app.validators.path import path_does_not_escape
from lp.testing import TestCase


class TestPathDoesNotEscape(TestCase):

    def test_valid_path(self):
        self.assertTrue(path_does_not_escape('Buildfile'))

    def test_invalid_path_parent(self):
        self.assertRaises(
            LaunchpadValidationError,
            path_does_not_escape,
            '../Buildfile')

    def test_invalid_path_elsewhere(self):
        self.assertRaises(
            LaunchpadValidationError,
            path_does_not_escape,
            '/var/foo/Buildfile')

    def test_starts_with_target(self):
        self.assertRaises(
            LaunchpadValidationError,
            path_does_not_escape,
            '/target/../../../Buildfile')

    def test_extra_dot_slash(self):
        self.assertRaises(
            LaunchpadValidationError,
            path_does_not_escape,
            '/foo/./../../bar/./Buildfile')

    def test_starts_with_target_inclusive(self):
        self.assertRaises(
            LaunchpadValidationError,
            path_does_not_escape,
            '/targetfoo/../../../Buildfile')

    def test_just_target(self):
        self.assertTrue(path_does_not_escape('/target'))
