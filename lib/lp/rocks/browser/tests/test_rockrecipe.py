# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test rock recipe views."""

import re
from datetime import datetime, timedelta, timezone

import soupmatchers
import transaction
from fixtures import FakeLogger
from testtools.matchers import Equals, MatchesListwise, MatchesStructure
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.app.interfaces.launchpad import ILaunchpadCelebrities
from lp.buildmaster.enums import BuildStatus
from lp.buildmaster.interfaces.processor import IProcessorSet
from lp.rocks.browser.rockrecipe import RockRecipeView
from lp.rocks.interfaces.rockrecipe import ROCK_RECIPE_ALLOW_CREATE
from lp.services.features.testing import FeatureFixture
from lp.services.job.interfaces.job import JobStatus
from lp.services.propertycache import get_property_cache
from lp.services.webapp import canonical_url
from lp.testing import (
    BrowserTestCase,
    TestCaseWithFactory,
    person_logged_in,
    time_counter,
)
from lp.testing.layers import DatabaseFunctionalLayer, LaunchpadFunctionalLayer
from lp.testing.publication import test_traverse
from lp.testing.views import create_initialized_view, create_view


class TestRockRecipeNavigation(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.useFixture(FeatureFixture({ROCK_RECIPE_ALLOW_CREATE: "on"}))

    def test_canonical_url(self):
        owner = self.factory.makePerson(name="person")
        project = self.factory.makeProduct(name="project")
        recipe = self.factory.makeRockRecipe(
            registrant=owner, owner=owner, project=project, name="rock"
        )
        self.assertEqual(
            "http://launchpad.test/~person/project/+rock/rock",
            canonical_url(recipe),
        )

    def test_rock_recipe(self):
        recipe = self.factory.makeRockRecipe()
        obj, _, _ = test_traverse(
            "http://launchpad.test/~%s/%s/+rock/%s"
            % (recipe.owner.name, recipe.project.name, recipe.name)
        )
        self.assertEqual(recipe, obj)


class BaseTestRockRecipeView(BrowserTestCase):

    layer = LaunchpadFunctionalLayer

    def setUp(self):
        super().setUp()
        self.useFixture(FeatureFixture({ROCK_RECIPE_ALLOW_CREATE: "on"}))
        self.useFixture(FakeLogger())
        self.person = self.factory.makePerson(
            name="test-person", displayname="Test Person"
        )


class TestRockRecipeView(BaseTestRockRecipeView):

    def setUp(self):
        super().setUp()
        self.project = self.factory.makeProduct(
            name="test-project", displayname="Test Project"
        )
        self.ubuntu = getUtility(ILaunchpadCelebrities).ubuntu
        self.distroseries = self.factory.makeDistroSeries(
            distribution=self.ubuntu
        )
        processor = getUtility(IProcessorSet).getByName("386")
        self.distroarchseries = self.factory.makeDistroArchSeries(
            distroseries=self.distroseries,
            architecturetag="i386",
            processor=processor,
        )
        self.factory.makeBuilder(virtualized=True)

    def makeRockRecipe(self, **kwargs):
        if "project" not in kwargs:
            kwargs["project"] = self.project
        if "git_ref" not in kwargs:
            kwargs["git_ref"] = self.factory.makeGitRefs()[0]
        return self.factory.makeRockRecipe(
            registrant=self.person,
            owner=self.person,
            name="rock-name",
            **kwargs,
        )

    def makeBuild(self, recipe=None, date_created=None, **kwargs):
        if recipe is None:
            recipe = self.makeRockRecipe()
        if date_created is None:
            datetime.now(timezone.utc) - timedelta(hours=1)
        build = self.factory.makeRockRecipeBuild(
            requester=self.person,
            recipe=recipe,
            distro_arch_series=self.distroarchseries,
            date_created=date_created,
            **kwargs,
        )
        job = removeSecurityProxy(
            removeSecurityProxy(build.build_request)._job
        )
        job.job._status = JobStatus.COMPLETED
        return build

    def test_breadcrumb(self):
        recipe = self.makeRockRecipe()
        view = create_view(recipe, "+index")
        # To test the breadcrumbs we need a correct traversal stack.
        view.request.traversed_objects = [
            recipe.owner,
            recipe.project,
            recipe,
            view,
        ]
        view.initialize()
        breadcrumbs_tag = soupmatchers.Tag(
            "breadcrumbs", "ol", attrs={"class": "breadcrumbs"}
        )
        self.assertThat(
            view(),
            soupmatchers.HTMLContains(
                soupmatchers.Within(
                    breadcrumbs_tag,
                    soupmatchers.Tag(
                        "project breadcrumb",
                        "a",
                        text="Test Project",
                        attrs={"href": re.compile(r"/test-project$")},
                    ),
                ),
                soupmatchers.Within(
                    breadcrumbs_tag,
                    soupmatchers.Tag(
                        "rock breadcrumb",
                        "li",
                        text=re.compile(r"\srock-name\s"),
                    ),
                ),
            ),
        )

    def test_index_git(self):
        [ref] = self.factory.makeGitRefs(
            owner=self.person,
            target=self.project,
            name="rock-repository",
            paths=["refs/heads/master"],
        )
        recipe = self.makeRockRecipe(git_ref=ref)
        build = self.makeBuild(
            recipe=recipe,
            status=BuildStatus.FULLYBUILT,
            duration=timedelta(minutes=30),
        )
        self.assertTextMatchesExpressionIgnoreWhitespace(
            r"""\
            Test Project
            rock-name
            .*
            Rock recipe information
            Owner: Test Person
            Project: Test Project
            Source: ~test-person/test-project/\+git/rock-repository:master
            Build schedule: \(\?\)
            Built on request
            Builds of this rock recipe are not automatically uploaded to
            the store.
            Latest builds
            Status When complete Architecture
            Successfully built 30 minutes ago i386
            """,
            self.getMainText(build.recipe),
        )

    def test_index_success_with_buildlog(self):
        # The build log is shown if it is there.
        build = self.makeBuild(
            status=BuildStatus.FULLYBUILT, duration=timedelta(minutes=30)
        )
        build.setLog(self.factory.makeLibraryFileAlias())
        self.assertTextMatchesExpressionIgnoreWhitespace(
            r"""\
            Latest builds
            Status When complete Architecture
            Successfully built 30 minutes ago buildlog \(.*\) i386
            """,
            self.getMainText(build.recipe),
        )

    def test_index_no_builds(self):
        # A message is shown when there are no builds.
        recipe = self.makeRockRecipe()
        self.assertIn(
            "This rock recipe has not been built yet.",
            self.getMainText(recipe),
        )

    def test_index_pending_build(self):
        # A pending build is listed as such.
        build = self.makeBuild()
        build.queueBuild()
        self.assertTextMatchesExpressionIgnoreWhitespace(
            r"""\
            Latest builds
            Status When complete Architecture
            Needs building in .* \(estimated\) i386
            """,
            self.getMainText(build.recipe),
        )

    def test_index_pending_build_request(self):
        # A pending build request is listed as such.
        recipe = self.makeRockRecipe()
        with person_logged_in(recipe.owner):
            recipe.requestBuilds(recipe.owner)
        self.assertTextMatchesExpressionIgnoreWhitespace(
            """\
            Latest builds
            Status When complete Architecture
            Pending build request
            """,
            self.getMainText(recipe),
        )

    def test_index_failed_build_request(self):
        # A failed build request is listed as such, with its error message.
        recipe = self.makeRockRecipe()
        with person_logged_in(recipe.owner):
            request = recipe.requestBuilds(recipe.owner)
        job = removeSecurityProxy(removeSecurityProxy(request)._job)
        job.job._status = JobStatus.FAILED
        job.job.date_finished = datetime.now(timezone.utc) - timedelta(hours=1)
        job.error_message = "Boom"
        self.assertTextMatchesExpressionIgnoreWhitespace(
            r"""\
            Latest builds
            Status When complete Architecture
            Failed build request 1 hour ago \(Boom\)
            """,
            self.getMainText(recipe),
        )

    def setStatus(self, build, status):
        build.updateStatus(
            BuildStatus.BUILDING, date_started=build.date_created
        )
        build.updateStatus(
            status, date_finished=build.date_started + timedelta(minutes=30)
        )

    def test_builds_and_requests(self):
        # RockRecipeView.builds_and_requests produces reasonable results,
        # interleaving build requests with builds.
        recipe = self.makeRockRecipe()
        # Create oldest builds first so that they sort properly by id.
        date_gen = time_counter(
            datetime(2000, 1, 1, tzinfo=timezone.utc), timedelta(days=1)
        )
        builds = [
            self.makeBuild(recipe=recipe, date_created=next(date_gen))
            for i in range(3)
        ]
        self.setStatus(builds[2], BuildStatus.FULLYBUILT)
        with person_logged_in(recipe.owner):
            request = recipe.requestBuilds(recipe.owner)
        job = removeSecurityProxy(removeSecurityProxy(request)._job)
        job.job.date_created = next(date_gen)
        view = RockRecipeView(recipe, None)
        # The pending build request is interleaved in date order with
        # pending builds, and these are followed by completed builds.
        self.assertThat(
            view.builds_and_requests,
            MatchesListwise(
                [
                    MatchesStructure.byEquality(id=request.id),
                    Equals(builds[1]),
                    Equals(builds[0]),
                    Equals(builds[2]),
                ]
            ),
        )
        transaction.commit()
        builds.append(self.makeBuild(recipe=recipe))
        del get_property_cache(view).builds_and_requests
        self.assertThat(
            view.builds_and_requests,
            MatchesListwise(
                [
                    Equals(builds[3]),
                    MatchesStructure.byEquality(id=request.id),
                    Equals(builds[1]),
                    Equals(builds[0]),
                    Equals(builds[2]),
                ]
            ),
        )
        # If we pretend that the job failed, it is still listed, but after
        # any pending builds.
        job.job._status = JobStatus.FAILED
        job.job.date_finished = job.date_created + timedelta(minutes=30)
        del get_property_cache(view).builds_and_requests
        self.assertThat(
            view.builds_and_requests,
            MatchesListwise(
                [
                    Equals(builds[3]),
                    Equals(builds[1]),
                    Equals(builds[0]),
                    MatchesStructure.byEquality(id=request.id),
                    Equals(builds[2]),
                ]
            ),
        )

    def test_store_channels_empty(self):
        recipe = self.factory.makeRockRecipe()
        view = create_initialized_view(recipe, "+index")
        self.assertEqual("", view.store_channels)

    def test_store_channels_display(self):
        recipe = self.factory.makeRockRecipe(
            store_channels=["track/stable/fix-123", "track/edge/fix-123"]
        )
        view = create_initialized_view(recipe, "+index")
        self.assertEqual(
            "track/stable/fix-123, track/edge/fix-123", view.store_channels
        )
