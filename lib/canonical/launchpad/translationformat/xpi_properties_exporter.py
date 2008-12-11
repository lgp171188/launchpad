# Copyright 2008 Canonical Ltd.  All rights reserved.

__metaclass__ = type

__all__ = [
    'XpiPropertiesSubExporter'
    ]


import re


def has_comment(message):
    """Does `TranslationMessageData` contain a comment?"""
    return message.comment is not None and message.comment.strip() != ''


class XpiPropertiesSubExporter:
    """Produce a properties file to go into an XPI file."""

    def _escape(self, string):
        """Escape message string for use in properties file."""
        # Escape backslashes first, before we start inserting ones of
        # our own.  Then the other stuff.  Replace newlines by \n etc.,
        # and encode non-ASCII characters as \uXXXX.
        string = string.replace('\\', '\\\\')
        string = re.sub('''(["'])''', '\\\\\\1', string)
        # Escape newlines as \n etc, and non-ASCII as \uXXXX
        return string.encode('ascii', 'backslashreplace')

    def _escape_comment(self, comment):
        """Escape comment string for use in properties file."""
        # Prevent comment from breaking out of /* ... */ block.
        comment = re.sub('\*\/', '*X/', comment)
        return comment.encode('ascii', 'unicode-escape')

    def export(self, translation_file):
        assert translation_file.path.endswith('.properties'), (
            "Unexpected properties file suffix: %s" % translation_file.path)
        contents = []
        for message in translation_file.messages:
            if not message.translations:
                continue
            if has_comment(message):
                contents.append(
                    "\n/* %s */" % self._escape_comment(message.comment))
            msgid = self._escape(message.msgid_singular)
            text = self._escape(message.translations[0])
            line = "%s=%s" % (msgid, text)
            contents.append(line)

        return '\n'.join(contents)
