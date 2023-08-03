# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = ["SpokenIn"]

from storm.locals import Int, Reference
from zope.interface import implementer

from lp.services.database.stormbase import StormBase
from lp.services.worlddata.interfaces.spokenin import ISpokenIn


@implementer(ISpokenIn)
class SpokenIn(StormBase):
    """A way of telling which languages are spoken in which countries.

    This table maps a language which is SpokenIn a country.
    """

    __storm_table__ = "SpokenIn"

    id = Int(primary=True)
    country_id = Int(name="country", allow_none=False)
    country = Reference(country_id, "Country.id")
    language_id = Int(name="language", allow_none=False)
    language = Reference(language_id, "Language.id")
