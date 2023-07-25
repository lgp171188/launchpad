# Copyright 2009-2013 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "TranslationsPerson",
]

from storm.expr import SQL, And, Coalesce, Desc, Join, LeftJoin, Or, Select
from storm.info import ClassAlias
from storm.store import Store
from zope.component import adapter, getUtility
from zope.interface import implementer

from lp.app.enums import ServiceUsage
from lp.app.interfaces.launchpad import ILaunchpadCelebrities
from lp.registry.interfaces.person import IPerson
from lp.registry.model.distribution import Distribution
from lp.registry.model.distroseries import DistroSeries
from lp.registry.model.person import PersonLanguage
from lp.registry.model.product import Product
from lp.registry.model.productseries import ProductSeries
from lp.registry.model.projectgroup import ProjectGroup
from lp.registry.model.teammembership import TeamParticipation
from lp.services.database.interfaces import IStore
from lp.services.database.stormexpr import WithMaterialized
from lp.services.propertycache import cachedproperty, get_property_cache
from lp.services.worlddata.model.language import Language
from lp.translations.enums import TranslationPermission
from lp.translations.interfaces.translationgroup import ITranslationGroupSet
from lp.translations.interfaces.translationsperson import ITranslationsPerson
from lp.translations.interfaces.translator import ITranslatorSet
from lp.translations.model.pofile import POFile
from lp.translations.model.pofiletranslator import POFileTranslator
from lp.translations.model.potemplate import POTemplate
from lp.translations.model.translationgroup import TranslationGroup
from lp.translations.model.translationrelicensingagreement import (
    TranslationRelicensingAgreement,
)
from lp.translations.model.translator import Translator


@implementer(ITranslationsPerson)
@adapter(IPerson)
class TranslationsPerson:
    """See `ITranslationsPerson`."""

    def __init__(self, person):
        self.person = person

    @property
    def translatable_languages(self):
        """See `ITranslationsPerson`."""
        return (
            IStore(Language)
            .find(
                Language,
                PersonLanguage.language == Language.id,
                PersonLanguage.person == self.person,
                Language.code != "en",
                Language.visible,
            )
            .order_by(Language.englishname)
        )

    def getTranslationHistory(self, no_older_than=None):
        """See `ITranslationsPerson`."""
        conditions = And(POFileTranslator.person == self.person)
        if no_older_than is not None:
            conditions = And(
                conditions, POFileTranslator.date_last_touched >= no_older_than
            )

        entries = Store.of(self.person).find(POFileTranslator, conditions)
        return entries.order_by(Desc(POFileTranslator.date_last_touched))

    def hasTranslated(self):
        """See `ITranslationsPerson`."""
        return self.getTranslationHistory().any() is not None

    @property
    def translation_history(self):
        """See `ITranslationsPerson`."""
        return self.getTranslationHistory()

    @property
    def translation_groups(self):
        """See `ITranslationsPerson`."""
        return getUtility(ITranslationGroupSet).getByPerson(self.person)

    @property
    def translators(self):
        """See `ITranslationsPerson`."""
        return getUtility(ITranslatorSet).getByTranslator(self.person)

    @cachedproperty
    def _translations_relicensing_agreement(self):
        """Return whether translator agrees to relicense their translations.

        If they have made no explicit decision yet, return None.
        """
        relicensing_agreement = (
            IStore(TranslationRelicensingAgreement)
            .find(TranslationRelicensingAgreement, person=self.person)
            .one()
        )
        if relicensing_agreement is None:
            return None
        else:
            return relicensing_agreement.allow_relicensing

    def get_translations_relicensing_agreement(self):
        return self._translations_relicensing_agreement

    def set_translations_relicensing_agreement(self, value):
        """Set a translations relicensing decision by translator.

        If they have already made a decision, overrides it with the new one.
        """
        relicensing_agreement = (
            IStore(TranslationRelicensingAgreement)
            .find(TranslationRelicensingAgreement, person=self.person)
            .one()
        )
        if relicensing_agreement is None:
            relicensing_agreement = TranslationRelicensingAgreement(
                person=self.person, allow_relicensing=value
            )
        else:
            relicensing_agreement.allow_relicensing = value
        del get_property_cache(self)._translations_relicensing_agreement

    translations_relicensing_agreement = property(
        get_translations_relicensing_agreement,
        set_translations_relicensing_agreement,
        doc="See `ITranslationsPerson`.",
    )

    def getReviewableTranslationFiles(self, no_older_than=None):
        """See `ITranslationsPerson`."""
        if self.person.is_team:
            # A team as such does not work on translations.  Skip the
            # search for ones the team has worked on.
            return []
        with_statement = self._composePOFileReviewerCTEs(no_older_than)
        return (
            Store.of(self.person)
            .with_(with_statement)
            .using(
                POFile,
                Join(
                    POTemplate,
                    And(
                        POTemplate.id == POFile.potemplate_id,
                        POTemplate.iscurrent == True,
                    ),
                ),
            )
            .find(
                POFile,
                POFile.id.is_in(SQL("SELECT * FROM recent_pofiles")),
                POFile.unreviewed_count > 0,
                Or(
                    SQL(
                        "(POTemplate.productseries, POFile.language) IN "
                        "(SELECT * FROM translatable_productseries)"
                    ),
                    SQL(
                        "(POTemplate.distroseries, POFile.language) IN "
                        "(SELECT * FROM translatable_distroseries)"
                    ),
                ),
            )
            .config(distinct=True)
            .order_by(POFile.date_changed)
        )

    def _queryTranslatableFiles(self, no_older_than=None, languages=None):
        """Get `POFile`s this person could help translate.

        :param no_older_than: Oldest involvement to consider.  If the
            person last worked on a `POFile` before this date, that
            counts as not having worked on it.
        :param languages: Optional set of languages to restrict search to.
        :return: An unsorted query yielding `POFile`s.
        """
        if self.person.is_team:
            return []

        tables = self._composePOFileReviewerJoins(expect_reviewer_status=False)

        join_condition = And(
            POFileTranslator.person == self.person,
            POFileTranslator.pofile_id == POFile.id,
            POFile.language != getUtility(ILaunchpadCelebrities).english,
        )

        if no_older_than is not None:
            join_condition = And(
                join_condition,
                POFileTranslator.date_last_touched >= no_older_than,
            )

        translator_join = Join(POFileTranslator, join_condition)
        tables.append(translator_join)

        translated_count = (
            POFile.currentcount + POFile.updatescount + POFile.rosettacount
        )

        conditions = translated_count < POTemplate.messagecount

        # The person must not be a reviewer for this translation (unless
        # it's in the sense that any user gets review permissions
        # for it).
        permission = Coalesce(
            Distribution.translationpermission,
            Product.translationpermission,
            ProjectGroup.translationpermission,
        )
        Reviewership = ClassAlias(TeamParticipation, "Reviewership")
        # XXX JeroenVermeulen 2009-08-28 bug=420364: Storm's Coalesce()
        # can't currently infer its return type from its inputs, leading
        # to a "can't adapt" error.  Using the enum's .value works
        # around the problem.
        not_reviewer = Or(
            permission == TranslationPermission.OPEN.value,
            And(
                permission == TranslationPermission.STRUCTURED.value,
                Translator.id == None,
            ),
            And(
                permission == TranslationPermission.RESTRICTED.value,
                Translator.id != None,
                Reviewership.id == None,
            ),
        )

        conditions = And(conditions, not_reviewer)

        if languages is not None:
            conditions = And(conditions, POFile.language_id.is_in(languages))

        return Store.of(self.person).using(*tables).find(POFile, conditions)

    def getTranslatableFiles(self, no_older_than=None, urgent_first=True):
        """See `ITranslationsPerson`."""
        results = self._queryTranslatableFiles(no_older_than)

        translated_count = (
            POFile.currentcount + POFile.updatescount + POFile.rosettacount
        )
        ordering = translated_count - POTemplate.messagecount
        if not urgent_first:
            ordering = -ordering

        return results.order_by(ordering)

    def _composePOFileReviewerCTEs(self, no_older_than):
        """Compose Storm CTEs for common `POFile` queries.

        Returns a list of Storm CTEs, much the same as
        _composePOFileReviewerJoins."""
        clause = [
            POFileTranslator.person == self.person,
            POFile.language != getUtility(ILaunchpadCelebrities).english,
        ]
        if no_older_than:
            clause.append(POFileTranslator.date_last_touched >= no_older_than)
        store = IStore(POFile)
        RecentPOFiles = WithMaterialized(
            "recent_pofiles",
            store,
            Select(
                (POFile.id,),
                tables=[
                    POFileTranslator,
                    Join(POFile, POFileTranslator.pofile == POFile.id),
                ],
                where=And(*clause),
            ),
        )
        ReviewableGroups = WithMaterialized(
            "reviewable_groups",
            store,
            Select(
                (TranslationGroup.id, Translator.language_id),
                tables=[
                    TranslationGroup,
                    Join(
                        Translator,
                        Translator.translationgroup_id == TranslationGroup.id,
                    ),
                    Join(
                        TeamParticipation,
                        And(
                            TeamParticipation.team_id
                            == Translator.translator_id,
                            TeamParticipation.person == self.person,
                        ),
                    ),
                ],
            ),
        )
        TranslatableDistroSeries = WithMaterialized(
            "translatable_distroseries",
            store,
            Select(
                (DistroSeries.id, SQL("reviewable_groups.language")),
                tables=[
                    DistroSeries,
                    Join(
                        Distribution,
                        And(
                            Distribution.id == DistroSeries.distributionID,
                            Distribution.translations_usage
                            == ServiceUsage.LAUNCHPAD,
                            Distribution.translation_focusID
                            == DistroSeries.id,
                        ),
                    ),
                    Join(
                        SQL("reviewable_groups"),
                        SQL("reviewable_groups.id")
                        == Distribution.translationgroup_id,
                    ),
                ],
            ),
        )
        TranslatableProductSeries = WithMaterialized(
            "translatable_productseries",
            store,
            Select(
                (ProductSeries.id, SQL("reviewable_groups.language")),
                tables=[
                    ProductSeries,
                    Join(
                        Product,
                        And(
                            Product.id == ProductSeries.productID,
                            Product.translations_usage
                            == ServiceUsage.LAUNCHPAD,
                            Product.active == True,
                        ),
                    ),
                    LeftJoin(
                        ProjectGroup, ProjectGroup.id == Product.projectgroupID
                    ),
                    Join(
                        SQL("reviewable_groups"),
                        SQL("reviewable_groups.id")
                        == Product.translationgroup_id,
                    ),
                ],
            ),
        )
        return [
            RecentPOFiles,
            ReviewableGroups,
            TranslatableDistroSeries,
            TranslatableProductSeries,
        ]

    def _composePOFileReviewerJoins(self, expect_reviewer_status=True):
        """Compose certain Storm joins for common `POFile` queries.

        Returns a list of Storm joins for a query on `POFile`.  The
        joins will involve `Distribution`, `DistroSeries`, `POFile`,
        `Product`, `ProductSeries`, `ProjectGroup`, `TranslationGroup`,
        `TranslationTeam`, and `Translator`.

        The joins will restrict the ultimate query to `POFile`s
        distributions that use Launchpad for translations, which have a
        translation group and for which `self` is a reviewer.

        The added joins may make the overall query non-distinct, so be
        sure to enforce distinctness.
        """

        POTemplateJoin = Join(
            POTemplate,
            And(
                POTemplate.id == POFile.potemplate_id,
                POTemplate.iscurrent == True,
            ),
        )

        # This is a weird and complex diamond join.  Both DistroSeries
        # and ProductSeries are left joins, but one of them may
        # ultimately lead to a TranslationGroup.  In the case of
        # ProductSeries it may lead to up to two: one for the Product
        # and one for the ProjectGroup.
        DistroSeriesJoin = LeftJoin(
            DistroSeries, DistroSeries.id == POTemplate.distroseries_id
        )

        # If there's a DistroSeries, it should be the distro's
        # translation focus.
        distrojoin_conditions = And(
            Distribution.id == DistroSeries.distributionID,
            Distribution.translations_usage == ServiceUsage.LAUNCHPAD,
            Distribution.translation_focusID == DistroSeries.id,
        )

        DistroJoin = LeftJoin(Distribution, distrojoin_conditions)

        ProductSeriesJoin = LeftJoin(
            ProductSeries, ProductSeries.id == POTemplate.productseries_id
        )
        ProductJoin = LeftJoin(
            Product,
            And(
                Product.id == ProductSeries.productID,
                Product.translations_usage == ServiceUsage.LAUNCHPAD,
                Product.active == True,
            ),
        )

        ProjectJoin = LeftJoin(
            ProjectGroup, ProjectGroup.id == Product.projectgroupID
        )

        # Look up translation group.
        groupjoin_conditions = Or(
            TranslationGroup.id == Product.translationgroup_id,
            TranslationGroup.id == Distribution.translationgroup_id,
            TranslationGroup.id == ProjectGroup.translationgroup_id,
        )
        if expect_reviewer_status:
            GroupJoin = Join(TranslationGroup, groupjoin_conditions)
        else:
            GroupJoin = LeftJoin(TranslationGroup, groupjoin_conditions)

        # Look up translation team.
        translatorjoin_conditions = And(
            Translator.translationgroup_id == TranslationGroup.id,
            Translator.language_id == POFile.language_id,
        )
        if expect_reviewer_status:
            TranslatorJoin = Join(Translator, translatorjoin_conditions)
        else:
            TranslatorJoin = LeftJoin(Translator, translatorjoin_conditions)

        # Check for translation-team membership.  Use alias for
        # TeamParticipation; the query may want to include other
        # instances of that table.  It's just a linking table so the
        # query won't be interested in its actual contents anyway.
        Reviewership = ClassAlias(TeamParticipation, "Reviewership")
        reviewerjoin_condition = And(
            Reviewership.team_id == Translator.translator_id,
            Reviewership.person_id == self.person.id,
        )
        if expect_reviewer_status:
            TranslationTeamJoin = Join(Reviewership, reviewerjoin_condition)
        else:
            TranslationTeamJoin = LeftJoin(
                Reviewership, reviewerjoin_condition
            )

        return [
            POFile,
            POTemplateJoin,
            DistroSeriesJoin,
            DistroJoin,
            ProductSeriesJoin,
            ProductJoin,
            ProjectJoin,
            GroupJoin,
            TranslatorJoin,
            TranslationTeamJoin,
        ]
