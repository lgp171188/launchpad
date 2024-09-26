# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test craft recipes."""

from testtools.matchers import (
    Equals,
    Is,
    MatchesDict,
    MatchesSetwise,
    MatchesStructure,
)
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.app.enums import InformationType
from lp.crafts.interfaces.craftrecipe import (
    CRAFT_RECIPE_ALLOW_CREATE,
    CraftRecipeBuildRequestStatus,
    CraftRecipeFeatureDisabled,
    CraftRecipePrivateFeatureDisabled,
    ICraftRecipe,
    ICraftRecipeSet,
    NoSourceForCraftRecipe,
)
from lp.crafts.interfaces.craftrecipejob import (
    ICraftRecipeRequestBuildsJobSource,
)
from lp.services.database.constants import ONE_DAY_AGO, UTC_NOW
from lp.services.database.interfaces import IStore
from lp.services.database.sqlbase import get_transaction_timestamp
from lp.services.features.testing import FeatureFixture
from lp.services.job.interfaces.job import JobStatus
from lp.services.webapp.snapshot import notify_modified
from lp.testing import TestCaseWithFactory, admin_logged_in, person_logged_in
from lp.testing.layers import DatabaseFunctionalLayer, LaunchpadZopelessLayer


class TestCraftRecipeFeatureFlags(TestCaseWithFactory):

    layer = LaunchpadZopelessLayer

    def test_feature_flag_disabled(self):
        # Without a feature flag, we will not create any craft recipes.
        self.assertRaises(
            CraftRecipeFeatureDisabled, self.factory.makeCraftRecipe
        )

    def test_private_feature_flag_disabled(self):
        # Without a private feature flag, we will not create new private
        # craft recipes.
        self.useFixture(FeatureFixture({CRAFT_RECIPE_ALLOW_CREATE: "on"}))
        self.assertRaises(
            CraftRecipePrivateFeatureDisabled,
            self.factory.makeCraftRecipe,
            information_type=InformationType.PROPRIETARY,
        )


class TestCraftRecipe(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.useFixture(FeatureFixture({CRAFT_RECIPE_ALLOW_CREATE: "on"}))

    def test_implements_interfaces(self):
        # CraftRecipe implements ICraftRecipe.
        recipe = self.factory.makeCraftRecipe()
        with admin_logged_in():
            self.assertProvides(recipe, ICraftRecipe)

    def test___repr__(self):
        # CraftRecipe objects have an informative __repr__.
        recipe = self.factory.makeCraftRecipe()
        self.assertEqual(
            "<CraftRecipe ~%s/%s/+craft/%s>"
            % (recipe.owner.name, recipe.project.name, recipe.name),
            repr(recipe),
        )

    def test_initial_date_last_modified(self):
        # The initial value of date_last_modified is date_created.
        recipe = self.factory.makeCraftRecipe(date_created=ONE_DAY_AGO)
        self.assertEqual(recipe.date_created, recipe.date_last_modified)

    def test_modifiedevent_sets_date_last_modified(self):
        # When a CraftRecipe receives an object modified event, the last
        # modified date is set to UTC_NOW.
        recipe = self.factory.makeCraftRecipe(date_created=ONE_DAY_AGO)
        with notify_modified(removeSecurityProxy(recipe), ["name"]):
            pass
        self.assertSqlAttributeEqualsDate(
            recipe, "date_last_modified", UTC_NOW
        )

    def test_delete_without_builds(self):
        # A craft recipe with no builds can be deleted.
        owner = self.factory.makePerson()
        project = self.factory.makeProduct()
        recipe = self.factory.makeCraftRecipe(
            registrant=owner, owner=owner, project=project, name="condemned"
        )
        self.assertIsNotNone(
            getUtility(ICraftRecipeSet).getByName(owner, project, "condemned")
        )
        with person_logged_in(recipe.owner):
            recipe.destroySelf()
        self.assertIsNone(
            getUtility(ICraftRecipeSet).getByName(owner, project, "condemned")
        )

    def test_requestBuilds(self):
        # requestBuilds schedules a job and returns a corresponding
        # CraftRecipeBuildRequest.
        recipe = self.factory.makeCraftRecipe()
        now = get_transaction_timestamp(IStore(recipe))
        with person_logged_in(recipe.owner.teamowner):
            request = recipe.requestBuilds(recipe.owner.teamowner)
        self.assertThat(
            request,
            MatchesStructure(
                date_requested=Equals(now),
                date_finished=Is(None),
                recipe=Equals(recipe),
                status=Equals(CraftRecipeBuildRequestStatus.PENDING),
                error_message=Is(None),
                channels=Is(None),
                architectures=Is(None),
            ),
        )
        [job] = getUtility(ICraftRecipeRequestBuildsJobSource).iterReady()
        self.assertThat(
            job,
            MatchesStructure(
                job_id=Equals(request.id),
                job=MatchesStructure.byEquality(status=JobStatus.WAITING),
                recipe=Equals(recipe),
                requester=Equals(recipe.owner.teamowner),
                channels=Is(None),
                architectures=Is(None),
            ),
        )

    def test_requestBuilds_with_channels(self):
        # If asked to build using particular snap channels, requestBuilds
        # passes those through to the job.
        recipe = self.factory.makeCraftRecipe()
        now = get_transaction_timestamp(IStore(recipe))
        with person_logged_in(recipe.owner.teamowner):
            request = recipe.requestBuilds(
                recipe.owner.teamowner, channels={"craftcraft": "edge"}
            )
        self.assertThat(
            request,
            MatchesStructure(
                date_requested=Equals(now),
                date_finished=Is(None),
                recipe=Equals(recipe),
                status=Equals(CraftRecipeBuildRequestStatus.PENDING),
                error_message=Is(None),
                channels=MatchesDict({"craftcraft": Equals("edge")}),
                architectures=Is(None),
            ),
        )
        [job] = getUtility(ICraftRecipeRequestBuildsJobSource).iterReady()
        self.assertThat(
            job,
            MatchesStructure(
                job_id=Equals(request.id),
                job=MatchesStructure.byEquality(status=JobStatus.WAITING),
                recipe=Equals(recipe),
                requester=Equals(recipe.owner.teamowner),
                channels=Equals({"craftcraft": "edge"}),
                architectures=Is(None),
            ),
        )

    def test_requestBuilds_with_architectures(self):
        # If asked to build for particular architectures, requestBuilds
        # passes those through to the job.
        recipe = self.factory.makeCraftRecipe()
        now = get_transaction_timestamp(IStore(recipe))
        with person_logged_in(recipe.owner.teamowner):
            request = recipe.requestBuilds(
                recipe.owner.teamowner, architectures={"amd64", "i386"}
            )
        self.assertThat(
            request,
            MatchesStructure(
                date_requested=Equals(now),
                date_finished=Is(None),
                recipe=Equals(recipe),
                status=Equals(CraftRecipeBuildRequestStatus.PENDING),
                error_message=Is(None),
                channels=Is(None),
                architectures=MatchesSetwise(Equals("amd64"), Equals("i386")),
            ),
        )
        [job] = getUtility(ICraftRecipeRequestBuildsJobSource).iterReady()
        self.assertThat(
            job,
            MatchesStructure(
                job_id=Equals(request.id),
                job=MatchesStructure.byEquality(status=JobStatus.WAITING),
                recipe=Equals(recipe),
                requester=Equals(recipe.owner.teamowner),
                channels=Is(None),
                architectures=MatchesSetwise(Equals("amd64"), Equals("i386")),
            ),
        )


class TestCraftRecipeSet(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.useFixture(FeatureFixture({CRAFT_RECIPE_ALLOW_CREATE: "on"}))

    def test_class_implements_interfaces(self):
        # The CraftRecipeSet class implements ICraftRecipeSet.
        self.assertProvides(getUtility(ICraftRecipeSet), ICraftRecipeSet)

    def makeCraftRecipeComponents(self, git_ref=None):
        """Return a dict of values that can be used to make a craft recipe.

        Suggested use: provide as kwargs to ICraftRecipeSet.new.

        :param git_ref: An `IGitRef`, or None.
        """
        registrant = self.factory.makePerson()
        components = {
            "registrant": registrant,
            "owner": self.factory.makeTeam(owner=registrant),
            "project": self.factory.makeProduct(),
            "name": self.factory.getUniqueUnicode("craft-name"),
        }
        if git_ref is None:
            git_ref = self.factory.makeGitRefs()[0]
        components["git_ref"] = git_ref
        return components

    def test_creation_git(self):
        # The metadata entries supplied when a craft recipe is created for a
        # Git branch are present on the new object.
        [ref] = self.factory.makeGitRefs()
        components = self.makeCraftRecipeComponents(git_ref=ref)
        recipe = getUtility(ICraftRecipeSet).new(**components)
        self.assertEqual(components["registrant"], recipe.registrant)
        self.assertEqual(components["owner"], recipe.owner)
        self.assertEqual(components["project"], recipe.project)
        self.assertEqual(components["name"], recipe.name)
        self.assertEqual(ref.repository, recipe.git_repository)
        self.assertEqual(ref.path, recipe.git_path)
        self.assertEqual(ref, recipe.git_ref)
        self.assertIsNone(recipe.build_path)
        self.assertFalse(recipe.auto_build)
        self.assertIsNone(recipe.auto_build_channels)
        self.assertTrue(recipe.require_virtualized)
        self.assertFalse(recipe.private)
        self.assertFalse(recipe.store_upload)
        self.assertIsNone(recipe.store_name)
        self.assertIsNone(recipe.store_secrets)
        self.assertEqual([], recipe.store_channels)

    def test_creation_no_source(self):
        # Attempting to create a craft recipe without a Git repository
        # fails.
        registrant = self.factory.makePerson()
        self.assertRaises(
            NoSourceForCraftRecipe,
            getUtility(ICraftRecipeSet).new,
            registrant,
            registrant,
            self.factory.makeProduct(),
            self.factory.getUniqueUnicode("craft-name"),
        )

    def test_getByName(self):
        owner = self.factory.makePerson()
        project = self.factory.makeProduct()
        project_recipe = self.factory.makeCraftRecipe(
            registrant=owner, owner=owner, project=project, name="proj-craft"
        )
        self.factory.makeCraftRecipe(
            registrant=owner, owner=owner, name="proj-craft"
        )

        self.assertEqual(
            project_recipe,
            getUtility(ICraftRecipeSet).getByName(
                owner, project, "proj-craft"
            ),
        )

    def test_findByGitRepository(self):
        # ICraftRecipeSet.findByGitRepository returns all craft recipes with
        # the given Git repository.
        repositories = [self.factory.makeGitRepository() for i in range(2)]
        recipes = []
        for repository in repositories:
            for _ in range(2):
                [ref] = self.factory.makeGitRefs(repository=repository)
                recipes.append(self.factory.makeCraftRecipe(git_ref=ref))
        recipe_set = getUtility(ICraftRecipeSet)
        self.assertContentEqual(
            recipes[:2], recipe_set.findByGitRepository(repositories[0])
        )
        self.assertContentEqual(
            recipes[2:], recipe_set.findByGitRepository(repositories[1])
        )

    def test_findByGitRepository_paths(self):
        # ICraftRecipeSet.findByGitRepository can restrict by reference
        # paths.
        repositories = [self.factory.makeGitRepository() for i in range(2)]
        recipes = []
        for repository in repositories:
            for _ in range(3):
                [ref] = self.factory.makeGitRefs(repository=repository)
                recipes.append(self.factory.makeCraftRecipe(git_ref=ref))
        recipe_set = getUtility(ICraftRecipeSet)
        self.assertContentEqual(
            [], recipe_set.findByGitRepository(repositories[0], paths=[])
        )
        self.assertContentEqual(
            [recipes[0]],
            recipe_set.findByGitRepository(
                repositories[0], paths=[recipes[0].git_ref.path]
            ),
        )
        self.assertContentEqual(
            recipes[:2],
            recipe_set.findByGitRepository(
                repositories[0],
                paths=[recipes[0].git_ref.path, recipes[1].git_ref.path],
            ),
        )

    def test_findByOwner(self):
        # ICraftRecipeSet.findByOwner returns all craft recipes with the
        # given owner.
        owners = [self.factory.makePerson() for i in range(2)]
        recipes = []
        for owner in owners:
            for _ in range(2):
                recipes.append(
                    self.factory.makeCraftRecipe(registrant=owner, owner=owner)
                )
        recipe_set = getUtility(ICraftRecipeSet)
        self.assertContentEqual(recipes[:2], recipe_set.findByOwner(owners[0]))
        self.assertContentEqual(recipes[2:], recipe_set.findByOwner(owners[1]))

    def test_detachFromGitRepository(self):
        # ICraftRecipeSet.detachFromGitRepository clears the given Git
        # repository from all craft recipes.
        repositories = [self.factory.makeGitRepository() for i in range(2)]
        recipes = []
        paths = []
        refs = []
        for repository in repositories:
            for _ in range(2):
                [ref] = self.factory.makeGitRefs(repository=repository)
                paths.append(ref.path)
                refs.append(ref)
                recipes.append(
                    self.factory.makeCraftRecipe(
                        git_ref=ref, date_created=ONE_DAY_AGO
                    )
                )
        getUtility(ICraftRecipeSet).detachFromGitRepository(repositories[0])
        self.assertEqual(
            [None, None, repositories[1], repositories[1]],
            [recipe.git_repository for recipe in recipes],
        )
        self.assertEqual(
            [None, None, paths[2], paths[3]],
            [recipe.git_path for recipe in recipes],
        )
        self.assertEqual(
            [None, None, refs[2], refs[3]],
            [recipe.git_ref for recipe in recipes],
        )
        for recipe in recipes[:2]:
            self.assertSqlAttributeEqualsDate(
                recipe, "date_last_modified", UTC_NOW
            )
