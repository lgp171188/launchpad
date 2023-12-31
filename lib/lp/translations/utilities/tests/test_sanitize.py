# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from lp.testing import TestCase
from lp.translations.utilities.sanitize import (
    MixedNewlineMarkersError,
    Sanitizer,
    sanitize_translations_from_webui,
)


class TestSanitizer(TestCase):
    """Test the Sanitizer class used by sanitize_translations."""

    def test_convertDotToSpace(self):
        # Dots are converted back to spaces.
        sanitizer = Sanitizer("English with space.")
        translation = "Text\u2022with\u2022dots."
        expected_sanitized = "Text with dots."

        self.assertEqual(
            expected_sanitized, sanitizer.convertDotToSpace(translation)
        )

    def test_convertDotToSpace_dot_in_english(self):
        # If there are dots in the English string, no conversion happens.
        sanitizer = Sanitizer("English\u2022with\u2022dots.")
        translation = "Text\u2022with\u2022dots."
        expected_sanitized = "Text\u2022with\u2022dots."

        self.assertEqual(
            expected_sanitized, sanitizer.convertDotToSpace(translation)
        )

    def test_normalizeWhitespace_add(self):
        # Leading and trailing white space in the translation are synced to
        # what the English text has.
        sanitizer = Sanitizer("  English with leading white space.  ")
        translation = "Text without white space."
        expected_sanitized = "  Text without white space.  "

        self.assertEqual(
            expected_sanitized, sanitizer.normalizeWhitespace(translation)
        )

    def test_normalizeWhitespace_remove(self):
        # Leading and trailing white space in the translation are synced to
        # what the English text has.
        sanitizer = Sanitizer("English without leading white space.")
        translation = "  Text with white space.  "
        expected_sanitized = "Text with white space."

        self.assertEqual(
            expected_sanitized, sanitizer.normalizeWhitespace(translation)
        )

    def test_normalizeWhitespace_add_and_remove(self):
        # Leading and trailing white space in the translation are synced to
        # what the English text has.
        sanitizer = Sanitizer("  English with leading white space.")
        translation = "Text with trailing white space.  "
        expected_sanitized = "  Text with trailing white space."

        self.assertEqual(
            expected_sanitized, sanitizer.normalizeWhitespace(translation)
        )

    def test_normalizeWhitespace_only_whitespace(self):
        # If a translation is only whitespace, it will be turned into the
        # empty string.
        sanitizer = Sanitizer("English")
        only_whitespace = "    "

        self.assertEqual("", sanitizer.normalizeWhitespace(only_whitespace))

    def test_normalizeWhitespace_only_whitespace_everywhere(self):
        # Corner case: only whitespace in English and translation will
        # normalize to the English string.
        english_whitespace = "  "
        sanitizer = Sanitizer(english_whitespace)
        only_whitespace = "    "

        self.assertEqual(
            english_whitespace, sanitizer.normalizeWhitespace(only_whitespace)
        )

    newline_styles = ["\r\n", "\r", "\n"]

    def test_normalizeNewlines(self):
        # Newlines will be converted to the same style that the English has.
        english_template = "Text with%snewline."
        translation_template = "Translation with%snewline."
        for english_newline in self.newline_styles:
            english_text = english_template % english_newline
            sanitizer = Sanitizer(english_text)
            expected_sanitized = translation_template % english_newline
            for translation_newline in self.newline_styles:
                translation_text = translation_template % translation_newline
                sanitized = sanitizer.normalizeNewlines(translation_text)
                self.assertEqual(
                    expected_sanitized,
                    sanitized,
                    "With %r and %r:\n%r != %r"
                    % (
                        english_newline,
                        translation_newline,
                        expected_sanitized,
                        sanitized,
                    ),
                )

    def test_normalizeNewlines_nothing_to_do_english(self):
        # If no newlines are found in the english text, no normalization
        # takes place.
        sanitizer = Sanitizer("Text without newline.")
        translation_template = "Translation with%snewline."
        for translation_newline in self.newline_styles:
            translation_text = translation_template % translation_newline
            sanitized = sanitizer.normalizeNewlines(translation_text)
            self.assertEqual(
                translation_text,
                sanitized,
                "With %r: %r != %r"
                % (translation_newline, translation_text, sanitized),
            )

    def test_normalizeNewlines_nothing_to_do_translation(self):
        # If no newlines are found in the translation text, no normalization
        # takes place.
        english_template = "Text with%snewline."
        translation_text = "Translation without newline."
        for english_newline in self.newline_styles:
            english_text = english_template % english_newline
            sanitizer = Sanitizer(english_text)
            sanitized = sanitizer.normalizeNewlines(translation_text)
            self.assertEqual(
                translation_text,
                sanitized,
                "With %r: %r != %r"
                % (english_newline, translation_text, sanitized),
            )

    def test_normalizeNewlines_mixed_newlines_english(self):
        # Mixed newlines in the English text will not raise an exception.
        english_template = "Text with%smixed%snewlines."
        for english_newline_1 in self.newline_styles:
            other_newlines = self.newline_styles[:]
            other_newlines.remove(english_newline_1)
            for english_newline_2 in other_newlines:
                english_text = english_template % (
                    english_newline_1,
                    english_newline_2,
                )
                Sanitizer(english_text)

    def test_normalizeNewlines_mixed_newlines_translation(self):
        # Mixed newlines in the translation text will raise an exception.
        sanitizer = Sanitizer("Text with\nnewline.")
        translation_template = "Translation with%smixed%snewlines."
        for translation_newline_1 in self.newline_styles:
            other_newlines = self.newline_styles[:]
            other_newlines.remove(translation_newline_1)
            for translation_newline_2 in other_newlines:
                translation_text = translation_template % (
                    translation_newline_1,
                    translation_newline_2,
                )
                self.assertRaises(
                    MixedNewlineMarkersError,
                    sanitizer.normalizeNewlines,
                    translation_text,
                )

    def test_sanitize(self):
        # Calling the Sanitizer object will apply all sanitization procedures.
        sanitizer = Sanitizer("Text with\nnewline.")
        translation_text = (
            "Translation with\r\nnewline dots\u2022and whitespace.  "
        )
        expected_sanitized = "Translation with\nnewline dots and whitespace."
        self.assertEqual(
            expected_sanitized, sanitizer.sanitize(translation_text)
        )

    def test_sanitize_whitespace_string(self):
        # A whitespace only string will be normalized to None.
        sanitizer = Sanitizer("Text without whitespace.")
        empty_translation_text = "  "
        self.assertTrue(sanitizer.sanitize(empty_translation_text) is None)

    def test_sanitizer_None(self):
        # None is returned as None.
        sanitizer = Sanitizer("Text without whitespace.")
        self.assertIs(sanitizer.sanitize(None), None)


class TestSanitizeTranslations(TestCase):
    """Test sanitize_translations_from_webui function.

    This test case is just about how the functions handles different plural
    form situations.  The actual sanitization is tested in TestSanitizer.
    """

    english = "Some English text\nwith unix newline."

    def test_sanitize_translations(self):
        # All plural forms are sanitized.
        translations = {
            0: "Plural\r\nform 0  ",
            1: "Plural\r\nform 1  ",
            2: "Plural\r\nform 2  ",
        }
        expected_sanitized = {
            0: "Plural\nform 0",
            1: "Plural\nform 1",
            2: "Plural\nform 2",
        }
        self.assertEqual(
            expected_sanitized,
            sanitize_translations_from_webui(self.english, translations, 3),
        )

    def test_sanitize_translations_not_in_dict(self):
        # A list is converted to a dictionary.
        translations = [
            "Pluralform 0",
            "Pluralform 1",
            "Pluralform 2",
        ]
        expected_sanitized = {
            0: "Pluralform 0",
            1: "Pluralform 1",
            2: "Pluralform 2",
        }
        self.assertEqual(
            expected_sanitized,
            sanitize_translations_from_webui(self.english, translations, 3),
        )

    def test_sanitize_translations_missing_pluralform(self):
        # Missing plural forms are normalized to None.
        translations = {
            0: "Plural\r\nform 0  ",
            2: "Plural\r\nform 2  ",
        }
        expected_sanitized = {
            0: "Plural\nform 0",
            1: None,
            2: "Plural\nform 2",
        }
        self.assertEqual(
            expected_sanitized,
            sanitize_translations_from_webui(self.english, translations, 3),
        )

    def test_sanitize_translations_excess_pluralform(self):
        # Excess plural forms are sanitized, too.
        translations = {
            0: "Plural\r\nform 0  ",
            1: "Plural\r\nform 1  ",
            2: "Plural\r\nform 2  ",
            4: "Plural\r\nform 4  ",
        }
        expected_sanitized = {
            0: "Plural\nform 0",
            1: "Plural\nform 1",
            2: "Plural\nform 2",
            4: "Plural\nform 4",
        }
        self.assertEqual(
            expected_sanitized,
            sanitize_translations_from_webui(self.english, translations, 3),
        )

    def test_sanitize_translations_pluralforms_none(self):
        # Some languages don't provide a plural form, so 2 is assumed.
        translations = {
            0: "Plural form 0  ",
        }
        expected_sanitized = {
            0: "Plural form 0",
            1: None,
        }
        self.assertEqual(
            expected_sanitized,
            sanitize_translations_from_webui(self.english, translations, None),
        )
