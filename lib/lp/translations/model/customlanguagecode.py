# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Database class for `ICustomLanguageCode`."""

__all__ = [
    'CustomLanguageCode',
    'HasCustomLanguageCodesMixin',
    ]

from storm.locals import (
    And,
    Int,
    Reference,
    Unicode,
    )
from zope.interface import implementer

from lp.registry.interfaces.distributionsourcepackage import (
    IDistributionSourcePackage,
    )
from lp.registry.interfaces.product import IProduct
from lp.services.database.interfaces import IStore
from lp.services.database.stormbase import StormBase
from lp.translations.interfaces.customlanguagecode import ICustomLanguageCode


@implementer(ICustomLanguageCode)
class CustomLanguageCode(StormBase):
    """See `ICustomLanguageCode`."""

    __storm_table__ = 'CustomLanguageCode'

    id = Int(primary=True)

    product_id = Int(name='product', allow_none=True, default=None)
    product = Reference(product_id, 'Product.id')

    distribution_id = Int(name='distribution', allow_none=True, default=None)
    distribution = Reference(distribution_id, 'Distribution.id')

    sourcepackagename_id = Int(
        name='sourcepackagename', allow_none=True, default=None)
    sourcepackagename = Reference(sourcepackagename_id, 'SourcePackageName.id')

    language_code = Unicode(name='language_code', allow_none=False)

    language_id = Int(name='language', allow_none=True, default=None)
    language = Reference(language_id, 'Language.id')

    def __init__(self, translation_target, language_code, language=None):
        super().__init__()
        self.product = None
        self.distribution = None
        self.sourcepackagename = None
        if IProduct.providedBy(translation_target):
            self.product = translation_target
        elif IDistributionSourcePackage.providedBy(translation_target):
            self.distribution = translation_target.distribution
            self.sourcepackagename = translation_target.sourcepackagename
        else:
            raise ValueError(
                "Expected IProduct or IDistributionSourcePackage, got %r" %
                translation_target)
        self.language_code = language_code
        self.language = language

    @property
    def translation_target(self):
        """See `ICustomLanguageCode`."""
        # Avoid circular imports
        from lp.registry.model.distributionsourcepackage import (
            DistributionSourcePackage,
            )
        if self.product:
            return self.product
        else:
            return DistributionSourcePackage(
                self.distribution, self.sourcepackagename)


class HasCustomLanguageCodesMixin:
    """Helper class to implement `IHasCustomLanguageCodes`."""

    def composeCustomLanguageCodeMatch(self):
        """Define in child: compose Storm match clause.

        This should return a condition for use in a Storm query to match
        `CustomLanguageCode` objects to `self`.
        """
        raise NotImplementedError("composeCustomLanguageCodeMatch")

    def createCustomLanguageCode(self, language_code, language):
        """See `IHasCustomLanguageCodes`."""
        return CustomLanguageCode(
            translation_target=self,
            language_code=language_code, language=language)

    def _queryCustomLanguageCodes(self, language_code=None):
        """Query `CustomLanguageCodes` belonging to `self`.

        :param language_code: Optional custom language code to look for.
            If not given, all codes will match.
        :return: A Storm result set.
        """
        match = self.composeCustomLanguageCodeMatch()
        store = IStore(CustomLanguageCode)
        if language_code is not None:
            match = And(
                match, CustomLanguageCode.language_code == language_code)
        return store.find(CustomLanguageCode, match)

    @property
    def has_custom_language_codes(self):
        """See `IHasCustomLanguageCodes`."""
        return self._queryCustomLanguageCodes().any() is not None

    @property
    def custom_language_codes(self):
        """See `IHasCustomLanguageCodes`."""
        return self._queryCustomLanguageCodes().order_by('language_code')

    def getCustomLanguageCode(self, language_code):
        """See `IHasCustomLanguageCodes`."""
        return self._queryCustomLanguageCodes(language_code).one()

    def removeCustomLanguageCode(self, custom_code):
        """See `IHasCustomLanguageCodes`."""
        language_code = custom_code.language_code
        return self._queryCustomLanguageCodes(language_code).remove()
