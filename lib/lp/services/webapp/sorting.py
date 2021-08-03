# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""This module contains sorting utility functions."""

__metaclass__ = type
__all__ = ['expand_numbers',
           'sorted_version_numbers',
           'sorted_dotted_numbers']

import re

import six


def expand_numbers(unicode_text, fill_digits=4):
    """Return a copy of the string with numbers zero filled.

    >>> print(expand_numbers(u'hello world'))
    hello world
    >>> print(expand_numbers(u'0.12.1'))
    0000.0012.0001
    >>> print(expand_numbers(u'0.12.1', 2))
    00.12.01
    >>> print(expand_numbers(u'branch-2-3.12'))
    branch-0002-0003.0012

    """
    assert(isinstance(unicode_text, six.text_type))

    def substitute_filled_numbers(match):
        return match.group(0).zfill(fill_digits)
    return re.sub(r'\d+', substitute_filled_numbers, unicode_text)


# Create translation table for numeric ordinals to their
# strings in reversed order.  So ord(u'0') -> u'9' and
# so on.
reversed_numbers_table = dict(
  zip(map(ord, u'0123456789'), reversed(u'0123456789')))


def _reversed_number_sort_key(text):
    """Return comparison value reversed for numbers only.

    >>> print(_reversed_number_sort_key(u'9.3'))
    0.6
    >>> print(_reversed_number_sort_key(u'2.4'))
    7.5
    >>> print(_reversed_number_sort_key(u'hello'))
    hello
    >>> print(_reversed_number_sort_key(u'bzr-0.13'))
    bzr-9.86

    """
    assert isinstance(text, six.text_type)
    assert isinstance(text, six.text_type)
    return text.translate(reversed_numbers_table)


def _identity(x):
    return x


def sorted_version_numbers(sequence, key=_identity):
    """Return a new sequence where 'newer' versions appear before 'older' ones.

    >>> bzr_versions = [u'0.9', u'0.10', u'0.11']
    >>> for version in sorted_version_numbers(bzr_versions):
    ...   print(version)
    0.11
    0.10
    0.9
    >>> bzr_versions = [u'bzr-0.9', u'bzr-0.10', u'bzr-0.11']
    >>> for version in sorted_version_numbers(bzr_versions):
    ...   print(version)
    bzr-0.11
    bzr-0.10
    bzr-0.9

    >>> class series:
    ...   def __init__(self, name):
    ...     self.name = six.ensure_text(name)
    >>> bzr_versions = [series('0.9'), series('0.10'), series('0.11'),
    ...                 series('bzr-0.9'), series('bzr-0.10'),
    ...                 series('bzr-0.11'), series('foo')]
    >>> from operator import attrgetter
    >>> for version in sorted_version_numbers(bzr_versions,
    ...                                       key=attrgetter('name')):
    ...   print(version.name)
    0.11
    0.10
    0.9
    bzr-0.11
    bzr-0.10
    bzr-0.9
    foo

    Items in the sequence can also be tuples or lists, allowing for
    tie-breaking.  In such cases, only the first element in each item is
    considered as a version.

    >>> bzr_versions = [
    ...     (series('0.9'), 8), (series('0.9'), 9), (series('0.9'), 10),
    ...     (series('1.0'), 1)]
    >>> for version, tiebreak in sorted_version_numbers(
    ...         bzr_versions, key=lambda item: item[0].name):
    ...     print(version.name, tiebreak)
    1.0 1
    0.9 8
    0.9 9
    0.9 10

    >>> bzr_versions = [
    ...     [series('0.9'), 8], [series('0.9'), 9], [series('0.9'), 10],
    ...     [series('1.0'), 1]]
    >>> for version, tiebreak in sorted_version_numbers(
    ...         bzr_versions, key=lambda item: item[0].name):
    ...     print(version.name, tiebreak)
    1.0 1
    0.9 8
    0.9 9
    0.9 10

    """
    def sort_key(item):
        k = key(item)
        if isinstance(k, (tuple, list)):
            return (
                (_reversed_number_sort_key(expand_numbers(k[0])),) +
                tuple(k[1:]))
        else:
            return _reversed_number_sort_key(expand_numbers(k))

    return sorted(sequence, key=sort_key)


def sorted_dotted_numbers(sequence, key=_identity):
    """Sorts numbers inside strings numerically.

    There are times where numbers are used as part of a string
    normally separated with a delimiter, frequently '.' or '-'.
    The intent of this is to sort '0.10' after '0.9'.

    The function returns a new sorted sequence.

    >>> bzr_versions = [u'0.9', u'0.10', u'0.11']
    >>> for version in sorted_dotted_numbers(bzr_versions):
    ...   print(version)
    0.9
    0.10
    0.11
    >>> bzr_versions = [u'bzr-0.9', u'bzr-0.10', u'bzr-0.11']
    >>> for version in sorted_dotted_numbers(bzr_versions):
    ...   print(version)
    bzr-0.9
    bzr-0.10
    bzr-0.11

    >>> class series:
    ...   def __init__(self, name):
    ...     self.name = six.ensure_text(name)
    >>> bzr_versions = [series('0.9'), series('0.10'), series('0.11'),
    ...                 series('bzr-0.9'), series('bzr-0.10'),
    ...                 series('bzr-0.11'), series('foo')]
    >>> from operator import attrgetter
    >>> for version in sorted_dotted_numbers(bzr_versions,
    ...                                      key=attrgetter('name')):
    ...   print(version.name)
    0.9
    0.10
    0.11
    bzr-0.9
    bzr-0.10
    bzr-0.11
    foo

    """
    return sorted(sequence, key=lambda x: expand_numbers(key(x)))
