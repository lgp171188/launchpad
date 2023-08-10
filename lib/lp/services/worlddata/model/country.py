# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = ["Country", "CountrySet", "Continent"]

from storm.locals import Int, Reference, ReferenceSet, Unicode
from zope.interface import implementer

from lp.app.errors import NotFoundError
from lp.services.database.constants import DEFAULT
from lp.services.database.interfaces import IStore
from lp.services.database.stormbase import StormBase
from lp.services.worlddata.interfaces.country import (
    IContinent,
    ICountry,
    ICountrySet,
)


@implementer(ICountry)
class Country(StormBase):
    """A country."""

    __storm_table__ = "Country"

    # default to listing newest first
    __storm_order__ = "name"

    # db field names
    id = Int(primary=True)
    name = Unicode(name="name", allow_none=False)
    iso3166code2 = Unicode(name="iso3166code2", allow_none=False)
    iso3166code3 = Unicode(name="iso3166code3", allow_none=False)
    title = Unicode(name="title", allow_none=True, default=DEFAULT)
    description = Unicode(name="description")
    continent_id = Int(name="continent", default=None)
    continent = Reference(continent_id, "Continent.id")
    languages = ReferenceSet(
        id, "SpokenIn.country_id", "SpokenIn.language_id", "Language.id"
    )


@implementer(ICountrySet)
class CountrySet:
    """A set of countries"""

    def __getitem__(self, iso3166code2):
        country = (
            IStore(Country).find(Country, iso3166code2=iso3166code2).one()
        )
        if country is None:
            raise NotFoundError(iso3166code2)
        return country

    def __iter__(self):
        yield from IStore(Country).find(Country)

    def getByName(self, name):
        """See `ICountrySet`."""
        return IStore(Country).find(Country, name=name).one()

    def getByCode(self, code):
        """See `ICountrySet`."""
        return IStore(Country).find(Country, iso3166code2=code).one()

    def getCountries(self):
        """See `ICountrySet`."""
        return IStore(Country).find(Country).order_by(Country.iso3166code2)


@implementer(IContinent)
class Continent(StormBase):
    """See IContinent."""

    __storm_table__ = "Continent"
    __storm_order__ = ["name", "id"]

    id = Int(primary=True)
    name = Unicode(allow_none=False)
    code = Unicode(allow_none=False)
