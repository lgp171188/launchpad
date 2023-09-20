# Copyright 2009-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "TranslationGroup",
    "TranslationGroupSet",
]

import operator
from datetime import timezone

from storm.expr import Desc, Join, LeftJoin
from storm.properties import DateTime, Int, Unicode
from storm.references import Reference, ReferenceSet
from storm.store import Store
from zope.interface import implementer

from lp.app.errors import NotFoundError
from lp.registry.interfaces.person import validate_public_person
from lp.registry.model.person import Person
from lp.registry.model.teammembership import TeamParticipation
from lp.services.database import bulk
from lp.services.database.constants import DEFAULT
from lp.services.database.decoratedresultset import DecoratedResultSet
from lp.services.database.interfaces import IStandbyStore, IStore
from lp.services.database.stormbase import StormBase
from lp.services.librarian.model import LibraryFileAlias, LibraryFileContent
from lp.services.worlddata.model.language import Language
from lp.translations.interfaces.translationgroup import (
    ITranslationGroup,
    ITranslationGroupSet,
)
from lp.translations.model.translator import Translator


@implementer(ITranslationGroup)
class TranslationGroup(StormBase):
    """A TranslationGroup."""

    __storm_table__ = "TranslationGroup"
    # default to listing alphabetically
    __storm_order__ = "name"

    # db field names
    id = Int(primary=True)
    name = Unicode(allow_none=False)
    title = Unicode(allow_none=False)
    summary = Unicode(allow_none=False)
    datecreated = DateTime(
        allow_none=False, default=DEFAULT, tzinfo=timezone.utc
    )
    owner_id = Int(
        name="owner", validator=validate_public_person, allow_none=False
    )
    owner = Reference(owner_id, "Person.id")

    # useful joins
    distributions = ReferenceSet("id", "Distribution.translationgroup_id")
    languages = ReferenceSet(
        "id",
        "Translator.translationgroup_id",
        "Translator.language_id",
        "Language.id",
    )
    translators = ReferenceSet("id", "Translator.translationgroup_id")
    translation_guide_url = Unicode(allow_none=True, default=None)

    def __init__(
        self,
        name,
        title,
        summary,
        owner,
        datecreated=DEFAULT,
        translation_guide_url=None,
    ):
        super().__init__()
        self.name = name
        self.title = title
        self.summary = summary
        self.owner = owner
        self.datecreated = datecreated
        self.translation_guide_url = translation_guide_url

    def __getitem__(self, language_code):
        """See `ITranslationGroup`."""
        query = Store.of(self).find(
            Translator,
            Translator.translationgroup == self,
            Translator.language_id == Language.id,
            Language.code == language_code,
        )

        translator = query.one()
        if translator is None:
            raise NotFoundError(language_code)

        return translator

    # used to note additions
    def add(self, content):
        """See ITranslationGroup."""
        return content

    # adding and removing translators
    def remove_translator(self, translator):
        """See ITranslationGroup."""
        IStore(Translator).find(Translator, id=translator.id).remove()

    # get a translator by language or code
    def query_translator(self, language):
        """See ITranslationGroup."""
        return (
            IStore(Translator)
            .find(Translator, language=language, translationgroup=self)
            .one()
        )

    @property
    def products(self):
        """See `ITranslationGroup`."""
        # Avoid circular imports.
        from lp.registry.model.product import Product

        return IStore(Product).find(
            Product, translationgroup=self, active=True
        )

    @property
    def projects(self):
        """See `ITranslationGroup`."""
        # Avoid circular imports.
        from lp.registry.model.projectgroup import ProjectGroup

        return IStore(ProjectGroup).find(
            ProjectGroup, translationgroup=self, active=True
        )

    # A limit of projects to get for the `top_projects`.
    TOP_PROJECTS_LIMIT = 6

    @property
    def top_projects(self):
        """See `ITranslationGroup`."""
        # XXX Danilo 2009-08-25: We should make this list show a list
        # of projects based on the top translations karma (bug #418493).
        goal = self.TOP_PROJECTS_LIMIT
        projects = list(self.distributions[:goal])
        found = len(projects)
        if found < goal:
            projects.extend(list(self.projects[: goal - found]))
            found = len(projects)
        if found < goal:
            projects.extend(list(self.products[: goal - found]))
        return projects

    @property
    def number_of_remaining_projects(self):
        """See `ITranslationGroup`."""
        total = (
            self.projects.count()
            + self.products.count()
            + self.distributions.count()
        )
        if total > self.TOP_PROJECTS_LIMIT:
            return total - self.TOP_PROJECTS_LIMIT
        else:
            return 0

    def fetchTranslatorData(self):
        """See `ITranslationGroup`."""
        # Fetch Translator, Language, and Person; but also prefetch the
        # icon information.
        using = [
            Translator,
            Language,
            Person,
            LeftJoin(LibraryFileAlias, LibraryFileAlias.id == Person.icon_id),
            LeftJoin(
                LibraryFileContent,
                LibraryFileContent.id == LibraryFileAlias.content_id,
            ),
        ]
        tables = (
            Translator,
            Language,
            Person,
            LibraryFileAlias,
            LibraryFileContent,
        )
        translator_data = (
            Store.of(self)
            .using(*using)
            .find(
                tables,
                Translator.translationgroup == self,
                Language.id == Translator.language_id,
                Person.id == Translator.translator_id,
            )
        )
        translator_data = translator_data.order_by(Language.englishname)
        mapper = lambda row: row[slice(0, 3)]
        return DecoratedResultSet(translator_data, mapper)

    def fetchProjectsForDisplay(self, user):
        """See `ITranslationGroup`."""
        # Avoid circular imports.
        from lp.registry.model.product import (
            Product,
            ProductSet,
            get_precached_products,
        )

        products = list(
            IStore(Product)
            .find(
                Product,
                Product.translationgroup == self,
                Product.active == True,
                ProductSet.getProductPrivacyFilter(user),
            )
            .order_by(Product.display_name)
        )
        get_precached_products(products, need_licences=True)
        icons = bulk.load_related(LibraryFileAlias, products, ["icon_id"])
        bulk.load_related(LibraryFileContent, icons, ["content_id"])
        return products

    def fetchProjectGroupsForDisplay(self):
        """See `ITranslationGroup`."""
        # Avoid circular imports.
        from lp.registry.model.projectgroup import ProjectGroup

        using = [
            ProjectGroup,
            LeftJoin(
                LibraryFileAlias, LibraryFileAlias.id == ProjectGroup.icon_id
            ),
            LeftJoin(
                LibraryFileContent,
                LibraryFileContent.id == LibraryFileAlias.content_id,
            ),
        ]
        tables = (
            ProjectGroup,
            LibraryFileAlias,
            LibraryFileContent,
        )
        project_data = (
            IStandbyStore(ProjectGroup)
            .using(*using)
            .find(
                tables,
                ProjectGroup.translationgroup == self,
                ProjectGroup.active == True,
            )
            .order_by(ProjectGroup.display_name)
        )

        return DecoratedResultSet(project_data, operator.itemgetter(0))

    def fetchDistrosForDisplay(self):
        """See `ITranslationGroup`."""
        # Avoid circular imports.
        from lp.registry.model.distribution import Distribution

        using = [
            Distribution,
            LeftJoin(
                LibraryFileAlias, LibraryFileAlias.id == Distribution.icon_id
            ),
            LeftJoin(
                LibraryFileContent,
                LibraryFileContent.id == LibraryFileAlias.content_id,
            ),
        ]
        tables = (
            Distribution,
            LibraryFileAlias,
            LibraryFileContent,
        )
        distro_data = (
            IStandbyStore(Distribution)
            .using(*using)
            .find(tables, Distribution.translationgroup == self)
            .order_by(Distribution.display_name)
        )

        return DecoratedResultSet(distro_data, operator.itemgetter(0))


@implementer(ITranslationGroupSet)
class TranslationGroupSet:
    title = "Rosetta Translation Groups"

    def __iter__(self):
        """See `ITranslationGroupSet`."""
        # XXX Danilo 2009-08-25: See bug #418490: we should get
        # group names from their respective celebrities.  For now,
        # just hard-code them so they show up at the top of the
        # listing of all translation groups.
        yield from IStore(TranslationGroup).find(TranslationGroup).order_by(
            Desc(
                TranslationGroup.name.is_in(
                    ("launchpad-translators", "ubuntu-translators")
                )
            ),
            TranslationGroup.title,
        )

    def __getitem__(self, name):
        """See ITranslationGroupSet."""
        return self.getByName(name)

    def getByName(self, name):
        """See ITranslationGroupSet."""
        group = (
            IStore(TranslationGroup).find(TranslationGroup, name=name).one()
        )
        if group is None:
            raise NotFoundError(name)
        return group

    def _get(self):
        return IStore(TranslationGroup).find(TranslationGroup)

    def new(self, name, title, summary, translation_guide_url, owner):
        """See ITranslationGroupSet."""
        return TranslationGroup(
            name=name,
            title=title,
            summary=summary,
            translation_guide_url=translation_guide_url,
            owner=owner,
        )

    def getByPerson(self, person):
        """See `ITranslationGroupSet`."""
        store = Store.of(person)
        origin = [
            TranslationGroup,
            Join(
                Translator,
                Translator.translationgroup_id == TranslationGroup.id,
            ),
            Join(
                TeamParticipation,
                TeamParticipation.team_id == Translator.translator_id,
            ),
        ]
        result = store.using(*origin).find(
            TranslationGroup, TeamParticipation.person == person
        )

        return result.config(distinct=True).order_by(TranslationGroup.title)

    def getGroupsCount(self):
        """See ITranslationGroupSet."""
        return IStore(TranslationGroup).find(TranslationGroup).count()
