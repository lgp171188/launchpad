# Copyright 2009-2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from zope.interface import Interface

__all__ = [
    "IGeoIP",
    "IRequestLocalLanguages",
    "IRequestPreferredLanguages",
]


class IGeoIP(Interface):
    """The GeoIP utility, which represents the GeoIP database."""

    def getCountryCodeByAddr(ip_address):
        """Return the country code for the given IP address, or None."""

    def getCountryByAddr(ip_address):
        """Find and return an ICountry based on the given IP address.

        :param ip_address: Must be text in the dotted-address notation,
            for example '196.131.31.25'
        """


class IRequestLocalLanguages(Interface):
    def getLocalLanguages():
        """Return a list of the Language objects which represent languages
        spoken in the country from which that IP address is likely to be
        coming."""


class IRequestPreferredLanguages(Interface):
    def getPreferredLanguages():
        """Return a list of the Language objects which represent languages
        listed in the HTTP_ACCEPT_LANGUAGE header."""
