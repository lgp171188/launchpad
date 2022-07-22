#! /usr/bin/python3
#
# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test the validate-translations-file script."""

import logging
import os.path
from textwrap import dedent
from unittest import TestCase

import lp.translations
from lp.testing.script import run_script
from lp.translations.scripts.validate_translations_file import (
    UnknownFileType,
    ValidateTranslationsFile,
)


class TestValidateTranslationsFile(TestCase):
    def _makeValidator(self):
        """Produce a ValidateTranslationsFile."""
        validator = ValidateTranslationsFile(test_args=[])
        validator.logger.setLevel(logging.CRITICAL)
        return validator

    def _strip(self, file_contents):
        """Remove leading newlines & indentation from file_contents."""
        return dedent(file_contents.strip())

    def _findTestData(self):
        """Return base path to this test's test data."""
        return os.path.join(
            os.path.dirname(lp.translations.__file__),
            "scripts/tests/test-data",
        )

    def test_validate_unknown(self):
        # Unknown filename extensions result in UnknownFileType.
        validator = self._makeValidator()
        self.assertRaises(
            UnknownFileType, validator._validateContent, "foo.bar", b"content"
        )

    def test_validate_po_good(self):
        validator = self._makeValidator()
        result = validator._validateContent(
            "nl.po",
            self._strip(
                r"""
            msgid ""
            msgstr ""
            "MIME-Version: 1.0\n"
            "Content-Type: text/plan; charset=UTF-8\n"
            "Content-Transfer-Encoding: 8bit\n"

            msgid "foo"
            msgstr "bar"
            """
            ).encode("UTF-8"),
        )
        self.assertTrue(result)

    def test_validate_po_bad(self):
        validator = self._makeValidator()
        result = validator._validateContent(
            "nl.po",
            self._strip(
                """
            msgid "no header here"
            msgstr "hier geen kopje"
            """
            ).encode("UTF-8"),
        )
        self.assertFalse(result)

    def test_validate_pot_good(self):
        validator = self._makeValidator()
        result = validator._validateContent(
            "test.pot",
            self._strip(
                r"""
            msgid ""
            msgstr ""
            "MIME-Version: 1.0\n"
            "Content-Type: text/plan; charset=UTF-8\n"
            "Content-Transfer-Encoding: 8bit\n"

            msgid "foo"
            msgstr ""
            """
            ).encode("UTF-8"),
        )
        self.assertTrue(result)

    def test_validate_pot_bad(self):
        validator = self._makeValidator()
        result = validator._validateContent("test.pot", b"garble")
        self.assertFalse(result)

    def test_script(self):
        test_input = os.path.join(self._findTestData(), "minimal.pot")
        script = "scripts/rosetta/validate-translations-file.py"
        result, out, err = run_script(script, [test_input])
        self.assertEqual(0, result)
