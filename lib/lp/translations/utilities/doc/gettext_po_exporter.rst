gettext_po_exporter
===================

To export translation files from Rosetta, the data must be displayed in po
file fomrat which is a text file format.

    >>> from lp.translations.interfaces.translations import (
    ...     TranslationConstants,
    ... )
    >>> from lp.translations.utilities.gettext_po_exporter import (
    ...     comments_text_representation,
    ...     export_translation_message,
    ... )
    >>> from lp.translations.utilities.translation_common_format import (
    ...     TranslationMessageData,
    ... )

comments_text_representation
----------------------------

Special comments are created from metadata of each translation message.
Message flags are represented by the #, comment.

    >>> translation_message = TranslationMessageData()
    >>> translation_message.msgid_singular = "foo"
    >>> translation_message.addTranslation(
    ...     TranslationConstants.SINGULAR_FORM, "bar"
    ... )
    >>> translation_message.flags = ("fuzzy",)
    >>> print(comments_text_representation(translation_message))
    #, fuzzy

Multiple flags are divided by commas.

    >>> translation_message = TranslationMessageData()
    >>> translation_message.msgid_singular = "%d foo"
    >>> translation_message.addTranslation(
    ...     TranslationConstants.SINGULAR_FORM, "%d bar"
    ... )
    >>> translation_message.flags = ("fuzzy", "c-format")
    >>> print(comments_text_representation(translation_message))
    #, fuzzy, c-format

Simple comments are preceded by a single # sign.

    >>> translation_message = TranslationMessageData()
    >>> translation_message.msgid_singular = "a"
    >>> translation_message.addTranslation(
    ...     TranslationConstants.SINGULAR_FORM, "b"
    ... )
    >>> translation_message.comment = " blah\n"
    >>> print(comments_text_representation(translation_message))
    # blah

Any other comments have been stored verbatim during import and are now
prepended with a # sign again.

    >>> translation_message = TranslationMessageData()
    >>> translation_message.msgid_singular = "foo"
    >>> translation_message.addTranslation(
    ...     TranslationConstants.SINGULAR_FORM, "bar"
    ... )
    >>> translation_message.comment = "  line1\n| msgid line2\n"
    >>> print(comments_text_representation(translation_message))
    #  line1
    #| msgid line2

The order of comments must be kept, so #| are moved to the end.

    >>> translation_message = TranslationMessageData()
    >>> translation_message.msgid_singular = "foo"
    >>> translation_message.addTranslation(
    ...     TranslationConstants.SINGULAR_FORM, "bar"
    ... )
    >>> translation_message.comment = "  line1\n| msgid line2\n"
    >>> translation_message.file_references = "src/file.c"
    >>> print(comments_text_representation(translation_message))
    #  line1
    #: src/file.c
    #| msgid line2


wrap_text
---------
We are not using textwrap module because the .po file format has some
peculiarities like:

msgid ""
"a really long line."

instead of:

msgid "a really long"
"line."

with a wrapping width of 21.

    >>> translation_message = TranslationMessageData()
    >>> translation_message.msgid_singular = "abcdefghijkl"
    >>> translation_message.addTranslation(
    ...     TranslationConstants.SINGULAR_FORM, "z"
    ... )
    >>> print(export_translation_message(translation_message, wrap_width=20))
    msgid "abcdefghijkl"
    msgstr "z"

    >>> translation_message = TranslationMessageData()
    >>> translation_message.msgid_singular = "abcdefghijklmnopqr"
    >>> translation_message.addTranslation(
    ...     TranslationConstants.SINGULAR_FORM, "z"
    ... )
    >>> print(export_translation_message(translation_message, wrap_width=20))
    msgid ""
    "abcdefghijklmnopqr"
    msgstr "z"

    >>> translation_message = TranslationMessageData()
    >>> translation_message.msgid_singular = "abcdef hijklm"
    >>> translation_message.addTranslation(
    ...     TranslationConstants.SINGULAR_FORM, "z"
    ... )
    >>> print(export_translation_message(translation_message, wrap_width=20))
    msgid ""
    "abcdef hijklm"
    msgstr "z"

    >>> translation_message = TranslationMessageData()
    >>> translation_message.msgid_singular = "abcdefghijklmnopqr st"
    >>> translation_message.addTranslation(
    ...     TranslationConstants.SINGULAR_FORM, "z"
    ... )
    >>> print(export_translation_message(translation_message, wrap_width=20))
    msgid ""
    "abcdefghijklmnopqr "
    "st"
    msgstr "z"

Newlines in the text interfere with wrapping.

    >>> translation_message = TranslationMessageData()
    >>> translation_message.msgid_singular = "abc\ndef"
    >>> translation_message.addTranslation(
    ...     TranslationConstants.SINGULAR_FORM, "z"
    ... )
    >>> print(export_translation_message(translation_message, wrap_width=20))
    msgid ""
    "abc\n"
    "def"
    msgstr "z"

But not when it's just a line that ends with a newline char

    >>> translation_message = TranslationMessageData()
    >>> translation_message.msgid_singular = "abc\n"
    >>> translation_message.addTranslation(
    ...     TranslationConstants.SINGULAR_FORM, "def\n"
    ... )
    >>> print(export_translation_message(translation_message))
    msgid "abc\n"
    msgstr "def\n"

It's time to test the wrapping with the '-' char:

    >>> translation_message = TranslationMessageData()
    >>> translation_message.msgid_singular = (
    ...     "WARNING: unsafe enclosing directory permissions on homedir"
    ...     " `%s'\n"
    ... )
    >>> translation_message.addTranslation(
    ...     TranslationConstants.SINGULAR_FORM,
    ...     "WARNUNG: Unsichere Zugriffsrechte des umgebenden Verzeichnisses"
    ...     " des Home-Verzeichnisses `%s'\n",
    ... )
    >>> print(export_translation_message(translation_message))  # noqa
    msgid "WARNING: unsafe enclosing directory permissions on homedir `%s'\n"
    msgstr ""
    "WARNUNG: Unsichere Zugriffsrechte des umgebenden Verzeichnisses des Home-"
    "Verzeichnisses `%s'\n"

When we changed the wrapping code, we got a bug with this string.

    >>> translation_message = TranslationMessageData()
    >>> translation_message.msgid_singular = (
    ...     "The location and hierarchy of the Evolution contact folders has"
    ...     " changed since Evolution 1.x.\n\n"
    ... )
    >>> print(export_translation_message(translation_message))
    msgid ""
    "The location and hierarchy of the Evolution contact folders has changed "
    "since Evolution 1.x.\n"
    "\n"
    msgstr ""

When the wrapping size was exactly gotten past by in the middle of
escape sequence like \" or \\, it got cut off in there, thus
creating a broken PO message.  This is the test for bug #46156.

    >>> translation_message = TranslationMessageData()
    >>> translation_message.msgid_singular = (
    ...     '1234567890abcde word"1234567890abcdefghij'
    ... )
    >>> print(export_translation_message(translation_message, wrap_width=20))
    msgid ""
    "1234567890abcde "
    "word\"1234567890abcd"
    "efghij"
    msgstr ""

Lets also make sure that the unconditional break is not occurring
inside a single long word in the middle of the escape sequence
like \" or \\:

    >>> translation_message = TranslationMessageData()
    >>> translation_message.msgid_singular = "1234567890abcdefghij\\klmno"
    >>> print(export_translation_message(translation_message, wrap_width=20))
    msgid ""
    "1234567890abcdefghij"
    "\\klmno"
    msgstr ""

    >>> translation_message = TranslationMessageData()
    >>> translation_message.msgid_singular = "1234567890abcdefgh\\ijklmno"
    >>> print(export_translation_message(translation_message, wrap_width=20))
    msgid ""
    "1234567890abcdefgh\\"
    "ijklmno"
    msgstr ""

    >>> translation_message = TranslationMessageData()
    >>> translation_message.msgid_singular = "1234567890abcdefg\\\\hijklmno"
    >>> print(export_translation_message(translation_message, wrap_width=20))
    msgid ""
    "1234567890abcdefg\\"
    "\\hijklmno"
    msgstr ""

For compatibility with msgcat -w, it also wraps on \\ properly.

    >>> translation_message = TranslationMessageData()
    >>> translation_message.msgid_singular = "\\\\\\\\\\"
    >>> print(export_translation_message(translation_message, wrap_width=5))
    msgid ""
    "\\\\"
    "\\\\"
    "\\"
    msgstr ""

    >>> print(export_translation_message(translation_message, wrap_width=6))
    msgid ""
    "\\\\\\"
    "\\\\"
    msgstr ""

There are a couple of other characters that will be escaped in the
output, too.

    >>> translation_message.msgid_singular = '"\t\r'
    >>> print(export_translation_message(translation_message, wrap_width=10))
    msgid ""
    "\"\t\r"
    msgstr ""


export_translation_message
--------------------------
Putting it all together to export full translation messages in the correct
format.

    >>> translation_message = TranslationMessageData()
    >>> translation_message.msgid_singular = "foo"
    >>> translation_message.addTranslation(
    ...     TranslationConstants.SINGULAR_FORM, "bar"
    ... )
    >>> print(export_translation_message(translation_message))
    msgid "foo"
    msgstr "bar"

Obsolete entries are prefixed with #~ .

    >>> translation_message.is_obsolete = True
    >>> print(export_translation_message(translation_message))
    #~ msgid "foo"
    #~ msgstr "bar"

Also, obsolete entries preserve fuzzy strings.

    >>> translation_message.flags = ("fuzzy",)
    >>> print(export_translation_message(translation_message))
    #, fuzzy
    #~ msgid "foo"
    #~ msgstr "bar"

Plural forms have its own way to represent translations.

    >>> translation_message = TranslationMessageData()
    >>> translation_message.msgid_singular = "foo"
    >>> translation_message.msgid_plural = "foos"
    >>> translation_message.addTranslation(
    ...     TranslationConstants.SINGULAR_FORM, "bar"
    ... )
    >>> translation_message.addTranslation(
    ...     TranslationConstants.PLURAL_FORM, "bars"
    ... )
    >>> translation_message.nplurals = 2
    >>> print(export_translation_message(translation_message))
    msgid "foo"
    msgid_plural "foos"
    msgstr[0] "bar"
    msgstr[1] "bars"

Backslashes are escaped (doubled) and quotes are backslashed.

    >>> translation_message = TranslationMessageData()
    >>> translation_message.msgid_singular = 'foo"bar\\baz'
    >>> translation_message.addTranslation(
    ...     TranslationConstants.SINGULAR_FORM, "z"
    ... )
    >>> print(export_translation_message(translation_message))
    msgid "foo\"bar\\baz"
    msgstr "z"

Tabs are backslashed too, with standard C syntax.

    >>> translation_message = TranslationMessageData()
    >>> translation_message.msgid_singular = "\tServer name: %s"
    >>> print(export_translation_message(translation_message))
    msgid "\tServer name: %s"
    msgstr ""

You can have context on messages.

    >>> translation_message = TranslationMessageData()
    >>> translation_message.context = "bla"
    >>> translation_message.msgid_singular = "foo"
    >>> translation_message.addTranslation(
    ...     TranslationConstants.SINGULAR_FORM, "bar"
    ... )
    >>> print(export_translation_message(translation_message))
    msgctxt "bla"
    msgid "foo"
    msgstr "bar"
