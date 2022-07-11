# Copyright 2009-2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Security adapters for the lp.services.worlddata package."""

__all__ = []

from lp.app.security import AnonymousAuthorization
from lp.security import OnlyRosettaExpertsAndAdmins
from lp.services.worlddata.interfaces.country import ICountry
from lp.services.worlddata.interfaces.language import (
    ILanguage,
    ILanguageSet,
    )


class ViewCountry(AnonymousAuthorization):
    """Anyone can view a Country."""
    usedfor = ICountry


class ViewLanguageSet(AnonymousAuthorization):
    """Anyone can view an ILanguageSet."""
    usedfor = ILanguageSet


class AdminLanguageSet(OnlyRosettaExpertsAndAdmins):
    permission = 'launchpad.Admin'
    usedfor = ILanguageSet


class ViewLanguage(AnonymousAuthorization):
    """Anyone can view an ILanguage."""
    usedfor = ILanguage


class AdminLanguage(OnlyRosettaExpertsAndAdmins):
    permission = 'launchpad.Admin'
    usedfor = ILanguage
