# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Classes that implement LaunchpadStatistics."""

__all__ = [
    "LaunchpadStatistic",
    "LaunchpadStatisticSet",
]

from datetime import timezone

from storm.locals import DateTime, Int, Unicode
from zope.component import getUtility
from zope.interface import implementer

from lp.answers.enums import QuestionStatus
from lp.answers.model.question import Question
from lp.app.enums import ServiceUsage
from lp.blueprints.interfaces.specification import ISpecificationSet
from lp.bugs.model.bug import Bug
from lp.bugs.model.bugtask import BugTask
from lp.code.interfaces.branchcollection import IAllBranches
from lp.code.interfaces.gitcollection import IAllGitRepositories
from lp.registry.interfaces.person import IPersonSet
from lp.registry.model.product import Product
from lp.services.database.constants import UTC_NOW
from lp.services.database.interfaces import IStore
from lp.services.database.sqlbase import cursor
from lp.services.database.stormbase import StormBase
from lp.services.statistics.interfaces.statistic import (
    ILaunchpadStatistic,
    ILaunchpadStatisticSet,
)
from lp.services.worlddata.model.language import Language
from lp.translations.model.pofile import POFile
from lp.translations.model.pomsgid import POMsgID
from lp.translations.model.potemplate import POTemplate


@implementer(ILaunchpadStatistic)
class LaunchpadStatistic(StormBase):
    """A table of Launchpad Statistics."""

    __storm_table__ = "LaunchpadStatistic"
    __storm_order__ = "name"

    id = Int(primary=True)

    name = Unicode(allow_none=False)
    value = Int(allow_none=False)
    dateupdated = DateTime(
        allow_none=False, default=UTC_NOW, tzinfo=timezone.utc
    )

    def __init__(self, name, value):
        super().__init__()
        self.name = name
        self.value = value


@implementer(ILaunchpadStatisticSet)
class LaunchpadStatisticSet:
    """See `ILaunchpadStatisticSet`."""

    def __iter__(self):
        """See ILaunchpadStatisticSet."""
        store = IStore(LaunchpadStatistic)
        return iter(store.find(LaunchpadStatistic).order_by("name"))

    def update(self, name, value):
        """See ILaunchpadStatisticSet."""
        store = IStore(LaunchpadStatistic)
        stat = store.find(LaunchpadStatistic, name=name).one()
        if stat is None:
            stat = LaunchpadStatistic(name=name, value=value)
            store.add(stat)
        else:
            stat.value = value
            stat.dateupdated = UTC_NOW

    def dateupdated(self, name):
        """See ILaunchpadStatisticSet."""
        store = IStore(LaunchpadStatistic)
        stat = store.find(LaunchpadStatistic, name=name).one()
        if stat is None:
            return None
        return stat.dateupdated

    def value(self, name):
        """See ILaunchpadStatisticSet."""
        store = IStore(LaunchpadStatistic)
        stat = store.find(LaunchpadStatistic, name=name).one()
        if stat is None:
            return None
        return stat.value

    def updateStatistics(self, ztm):
        """See ILaunchpadStatisticSet."""
        self._updateMaloneStatistics(ztm)
        self._updateRegistryStatistics(ztm)
        self._updateRosettaStatistics(ztm)
        self._updateQuestionStatistics(ztm)
        self._updateBlueprintStatistics(ztm)
        self._updateCodeStatistics(ztm)
        getUtility(IPersonSet).updateStatistics()

    def _updateMaloneStatistics(self, ztm):
        store = IStore(Bug)
        self.update("bug_count", store.find(Bug).count())
        ztm.commit()

        self.update("bugtask_count", store.find(BugTask).count())
        ztm.commit()

        self.update(
            "products_using_malone",
            Product.selectBy(official_malone=True).count(),
        )
        ztm.commit()

        cur = cursor()
        cur.execute(
            "SELECT COUNT(DISTINCT product) + COUNT(DISTINCT distribution) "
            "FROM BugTask"
        )
        self.update("projects_with_bugs", cur.fetchone()[0] or 0)
        ztm.commit()

        cur = cursor()
        cur.execute(
            "SELECT COUNT(*) FROM (SELECT COUNT(distinct product) + "
            "                             COUNT(distinct distribution) "
            "                             AS places "
            "                             FROM BugTask GROUP BY bug) "
            "                      AS temp WHERE places > 1"
        )
        self.update("shared_bug_count", cur.fetchone()[0] or 0)
        ztm.commit()

    def _updateRegistryStatistics(self, ztm):
        self.update(
            "active_products",
            Product.select("active IS TRUE", distinct=True).count(),
        )
        self.update(
            "products_with_translations",
            Product.select(
                """
                POTemplate.productseries = ProductSeries.id AND
                Product.id = ProductSeries.product AND
                Product.active = TRUE
                """,
                clauseTables=["ProductSeries", "POTemplate"],
                distinct=True,
            ).count(),
        )
        self.update(
            "products_with_blueprints",
            Product.select(
                "Specification.product=Product.id AND Product.active IS TRUE",
                distinct=True,
                clauseTables=["Specification"],
            ).count(),
        )
        self.update(
            "products_with_branches",
            Product.select(
                "Branch.product=Product.id AND Product.active IS TRUE",
                distinct=True,
                clauseTables=["Branch"],
            ).count(),
        )
        self.update(
            "products_with_bugs",
            Product.select(
                "BugTask.product=Product.id AND Product.active IS TRUE",
                distinct=True,
                clauseTables=["BugTask"],
            ).count(),
        )
        self.update(
            "products_with_questions",
            Product.select(
                "Question.product=Product.id AND Product.active IS TRUE",
                distinct=True,
                clauseTables=["Question"],
            ).count(),
        )
        self.update(
            "reviewed_products",
            Product.selectBy(project_reviewed=True, active=True).count(),
        )

    def _updateRosettaStatistics(self, ztm):
        self.update(
            "products_using_rosetta",
            Product.selectBy(
                translations_usage=ServiceUsage.LAUNCHPAD
            ).count(),
        )
        self.update("potemplate_count", POTemplate.select().count())
        ztm.commit()
        self.update("pofile_count", IStore(POFile).find(POFile).count())
        ztm.commit()
        self.update("pomsgid_count", IStore(POMsgID).find(POMsgID).count())
        ztm.commit()
        self.update(
            "language_count",
            IStore(Language)
            .find(Language, POFile.language == Language.id)
            .config(distinct=True)
            .count(),
        )
        ztm.commit()

        cur = cursor()
        cur.execute("SELECT COUNT(DISTINCT submitter) FROM TranslationMessage")
        self.update("translator_count", cur.fetchone()[0] or 0)
        ztm.commit()

        cur = cursor()
        cur.execute(
            """
            SELECT COUNT(DISTINCT submitter)
            FROM TranslationMessage
            WHERE origin=2
            """
        )
        self.update("rosetta_translator_count", cur.fetchone()[0] or 0)
        ztm.commit()

        cur = cursor()
        cur.execute(
            """
            SELECT COUNT(DISTINCT product) FROM ProductSeries,POTemplate
            WHERE ProductSeries.id = POTemplate.productseries
            """
        )
        self.update("products_with_potemplates", cur.fetchone()[0] or 0)
        ztm.commit()

    def _updateQuestionStatistics(self, ztm):
        store = IStore(Question)
        self.update("question_count", store.find(Question).count())
        ztm.commit()

        self.update(
            "answered_question_count",
            store.find(
                Question, Question.status == QuestionStatus.ANSWERED
            ).count(),
        )
        ztm.commit()

        self.update(
            "solved_question_count",
            store.find(
                Question, Question.status == QuestionStatus.SOLVED
            ).count(),
        )
        ztm.commit()

        cur = cursor()
        cur.execute(
            "SELECT COUNT(DISTINCT product) + COUNT(DISTINCT distribution) "
            "FROM Question"
        )
        self.update("projects_with_questions_count", cur.fetchone()[0] or 0)
        ztm.commit()

    def _updateBlueprintStatistics(self, ztm):
        self.update(
            "public_specification_count",
            getUtility(ISpecificationSet).specificationCount(None),
        )
        ztm.commit()

    def _updateCodeStatistics(self, ztm):
        self.update(
            "public_branch_count",
            getUtility(IAllBranches).visibleByUser(None).count(),
        )
        ztm.commit()
        self.update(
            "public_git_repository_count",
            getUtility(IAllGitRepositories).visibleByUser(None).count(),
        )
        ztm.commit()
