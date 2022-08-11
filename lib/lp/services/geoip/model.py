# Copyright 2009-2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "GeoIP",
    "RequestLocalLanguages",
    "RequestPreferredLanguages",
]

import os

from geoip2.database import Reader
from geoip2.errors import AddressNotFoundError
from zope.component import getUtility
from zope.i18n.interfaces import IUserPreferredLanguages
from zope.interface import implementer

from lp.services.config import config
from lp.services.geoip.helpers import (
    ipaddress_from_request,
    ipaddress_is_global,
)
from lp.services.geoip.interfaces import (
    IGeoIP,
    IRequestLocalLanguages,
    IRequestPreferredLanguages,
)
from lp.services.propertycache import cachedproperty
from lp.services.worlddata.interfaces.country import ICountrySet
from lp.services.worlddata.interfaces.language import ILanguageSet


class NonexistentGeoIPDatabase(Exception):
    """Configured GeoIP database does not exist."""


@implementer(IGeoIP)
class GeoIP:
    """See `IGeoIP`."""

    @cachedproperty
    def _gi(self):
        if config.launchpad.geoip_database is None:
            return None
        if not os.path.exists(config.launchpad.geoip_database):
            raise NonexistentGeoIPDatabase(
                "The configured GeoIP DB (%s) does not exist."
                % config.launchpad.geoip_database
            )
        return Reader(config.launchpad.geoip_database)

    def getCountryCodeByAddr(self, ip_address):
        """See `IGeoIP`."""
        if not ipaddress_is_global(ip_address):
            return None
        if self._gi is None:
            return None
        try:
            return self._gi.country(ip_address).country.iso_code
        except AddressNotFoundError:
            return None

    def getCountryByAddr(self, ip_address):
        """See `IGeoIP`."""
        if not ipaddress_is_global(ip_address):
            return None
        countrycode = self.getCountryCodeByAddr(ip_address)
        if countrycode is None:
            return None

        countryset = getUtility(ICountrySet)
        try:
            country = countryset[countrycode]
        except KeyError:
            return None
        else:
            return country


@implementer(IRequestLocalLanguages)
class RequestLocalLanguages:
    def __init__(self, request):
        self.request = request

    def getLocalLanguages(self):
        """See the IRequestLocationLanguages interface"""
        ip_addr = ipaddress_from_request(self.request)
        if ip_addr is None:
            # this happens during page testing, when the REMOTE_ADDR is not
            # set by Zope
            ip_addr = "127.0.0.1"
        gi = getUtility(IGeoIP)
        country = gi.getCountryByAddr(ip_addr)
        if country in [None, "A0", "A1", "A2"]:
            return []

        languages = [
            language for language in country.languages if language.visible
        ]
        return sorted(languages, key=lambda x: x.englishname)


@implementer(IRequestPreferredLanguages)
class RequestPreferredLanguages:
    def __init__(self, request):
        self.request = request

    def getPreferredLanguages(self):
        """See the IRequestPreferredLanguages interface"""

        codes = IUserPreferredLanguages(self.request).getPreferredLanguages()
        languageset = getUtility(ILanguageSet)
        languages = set()

        for code in codes:
            # Language tags are restricted to ASCII (see RFC 5646).
            if isinstance(code, bytes):
                try:
                    code = code.decode("ASCII")
                except UnicodeDecodeError:
                    # skip language codes that can't be represented in ASCII
                    continue
            else:
                try:
                    code.encode("ASCII")
                except UnicodeEncodeError:
                    # skip language codes that can't be represented in ASCII
                    continue
            code = languageset.canonicalise_language_code(code)
            try:
                languages.add(languageset[code])
            except KeyError:
                pass

        languages = [language for language in languages if language.visible]
        return sorted(languages, key=lambda x: x.englishname)
