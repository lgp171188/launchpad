# Copyright 2008 Canonical Ltd.  All rights reserved.
# Pylint doesn't grok zope interfaces.
# pylint: disable-msg=E0211,E0213

"""Interfaces for utility classes that operate on Zope fields."""

__metaclass__ = type
__all__ = [
    'IFieldMarshaller',
    ]

from zope.interface import Interface


class IFieldMarshaller(Interface):
    """A mapper between schema fields and representation fields"""

    def representationName(field_name):
        """Transform a field name into a name used in a representation.

        :param field_name: The name of the field within the entry.
        :return: The name to give this field when representing it in a
                 JSON hash.
        """

    def marshall(value):
        """Transform the given value into an object."""

    def unmarshall(entry, field_name, value):
        """Transform an object value into a string value.

        :param entry: The entry whose field this is.
        :param field_name: The name of the field within the entry.
        :value: The object value of the field.

        :return: The string value to give when representing the field
                 in a JSON hash.
"""
