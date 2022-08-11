# Copyright 2009-2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Character encoding utilities"""

__all__ = [
    "escape_nonascii_uniquely",
    "guess",
    "is_ascii_only",
    "wsgi_native_string",
]

import codecs
import re

import six

_boms = [
    (codecs.BOM_UTF16_BE, "utf_16_be"),
    (codecs.BOM_UTF16_LE, "utf_16_le"),
    (codecs.BOM_UTF32_BE, "utf_32_be"),
    (codecs.BOM_UTF32_LE, "utf_32_le"),
]


def guess(s):
    r"""
    Attempts to heuristically guess a strings encoding, returning
    a Unicode string.

    This method should only be used for importing legacy data from systems
    or files where the encoding is not known. This method will always
    succeed and normally guess the correct encoding, but it is only
    a guess and will be incorrect some of the time. Also note that
    data may be lost, as if we cannot determine the correct encoding
    we fall back to ISO-8859-1 and replace unrecognized characters with
    \ufffd characters (the Unicode unrepresentable code point).

    NB: We currently only cope with the major Western character
    sets - we need to change the algorithm to cope with asian languages.
    One way that apparently works is to convert the string into all possible
    encodings, one at a time, and if successful score them based on the
    number of meaningful characters (using the unicodedata module to
    let us know what are control characters, letters, printable characters
    etc.).


    ASCII is easy

    >>> print(guess(b'hello'))
    hello

    Unicode raises an exception to annoy lazy programmers. It should also
    catches bugs as if you have valid Unicode you shouldn't be going anywhere
    near this method.

    >>> guess(u'Caution \N{BIOHAZARD SIGN}')
    Traceback (most recent call last):
    ...
    TypeError: ...

    UTF-8 is our best guess

    >>> print(guess(u'100% Pure Beef\N{TRADE MARK SIGN}'.encode('UTF-8')))
    100% Pure Beef™

    But we fall back to ISO-8859-1 if UTF-8 fails

    >>> u = u'Ol\N{LATIN SMALL LETTER E WITH ACUTE}'
    >>> u.encode('UTF-8') == u.encode('ISO-8859-1')
    False
    >>> print(guess(u.encode('UTF-8')))
    Olé
    >>> print(guess(u.encode('ISO-8859-1')))
    Olé

    However, if the string contains ISO-8859-1 control characters, it is
    probably a CP1252 document (Windows).

    >>> u = u'Show me the \N{EURO SIGN}'
    >>> u.encode('UTF-8') == u.encode('CP1252')
    False
    >>> print(guess(u.encode('UTF-8')))
    Show me the €
    >>> print(guess(u.encode('CP1252')))
    Show me the €

    We also check for characters common in ISO-8859-15 that are uncommon
    in ISO-8859-1, and use ISO-8859-15 if they are found.

    >>> u = u'\N{LATIN SMALL LETTER S WITH CARON}'
    >>> print(guess(u.encode('iso-8859-15')))
    š

    Strings with a BOM are unambiguous.

    >>> print(guess(u'hello'.encode('UTF-16')))
    hello

    However, UTF-16 strings without a BOM will be interpreted as ISO-8859-1.
    I doubt this is a problem, as we are unlikely to see this except with
    asian languages and in these cases other encodings we don't support
    at the moment like ISO-2022-jp, BIG5, SHIFT-JIS etc. will be a bigger
    problem.

    >>> guess(u'hello'.encode('UTF-16be')) == u'\x00h\x00e\x00l\x00l\x00o'
    True

    """

    # Calling this method with a Unicode argument indicates a hidden bug
    # that will bite you eventually -- StuartBishop 20050709
    if isinstance(s, str):
        raise TypeError("encoding.guess called with Unicode string %r" % (s,))

    # Attempt to use an objects default Unicode conversion, for objects
    # that can encode themselves as ASCII.
    if not isinstance(s, bytes):
        try:
            return str(s)
        except UnicodeDecodeError:
            pass

    # Detect BOM
    try:
        for bom, encoding in _boms:
            if s.startswith(bom):
                return str(s[len(bom) :], encoding)
    except UnicodeDecodeError:
        pass

    # Try preferred encoding
    try:
        return str(s, "UTF-8")
    except UnicodeDecodeError:
        pass

    # If we have characters in this range, it is probably CP1252
    if re.search(rb"[\x80-\x9f]", s) is not None:
        try:
            return str(s, "CP1252")
        except UnicodeDecodeError:
            pass

    # If we have characters in this range, it is probably ISO-8859-15
    if re.search(rb"[\xa4\xa6\xa8\xb4\xb8\xbc-\xbe]", s) is not None:
        try:
            return str(s, "ISO-8859-15")
        except UnicodeDecodeError:
            pass

    # Otherwise we default to ISO-8859-1
    return str(s, "ISO-8859-1", "replace")


def escape_nonascii_uniquely(bogus_string):
    r"""Replace non-ascii characters with a hex representation.

    This is mainly for preventing emails with invalid characters from causing
    oopses. The nonascii characters could have been removed or just converted
    to "?", but this provides some insight into what the bogus data was, and
    it prevents the message-id from two unrelated emails matching because
    all the nonascii characters have been replaced with the same ascii
    character.

    >>> print(len(b'\xa9'), len(b'\\xa9'))
    1 4
    >>> print(six.ensure_str(escape_nonascii_uniquely(b'hello \xa9')))
    hello \xa9

    This string only has ascii characters, so escape_nonascii_uniquely()
    actually has no effect.

    >>> print(six.ensure_str(escape_nonascii_uniquely(b'hello \\xa9')))
    hello \xa9

    :type bogus_string: bytes
    """
    nonascii_regex = re.compile(rb"[\200-\377]")

    # By encoding the invalid ascii with a backslash, x, and then the
    # hex value, it makes it easy to decode it by pasting into a python
    # interpreter. quopri() is not used, since that could caused the
    # decoding of an email to fail.
    def quote(match):
        return b"\\x%x" % ord(match.group(0))

    return nonascii_regex.sub(quote, bogus_string)


def is_ascii_only(string):
    r"""Ensure that the string contains only ASCII characters.

    >>> is_ascii_only(u'ascii only')
    True
    >>> is_ascii_only(b'ascii only')
    True
    >>> is_ascii_only(b'\xf4')
    False
    >>> is_ascii_only(u'\xf4')
    False
    """
    try:
        if isinstance(string, bytes):
            string.decode("ascii")
        else:
            string.encode("ascii")
    except UnicodeError:
        return False
    else:
        return True


def wsgi_native_string(s):
    """Make a native string suitable for use in WSGI.

    PEP 3333 requires environment variables to be native strings that
    contain only code points representable in ISO-8859-1.  To support
    porting to Python 3 via an intermediate stage of Unicode literals in
    Python 2, we enforce this here.
    """
    result = six.ensure_str(s, encoding="ISO-8859-1")
    if isinstance(s, str):
        # Ensure we're limited to ISO-8859-1.
        result.encode("ISO-8859-1")
    return result
