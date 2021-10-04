# Copyright 2009-2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = ['POTranslation']

import six
from storm.expr import Func
from storm.locals import (
    Int,
    Unicode,
    )
from zope.interface import implementer

from lp.app.errors import NotFoundError
from lp.services.database.interfaces import IStore
from lp.services.database.stormbase import StormBase
from lp.translations.interfaces.potranslation import IPOTranslation


@implementer(IPOTranslation)
class POTranslation(StormBase):

    __storm_table__ = 'POTranslation'

    id = Int(primary=True)
    translation = Unicode(name='translation', allow_none=False)

    def __init__(self, translation):
        super(POTranslation, self).__init__()
        self.translation = translation

    @classmethod
    def new(cls, translation):
        """Return a new POTranslation object for the given translation."""
        potranslation = cls(translation)
        IStore(cls).add(potranslation)
        return potranslation

    @classmethod
    def getByTranslation(cls, key):
        """Return a POTranslation object for the given translation."""

        # We can't search directly on msgid, because this database column
        # contains values too large to index. Instead we search on its
        # hash, which *is* indexed
        r = IStore(POTranslation).find(
            POTranslation,
            Func('sha1', POTranslation.translation) ==
                Func('sha1', six.ensure_text(key))).one()

        if r is not None:
            return r
        else:
            raise NotFoundError(six.ensure_str(key, errors='replace'))

    @classmethod
    def getOrCreateTranslation(cls, key):
        """Return a POTranslation object for the given translation, or create
        it if it doesn't exist.
        """
        # If this is not a unicode object, it had better be ASCII or UTF-8.
        # XXX: JeroenVermeulen 2008-06-06 bug=237868: non-ascii str strings
        # should be contained in the parser or the browser code.
        key = six.ensure_text(key)

        try:
            return cls.getByTranslation(key)
        except NotFoundError:
            return cls.new(key)
