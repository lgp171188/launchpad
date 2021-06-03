# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test charm recipes."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type

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
from lp.charms.interfaces.charmrecipe import (
    CHARM_RECIPE_ALLOW_CREATE,
    CHARM_RECIPE_BUILD_DISTRIBUTION,
    CharmRecipeBuildRequestStatus,
    CharmRecipeFeatureDisabled,
    CharmRecipePrivateFeatureDisabled,
    ICharmRecipe,
    ICharmRecipeSet,
    NoSourceForCharmRecipe,
    )
from lp.charms.interfaces.charmrecipejob import (
    ICharmRecipeRequestBuildsJobSource,
    )
from lp.registry.interfaces.series import SeriesStatus
from lp.services.database.constants import (
    ONE_DAY_AGO,
    UTC_NOW,
    )
from lp.services.database.interfaces import IStore
from lp.services.database.sqlbase import get_transaction_timestamp
from lp.services.features.testing import FeatureFixture
from lp.services.job.interfaces.job import JobStatus
from lp.services.webapp.snapshot import notify_modified
from lp.testing import (
    admin_logged_in,
    person_logged_in,
    TestCaseWithFactory,
    )
from lp.testing.layers import (
    DatabaseFunctionalLayer,
    LaunchpadZopelessLayer,
    )


class TestCharmRecipeFeatureFlags(TestCaseWithFactory):

    layer = LaunchpadZopelessLayer

    def test_feature_flag_disabled(self):
        # Without a feature flag, we wil not create any charm recipes.
        self.assertRaises(
            CharmRecipeFeatureDisabled, self.factory.makeCharmRecipe)

    def test_private_feature_flag_disabled(self):
        # Without a private feature flag, we wil not create new private
        # charm recipes.
        self.useFixture(FeatureFixture({CHARM_RECIPE_ALLOW_CREATE: "on"}))
        self.assertRaises(
            CharmRecipePrivateFeatureDisabled, self.factory.makeCharmRecipe,
            information_type=InformationType.PROPRIETARY)


class TestCharmRecipe(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestCharmRecipe, self).setUp()
        self.useFixture(FeatureFixture({CHARM_RECIPE_ALLOW_CREATE: "on"}))

    def test_implements_interfaces(self):
        # CharmRecipe implements ICharmRecipe.
        recipe = self.factory.makeCharmRecipe()
        with admin_logged_in():
            self.assertProvides(recipe, ICharmRecipe)

    def test___repr__(self):
        # CharmRecipe objects have an informative __repr__.
        recipe = self.factory.makeCharmRecipe()
        self.assertEqual(
            "<CharmRecipe ~%s/%s/+charm/%s>" % (
                recipe.owner.name, recipe.project.name, recipe.name),
            repr(recipe))

    def test_initial_date_last_modified(self):
        # The initial value of date_last_modified is date_created.
        recipe = self.factory.makeCharmRecipe(date_created=ONE_DAY_AGO)
        self.assertEqual(recipe.date_created, recipe.date_last_modified)

    def test_modifiedevent_sets_date_last_modified(self):
        # When a CharmRecipe receives an object modified event, the last
        # modified date is set to UTC_NOW.
        recipe = self.factory.makeCharmRecipe(date_created=ONE_DAY_AGO)
        with notify_modified(removeSecurityProxy(recipe), ["name"]):
            pass
        self.assertSqlAttributeEqualsDate(
            recipe, "date_last_modified", UTC_NOW)

    def test__default_distribution_default(self):
        # If the CHARM_RECIPE_BUILD_DISTRIBUTION feature rule is not set, we
        # default to Ubuntu.
        recipe = self.factory.makeCharmRecipe()
        self.assertEqual(
            "ubuntu", removeSecurityProxy(recipe)._default_distribution.name)

    def test__default_distribution_feature_rule(self):
        # If the CHARM_RECIPE_BUILD_DISTRIBUTION feature rule is set, we
        # default to the distribution with the given name.
        distro_name = "mydistro"
        distribution = self.factory.makeDistribution(name=distro_name)
        recipe = self.factory.makeCharmRecipe()
        with FeatureFixture({CHARM_RECIPE_BUILD_DISTRIBUTION: distro_name}):
            self.assertEqual(
                distribution,
                removeSecurityProxy(recipe)._default_distribution)

    def test__default_distribution_feature_rule_nonexistent(self):
        # If we mistakenly set the rule to a non-existent distribution,
        # things break explicitly.
        recipe = self.factory.makeCharmRecipe()
        with FeatureFixture({CHARM_RECIPE_BUILD_DISTRIBUTION: "nonexistent"}):
            expected_msg = (
                "'nonexistent' is not a valid value for feature rule '%s'" %
                CHARM_RECIPE_BUILD_DISTRIBUTION)
            self.assertRaisesWithContent(
                ValueError, expected_msg,
                getattr, removeSecurityProxy(recipe), "_default_distribution")

    def test__default_distro_series_feature_rule(self):
        # If the appropriate per-distribution feature rule is set, we
        # default to the named distro series.
        distro_name = "mydistro"
        distribution = self.factory.makeDistribution(name=distro_name)
        distro_series_name = "myseries"
        distro_series = self.factory.makeDistroSeries(
            distribution=distribution, name=distro_series_name)
        self.factory.makeDistroSeries(distribution=distribution)
        recipe = self.factory.makeCharmRecipe()
        with FeatureFixture({
                CHARM_RECIPE_BUILD_DISTRIBUTION: distro_name,
                "charm.default_build_series.%s" % distro_name: (
                    distro_series_name),
                }):
            self.assertEqual(
                distro_series,
                removeSecurityProxy(recipe)._default_distro_series)

    def test__default_distro_series_no_feature_rule(self):
        # If the appropriate per-distribution feature rule is not set, we
        # default to the distribution's current series.
        distro_name = "mydistro"
        distribution = self.factory.makeDistribution(name=distro_name)
        self.factory.makeDistroSeries(
            distribution=distribution, status=SeriesStatus.SUPPORTED)
        current_series = self.factory.makeDistroSeries(
            distribution=distribution, status=SeriesStatus.DEVELOPMENT)
        recipe = self.factory.makeCharmRecipe()
        with FeatureFixture({CHARM_RECIPE_BUILD_DISTRIBUTION: distro_name}):
            self.assertEqual(
                current_series,
                removeSecurityProxy(recipe)._default_distro_series)

    def test_requestBuilds(self):
        # requestBuilds schedules a job and returns a corresponding
        # CharmRecipeBuildRequest.
        recipe = self.factory.makeCharmRecipe()
        now = get_transaction_timestamp(IStore(recipe))
        with person_logged_in(recipe.owner.teamowner):
            request = recipe.requestBuilds(recipe.owner.teamowner)
        self.assertThat(request, MatchesStructure(
            date_requested=Equals(now),
            date_finished=Is(None),
            recipe=Equals(recipe),
            status=Equals(CharmRecipeBuildRequestStatus.PENDING),
            error_message=Is(None),
            channels=Is(None),
            architectures=Is(None)))
        [job] = getUtility(ICharmRecipeRequestBuildsJobSource).iterReady()
        self.assertThat(job, MatchesStructure(
            job_id=Equals(request.id),
            job=MatchesStructure.byEquality(status=JobStatus.WAITING),
            recipe=Equals(recipe),
            requester=Equals(recipe.owner.teamowner),
            channels=Is(None),
            architectures=Is(None)))

    def test_requestBuilds_with_channels(self):
        # If asked to build using particular snap channels, requestBuilds
        # passes those through to the job.
        recipe = self.factory.makeCharmRecipe()
        now = get_transaction_timestamp(IStore(recipe))
        with person_logged_in(recipe.owner.teamowner):
            request = recipe.requestBuilds(
                recipe.owner.teamowner, channels={"charmcraft": "edge"})
        self.assertThat(request, MatchesStructure(
            date_requested=Equals(now),
            date_finished=Is(None),
            recipe=Equals(recipe),
            status=Equals(CharmRecipeBuildRequestStatus.PENDING),
            error_message=Is(None),
            channels=MatchesDict({"charmcraft": Equals("edge")}),
            architectures=Is(None)))
        [job] = getUtility(ICharmRecipeRequestBuildsJobSource).iterReady()
        self.assertThat(job, MatchesStructure(
            job_id=Equals(request.id),
            job=MatchesStructure.byEquality(status=JobStatus.WAITING),
            recipe=Equals(recipe),
            requester=Equals(recipe.owner.teamowner),
            channels=Equals({"charmcraft": "edge"}),
            architectures=Is(None)))

    def test_requestBuilds_with_architectures(self):
        # If asked to build for particular architectures, requestBuilds
        # passes those through to the job.
        recipe = self.factory.makeCharmRecipe()
        now = get_transaction_timestamp(IStore(recipe))
        with person_logged_in(recipe.owner.teamowner):
            request = recipe.requestBuilds(
                recipe.owner.teamowner, architectures={"amd64", "i386"})
        self.assertThat(request, MatchesStructure(
            date_requested=Equals(now),
            date_finished=Is(None),
            recipe=Equals(recipe),
            status=Equals(CharmRecipeBuildRequestStatus.PENDING),
            error_message=Is(None),
            channels=Is(None),
            architectures=MatchesSetwise(Equals("amd64"), Equals("i386"))))
        [job] = getUtility(ICharmRecipeRequestBuildsJobSource).iterReady()
        self.assertThat(job, MatchesStructure(
            job_id=Equals(request.id),
            job=MatchesStructure.byEquality(status=JobStatus.WAITING),
            recipe=Equals(recipe),
            requester=Equals(recipe.owner.teamowner),
            channels=Is(None),
            architectures=MatchesSetwise(Equals("amd64"), Equals("i386"))))

    def test_delete_without_builds(self):
        # A charm recipe with no builds can be deleted.
        owner = self.factory.makePerson()
        project = self.factory.makeProduct()
        recipe = self.factory.makeCharmRecipe(
            registrant=owner, owner=owner, project=project, name="condemned")
        self.assertIsNotNone(
            getUtility(ICharmRecipeSet).getByName(owner, project, "condemned"))
        with person_logged_in(recipe.owner):
            recipe.destroySelf()
        self.assertIsNone(
            getUtility(ICharmRecipeSet).getByName(owner, project, "condemned"))


class TestCharmRecipeSet(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestCharmRecipeSet, self).setUp()
        self.useFixture(FeatureFixture({CHARM_RECIPE_ALLOW_CREATE: "on"}))

    def test_class_implements_interfaces(self):
        # The CharmRecipeSet class implements ICharmRecipeSet.
        self.assertProvides(getUtility(ICharmRecipeSet), ICharmRecipeSet)

    def makeCharmRecipeComponents(self, git_ref=None):
        """Return a dict of values that can be used to make a charm recipe.

        Suggested use: provide as kwargs to ICharmRecipeSet.new.

        :param git_ref: An `IGitRef`, or None.
        """
        registrant = self.factory.makePerson()
        components = {
            "registrant": registrant,
            "owner": self.factory.makeTeam(owner=registrant),
            "project": self.factory.makeProduct(),
            "name": self.factory.getUniqueUnicode("charm-name"),
            }
        if git_ref is None:
            git_ref = self.factory.makeGitRefs()[0]
        components["git_ref"] = git_ref
        return components

    def test_creation_git(self):
        # The metadata entries supplied when a charm recipe is created for a
        # Git branch are present on the new object.
        [ref] = self.factory.makeGitRefs()
        components = self.makeCharmRecipeComponents(git_ref=ref)
        recipe = getUtility(ICharmRecipeSet).new(**components)
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
        # Attempting to create a charm recipe without a Git repository
        # fails.
        registrant = self.factory.makePerson()
        self.assertRaises(
            NoSourceForCharmRecipe, getUtility(ICharmRecipeSet).new,
            registrant, registrant, self.factory.makeProduct(),
            self.factory.getUniqueUnicode("charm-name"))

    def test_getByName(self):
        owner = self.factory.makePerson()
        project = self.factory.makeProduct()
        project_recipe = self.factory.makeCharmRecipe(
            registrant=owner, owner=owner, project=project, name="proj-charm")
        self.factory.makeCharmRecipe(
            registrant=owner, owner=owner, name="proj-charm")

        self.assertEqual(
            project_recipe,
            getUtility(ICharmRecipeSet).getByName(
                owner, project, "proj-charm"))

    def test_findByGitRepository(self):
        # ICharmRecipeSet.findByGitRepository returns all charm recipes with
        # the given Git repository.
        repositories = [self.factory.makeGitRepository() for i in range(2)]
        recipes = []
        for repository in repositories:
            for i in range(2):
                [ref] = self.factory.makeGitRefs(repository=repository)
                recipes.append(self.factory.makeCharmRecipe(git_ref=ref))
        recipe_set = getUtility(ICharmRecipeSet)
        self.assertContentEqual(
            recipes[:2], recipe_set.findByGitRepository(repositories[0]))
        self.assertContentEqual(
            recipes[2:], recipe_set.findByGitRepository(repositories[1]))

    def test_findByGitRepository_paths(self):
        # ICharmRecipeSet.findByGitRepository can restrict by reference
        # paths.
        repositories = [self.factory.makeGitRepository() for i in range(2)]
        recipes = []
        for repository in repositories:
            for i in range(3):
                [ref] = self.factory.makeGitRefs(repository=repository)
                recipes.append(self.factory.makeCharmRecipe(git_ref=ref))
        recipe_set = getUtility(ICharmRecipeSet)
        self.assertContentEqual(
            [], recipe_set.findByGitRepository(repositories[0], paths=[]))
        self.assertContentEqual(
            [recipes[0]],
            recipe_set.findByGitRepository(
                repositories[0], paths=[recipes[0].git_ref.path]))
        self.assertContentEqual(
            recipes[:2],
            recipe_set.findByGitRepository(
                repositories[0],
                paths=[recipes[0].git_ref.path, recipes[1].git_ref.path]))

    def test_detachFromGitRepository(self):
        # ICharmRecipeSet.detachFromGitRepository clears the given Git
        # repository from all charm recipes.
        repositories = [self.factory.makeGitRepository() for i in range(2)]
        recipes = []
        paths = []
        refs = []
        for repository in repositories:
            for i in range(2):
                [ref] = self.factory.makeGitRefs(repository=repository)
                paths.append(ref.path)
                refs.append(ref)
                recipes.append(self.factory.makeCharmRecipe(
                    git_ref=ref, date_created=ONE_DAY_AGO))
        getUtility(ICharmRecipeSet).detachFromGitRepository(repositories[0])
        self.assertEqual(
            [None, None, repositories[1], repositories[1]],
            [recipe.git_repository for recipe in recipes])
        self.assertEqual(
            [None, None, paths[2], paths[3]],
            [recipe.git_path for recipe in recipes])
        self.assertEqual(
            [None, None, refs[2], refs[3]],
            [recipe.git_ref for recipe in recipes])
        for recipe in recipes[:2]:
            self.assertSqlAttributeEqualsDate(
                recipe, "date_last_modified", UTC_NOW)
