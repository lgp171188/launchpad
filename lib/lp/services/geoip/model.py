# Copyright 2009-2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    'GeoIP',
    'RequestLocalLanguages',
    'RequestPreferredLanguages',
    ]

import os

import GeoIP as libGeoIP
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


@implementer(IGeoIP)
class GeoIP:
    """See `IGeoIP`."""

    @cachedproperty
    def _gi(self):
        if not os.path.exists(config.launchpad.geoip_database):
            raise NoGeoIPDatabaseFound(
                "No GeoIP DB found. Please install launchpad-dependencies.")
        return libGeoIP.open(
            config.launchpad.geoip_database, libGeoIP.GEOIP_MEMORY_CACHE)

    def getCountryCodeByAddr(self, ip_address):
        """See `IGeoIP`."""
        if not ipaddress_is_global(ip_address):
            return None
        try:
            return self._gi.country_code_by_addr(ip_address)
        except SystemError:
            # libGeoIP may raise a SystemError if it doesn't find a record for
            # some IP addresses (e.g. 255.255.255.255), so we need to catch
            # that and return None here.
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
class RequestLocalLanguages(object):

    def __init__(self, request):
        self.request = request

    def getLocalLanguages(self):
        """See the IRequestLocationLanguages interface"""
        ip_addr = ipaddress_from_request(self.request)
        if ip_addr is None:
            # this happens during page testing, when the REMOTE_ADDR is not
            # set by Zope
            ip_addr = '127.0.0.1'
        gi = getUtility(IGeoIP)
        country = gi.getCountryByAddr(ip_addr)
        if country in [None, 'A0', 'A1', 'A2']:
            return []

        languages = [
            language for language in country.languages if language.visible]
        return sorted(languages, key=lambda x: x.englishname)


@implementer(IRequestPreferredLanguages)
class RequestPreferredLanguages(object):

    def __init__(self, request):
        self.request = request

    def getPreferredLanguages(self):
        """See the IRequestPreferredLanguages interface"""

        codes = IUserPreferredLanguages(self.request).getPreferredLanguages()
        languageset = getUtility(ILanguageSet)
        languages = set()

        for code in codes:
            # We need to ensure that the code received contains only ASCII
            # characters otherwise SQLObject will crash if it receives a query
            # with non printable ASCII characters.
            if isinstance(code, str):
                try:
                    code = code.decode('ASCII')
                except UnicodeDecodeError:
                    # skip language codes that can't be represented in ASCII
                    continue
            else:
                try:
                    code = code.encode('ASCII')
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


class NoGeoIPDatabaseFound(Exception):
    """No GeoIP database was found."""
