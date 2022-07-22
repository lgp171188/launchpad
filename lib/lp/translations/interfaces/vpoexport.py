# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).
"""Interfaces for efficient translation file exports."""

__all__ = [
    "IVPOExportSet",
    "IVPOExport",
]

from zope.interface import Interface
from zope.schema import Bool, Int, Object, Text

from lp import _
from lp.translations.interfaces.pofile import IPOFile
from lp.translations.interfaces.potmsgset import IPOTMsgSet
from lp.translations.interfaces.translations import TranslationConstants


class IVPOExportSet(Interface):
    """A collection of IVPOExport-providing rows."""

    def get_distroseries_pofiles(
        series, date=None, component=None, languagepack=None
    ):
        """Get a list of PO files which would be contained in an export of a
        distribution series.

        The filtering is done based on the 'series', last modified 'date',
        archive 'component' and if it belongs to a 'languagepack'

        Results are grouped by `POTemplate` to allow for caching of
        information related to the template.
        """

    def get_distroseries_pofiles_count(
        series, date=None, component=None, languagepack=None
    ):
        """Return the number of PO files which would be contained in an export
        of a distribution series.

        The filtering is done based on the 'series', last modified 'date',
        archive 'component' and if it belongs to a 'languagepack'
        """


class IVPOExport(Interface):
    """Shorthand of translation messages for efficient exports."""

    pofile = Object(
        title="Translation file", required=True, readonly=True, schema=IPOFile
    )

    diverged = Text(
        title="Message divergence.",
        description="A POTemplate this is a divergence for, or None.",
        required=False,
        readonly=True,
    )

    potmsgset = Object(
        title="See `IPOTMsgSet`.",
        required=True,
        readonly=True,
        schema=IPOTMsgSet,
    )

    sequence = Int(
        title="Message sequence number",
        description="As in IPOTMsgSet.",
        required=True,
        readonly=True,
    )

    comment = Text(
        title="Comment for translated message",
        description="Same as IPOTMsgSet.commenttext.",
        required=False,
        readonly=True,
    )

    source_comment = Text(
        title="Comment for original message",
        description="Same as IPOTMsgSet.sourcecomment.",
        required=False,
        readonly=True,
    )

    file_references = Text(
        title="Message's source location",
        description="Same as IPOTMsgSet.filereferences.",
        required=False,
        readonly=True,
    )

    flags_comment = Text(
        title="Message flags",
        description="Same as IPOTMsgSet.flagscomment.",
        required=False,
        readonly=True,
    )

    context = Text(
        title="Message context",
        description="As in IPOTMsgSet.",
        readonly=True,
        required=False,
    )

    msgid_singular = Text(
        title="Message identifier (singular)",
        description="See IPOMsgID.pomsgid.",
        required=True,
        readonly=True,
    )

    msgid_plural = Text(
        title="Message identifier (plural)",
        description="See IPOMsgID.pomsgid.",
        required=False,
        readonly=True,
    )

    is_current_ubuntu = Bool(
        title=_("Whether this message is currently used in Launchpad"),
        description="As in ITranslationMessage.",
        readonly=True,
        required=True,
    )

    is_current_upstream = Bool(
        title=_("Whether this message was imported"),
        description="As in ITranslationMessage.",
        readonly=True,
        required=True,
    )

    assert TranslationConstants.MAX_PLURAL_FORMS == 6, (
        "Change this code to support %d plural forms."
        % TranslationConstants.MAX_PLURAL_FORMS
    )

    translation0 = Text(
        title="Translation in plural form 0",
        description="As in ITranslationMessage.",
        readonly=True,
        required=False,
    )

    translation1 = Text(
        title="Translation in plural form 1",
        description="As in ITranslationMessage.",
        readonly=True,
        required=False,
    )

    translation2 = Text(
        title="Translation in plural form 2",
        description="As in ITranslationMessage.",
        readonly=True,
        required=False,
    )

    translation3 = Text(
        title="Translation in plural form 3",
        description="As in ITranslationMessage.",
        readonly=True,
        required=False,
    )

    translation4 = Text(
        title="Translation in plural form 4",
        description="As in ITranslationMessage.",
        readonly=True,
        required=False,
    )

    translation5 = Text(
        title="Translation in plural form 5",
        description="As in ITranslationMessage.",
        readonly=True,
        required=False,
    )
