# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test charm recipe listings."""

from datetime import datetime, timedelta, timezone
from functools import partial

import soupmatchers
from testtools.matchers import MatchesAll, Not
from zope.security.proxy import removeSecurityProxy

from lp.charms.interfaces.charmrecipe import CHARM_RECIPE_ALLOW_CREATE
from lp.code.tests.helpers import GitHostingFixture
from lp.services.database.constants import ONE_DAY_AGO, UTC_NOW
from lp.services.features.testing import MemoryFeatureFixture
from lp.services.webapp import canonical_url
from lp.testing import (
    ANONYMOUS,
    BrowserTestCase,
    login,
    person_logged_in,
    record_two_runs,
)
from lp.testing.layers import LaunchpadFunctionalLayer
from lp.testing.matchers import HasQueryCount
from lp.testing.views import create_initialized_view


class TestCharmRecipeListing(BrowserTestCase):
    layer = LaunchpadFunctionalLayer

    def assertCharmRecipesLink(
        self, context, link_text, link_has_context=False, **kwargs
    ):
        if link_has_context:
            expected_href = canonical_url(context, view_name="+charm-recipes")
        else:
            expected_href = "+charm-recipes"
        matcher = soupmatchers.HTMLContains(
            soupmatchers.Tag(
                "View charm recipes link",
                "a",
                text=link_text,
                attrs={"href": expected_href},
            )
        )
        self.assertThat(self.getViewBrowser(context).contents, Not(matcher))
        login(ANONYMOUS)
        with MemoryFeatureFixture({CHARM_RECIPE_ALLOW_CREATE: "on"}):
            self.factory.makeCharmRecipe(**kwargs)
            self.factory.makeCharmRecipe(**kwargs)
        self.assertThat(self.getViewBrowser(context).contents, matcher)

    def test_git_repository_links_to_recipes(self):
        repository = self.factory.makeGitRepository()
        [ref] = self.factory.makeGitRefs(repository=repository)
        self.assertCharmRecipesLink(repository, "2 charm recipes", git_ref=ref)

    def test_git_ref_links_to_recipes(self):
        self.useFixture(GitHostingFixture())
        [ref] = self.factory.makeGitRefs()
        self.assertCharmRecipesLink(ref, "2 charm recipes", git_ref=ref)

    def test_person_links_to_recipes(self):
        person = self.factory.makePerson()
        self.assertCharmRecipesLink(
            person,
            "View charm recipes",
            link_has_context=True,
            registrant=person,
            owner=person,
        )

    def test_project_links_to_recipes(self):
        project = self.factory.makeProduct()
        [ref] = self.factory.makeGitRefs(target=project)
        self.assertCharmRecipesLink(
            project, "View charm recipes", link_has_context=True, git_ref=ref
        )

    def test_git_repository_recipe_listing(self):
        # We can see charm recipes for a Git repository.
        repository = self.factory.makeGitRepository()
        [ref] = self.factory.makeGitRefs(repository=repository)
        with MemoryFeatureFixture({CHARM_RECIPE_ALLOW_CREATE: "on"}):
            self.factory.makeCharmRecipe(git_ref=ref)
        text = self.getMainText(repository, "+charm-recipes")
        self.assertTextMatchesExpressionIgnoreWhitespace(
            """
            Charm recipes for lp:~.*
            Name            Owner           Registered
            charm-name.*    Team Name.*     .*""",
            text,
        )

    def test_git_ref_recipe_listing(self):
        # We can see charm recipes for a Git reference.
        [ref] = self.factory.makeGitRefs()
        with MemoryFeatureFixture({CHARM_RECIPE_ALLOW_CREATE: "on"}):
            self.factory.makeCharmRecipe(git_ref=ref)
        text = self.getMainText(ref, "+charm-recipes")
        self.assertTextMatchesExpressionIgnoreWhitespace(
            """
            Charm recipes for ~.*:.*
            Name            Owner           Registered
            charm-name.*    Team Name.*     .*""",
            text,
        )

    def test_person_recipe_listing(self):
        # We can see charm recipes for a person.
        owner = self.factory.makePerson(displayname="Charm Owner")
        [ref] = self.factory.makeGitRefs()
        with MemoryFeatureFixture({CHARM_RECIPE_ALLOW_CREATE: "on"}):
            self.factory.makeCharmRecipe(
                registrant=owner,
                owner=owner,
                git_ref=ref,
                date_created=ONE_DAY_AGO,
            )
        text = self.getMainText(owner, "+charm-recipes")
        self.assertTextMatchesExpressionIgnoreWhitespace(
            """
            Charm recipes for Charm Owner
            Name            Source                  Registered
            charm-name.*    ~.*:.*                  .*""",
            text,
        )

    def test_project_recipe_listing(self):
        # We can see charm recipes for a project.
        project = self.factory.makeProduct(displayname="Charmable")
        [ref] = self.factory.makeGitRefs(target=project)
        with MemoryFeatureFixture({CHARM_RECIPE_ALLOW_CREATE: "on"}):
            self.factory.makeCharmRecipe(git_ref=ref, date_created=UTC_NOW)
        text = self.getMainText(project, "+charm-recipes")
        self.assertTextMatchesExpressionIgnoreWhitespace(
            """
            Charm recipes for Charmable
            Name            Owner           Source          Registered
            charm-name.*    Team Name.*     ~.*:.*          .*""",
            text,
        )

    def assertCharmRecipesQueryCount(self, context, item_creator):
        self.pushConfig("launchpad", default_batch_size=10)
        recorder1, recorder2 = record_two_runs(
            lambda: self.getMainText(context, "+charm-recipes"),
            item_creator,
            5,
        )
        self.assertThat(recorder2, HasQueryCount.byEquality(recorder1))

    def test_git_repository_query_count(self):
        # The number of queries required to render the list of all charm
        # recipes for a Git repository is constant in the number of owners
        # and charm recipes.
        person = self.factory.makePerson()
        repository = self.factory.makeGitRepository(owner=person)

        def create_recipe():
            with person_logged_in(person):
                [ref] = self.factory.makeGitRefs(repository=repository)
                with MemoryFeatureFixture({CHARM_RECIPE_ALLOW_CREATE: "on"}):
                    self.factory.makeCharmRecipe(git_ref=ref)

        self.assertCharmRecipesQueryCount(repository, create_recipe)

    def test_git_ref_query_count(self):
        # The number of queries required to render the list of all charm
        # recipes for a Git reference is constant in the number of owners
        # and charm recipes.
        person = self.factory.makePerson()
        [ref] = self.factory.makeGitRefs(owner=person)

        def create_recipe():
            with person_logged_in(person):
                with MemoryFeatureFixture({CHARM_RECIPE_ALLOW_CREATE: "on"}):
                    self.factory.makeCharmRecipe(git_ref=ref)

        self.assertCharmRecipesQueryCount(ref, create_recipe)

    def test_person_query_count(self):
        # The number of queries required to render the list of all charm
        # recipes for a person is constant in the number of projects,
        # sources, and charm recipes.
        person = self.factory.makePerson()

        def create_recipe():
            with person_logged_in(person):
                project = self.factory.makeProduct()
                [ref] = self.factory.makeGitRefs(owner=person, target=project)
                with MemoryFeatureFixture({CHARM_RECIPE_ALLOW_CREATE: "on"}):
                    self.factory.makeCharmRecipe(git_ref=ref)

        self.assertCharmRecipesQueryCount(person, create_recipe)

    def test_project_query_count(self):
        # The number of queries required to render the list of all charm
        # recipes for a person is constant in the number of owners, sources,
        # and charm recipes.
        person = self.factory.makePerson()
        project = self.factory.makeProduct(owner=person)

        def create_recipe():
            with person_logged_in(person):
                [ref] = self.factory.makeGitRefs(target=project)
                with MemoryFeatureFixture({CHARM_RECIPE_ALLOW_CREATE: "on"}):
                    self.factory.makeCharmRecipe(git_ref=ref)

        self.assertCharmRecipesQueryCount(project, create_recipe)

    def makeCharmRecipesAndMatchers(self, create_recipe, count, start_time):
        with MemoryFeatureFixture({CHARM_RECIPE_ALLOW_CREATE: "on"}):
            recipes = [create_recipe() for i in range(count)]
        for i, recipe in enumerate(recipes):
            removeSecurityProxy(
                recipe
            ).date_last_modified = start_time - timedelta(seconds=i)
        return [
            soupmatchers.Tag(
                "charm recipe link",
                "a",
                text=recipe.name,
                attrs={
                    "href": canonical_url(recipe, path_only_if_possible=True)
                },
            )
            for recipe in recipes
        ]

    def assertBatches(self, context, link_matchers, batched, start, size):
        view = create_initialized_view(context, "+charm-recipes")
        listing_tag = soupmatchers.Tag(
            "charm recipe listing",
            "table",
            attrs={"class": "listing sortable"},
        )
        batch_nav_tag = soupmatchers.Tag(
            "batch nav links", "td", attrs={"class": "batch-navigation-links"}
        )
        present_links = ([batch_nav_tag] if batched else []) + [
            matcher
            for i, matcher in enumerate(link_matchers)
            if i in range(start, start + size)
        ]
        absent_links = ([] if batched else [batch_nav_tag]) + [
            matcher
            for i, matcher in enumerate(link_matchers)
            if i not in range(start, start + size)
        ]
        self.assertThat(
            view.render(),
            MatchesAll(
                soupmatchers.HTMLContains(listing_tag, *present_links),
                Not(soupmatchers.HTMLContains(*absent_links)),
            ),
        )

    def test_git_repository_batches_recipes(self):
        repository = self.factory.makeGitRepository()
        [ref] = self.factory.makeGitRefs(repository=repository)
        create_recipe = partial(self.factory.makeCharmRecipe, git_ref=ref)
        now = datetime.now(timezone.utc)
        link_matchers = self.makeCharmRecipesAndMatchers(create_recipe, 3, now)
        self.assertBatches(repository, link_matchers, False, 0, 3)
        link_matchers.extend(
            self.makeCharmRecipesAndMatchers(
                create_recipe, 7, now - timedelta(seconds=3)
            )
        )
        self.assertBatches(repository, link_matchers, True, 0, 5)

    def test_git_ref_batches_recipes(self):
        [ref] = self.factory.makeGitRefs()
        create_recipe = partial(self.factory.makeCharmRecipe, git_ref=ref)
        now = datetime.now(timezone.utc)
        link_matchers = self.makeCharmRecipesAndMatchers(create_recipe, 3, now)
        self.assertBatches(ref, link_matchers, False, 0, 3)
        link_matchers.extend(
            self.makeCharmRecipesAndMatchers(
                create_recipe, 7, now - timedelta(seconds=3)
            )
        )
        self.assertBatches(ref, link_matchers, True, 0, 5)

    def test_person_batches_recipes(self):
        owner = self.factory.makePerson()
        create_recipe = partial(
            self.factory.makeCharmRecipe, registrant=owner, owner=owner
        )
        now = datetime.now(timezone.utc)
        link_matchers = self.makeCharmRecipesAndMatchers(create_recipe, 3, now)
        self.assertBatches(owner, link_matchers, False, 0, 3)
        link_matchers.extend(
            self.makeCharmRecipesAndMatchers(
                create_recipe, 7, now - timedelta(seconds=3)
            )
        )
        self.assertBatches(owner, link_matchers, True, 0, 5)

    def test_project_batches_recipes(self):
        project = self.factory.makeProduct()
        [ref] = self.factory.makeGitRefs(target=project)
        create_recipe = partial(self.factory.makeCharmRecipe, git_ref=ref)
        now = datetime.now(timezone.utc)
        link_matchers = self.makeCharmRecipesAndMatchers(create_recipe, 3, now)
        self.assertBatches(project, link_matchers, False, 0, 3)
        link_matchers.extend(
            self.makeCharmRecipesAndMatchers(
                create_recipe, 7, now - timedelta(seconds=3)
            )
        )
        self.assertBatches(project, link_matchers, True, 0, 5)
