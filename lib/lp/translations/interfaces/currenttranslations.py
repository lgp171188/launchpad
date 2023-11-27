#  Copyright 2022 Canonical Ltd.  This software is licensed under the
#  GNU Affero General Public License version 3 (see the file LICENSE).
from typing import NamedTuple, Optional

from zope.interface import Interface

__all__ = [
    "CurrentTranslationKey",
    "ICurrentTranslations",
]


class CurrentTranslationKey(NamedTuple):
    potmsgset_id: int
    potemplate_id: Optional[int]
    language_id: int
    side: int


class ICurrentTranslations(Interface):
    def getCurrentTranslation(
        potmsgset,
        potemplate,
        language,
        side,
        use_cache=False,
    ):
        """
        Get the current translation message for a given POTMsgSet, POTemplate,
        Language and side.

        Optionally, try fetching the result from cache to avoid database
        query (see `cacheCurrentTranslations`)
        """

    def getCurrentTranslations(
        potmsgsets,
        potemplates,
        languages,
        sides,
    ):
        """
        Get the current translation messages for a collection of POTMsgSets,
        POTemplates, Languages and Sides.

        Specifically, it gets messages for the full cross-product of all
        the given parameters.

        The results are returned as a dictionary organized by
        `CurrentTranslationKey`.
        """

    def cacheCurrentTranslations(
        msgsets,
        potemplates,
        languages,
        sides,
    ):
        """
        Cache the current translation messages for a collection of POTMsgSets,
        POTemplates, Languages and Sides.
        """
