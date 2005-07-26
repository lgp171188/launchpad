# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

"""Country interfaces."""

__metaclass__ = type

__all__ = [
    'ICountry',
    'ICountrySet',
    ]

from zope.i18nmessageid import MessageIDFactory
from zope.interface import Interface, Attribute
from zope.schema import Int, TextLine

from canonical.launchpad.fields import Title, Description
from canonical.launchpad.validators.name import valid_name

_ = MessageIDFactory('launchpad')

class ICountry(Interface):
    """The country description."""

    id = Int(
            title=_('Country ID'), required=True, readonly=True,
            )
    iso3166code2 = TextLine( title=_('iso3166code2'), required=True,
                             readonly=True)
    iso3166code3 = TextLine( title=_('iso3166code3'), required=True,
                             readonly=True)
    name = TextLine(
            title=_('Country name'), required=True,
            constraint=valid_name,
            )
    title = Title(
            title=_('Country title'), required=True,
            )
    description = Description(
            title=_('Description'), required=True,
            )

    languages = Attribute("An iterator over languages that are spoken in "
                          "that country.")


class ICountrySet(Interface):
    """A container for countries."""

    def __getitem__(key):
        """Get a country."""

    def __iter__():
        """Iterate through the countries in this set."""

