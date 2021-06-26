# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test charm recipe views."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type

from datetime import (
    datetime,
    timedelta,
    )
import re

from fixtures import FakeLogger
import pytz
import soupmatchers
from testtools.matchers import (
    Equals,
    MatchesListwise,
    MatchesStructure,
    )
import transaction
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.app.interfaces.launchpad import ILaunchpadCelebrities
from lp.buildmaster.enums import BuildStatus
from lp.buildmaster.interfaces.processor import IProcessorSet
from lp.charms.browser.charmrecipe import CharmRecipeView
from lp.charms.interfaces.charmrecipe import CHARM_RECIPE_ALLOW_CREATE
from lp.services.features.testing import FeatureFixture
from lp.services.job.interfaces.job import JobStatus
from lp.services.propertycache import get_property_cache
from lp.services.webapp import canonical_url
from lp.testing import (
    BrowserTestCase,
    person_logged_in,
    TestCaseWithFactory,
    time_counter,
    )
from lp.testing.layers import (
    DatabaseFunctionalLayer,
    LaunchpadFunctionalLayer,
    )
from lp.testing.publication import test_traverse
from lp.testing.views import (
    create_initialized_view,
    create_view,
    )


class TestCharmRecipeNavigation(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestCharmRecipeNavigation, self).setUp()
        self.useFixture(FeatureFixture({CHARM_RECIPE_ALLOW_CREATE: "on"}))

    def test_canonical_url(self):
        owner = self.factory.makePerson(name="person")
        project = self.factory.makeProduct(name="project")
        recipe = self.factory.makeCharmRecipe(
            registrant=owner, owner=owner, project=project, name="charm")
        self.assertEqual(
            "http://launchpad.test/~person/project/+charm/charm",
            canonical_url(recipe))

    def test_charm_recipe(self):
        recipe = self.factory.makeCharmRecipe()
        obj, _, _ = test_traverse(
            "http://launchpad.test/~%s/%s/+charm/%s" % (
                recipe.owner.name, recipe.project.name, recipe.name))
        self.assertEqual(recipe, obj)


class BaseTestCharmRecipeView(BrowserTestCase):

    layer = LaunchpadFunctionalLayer

    def setUp(self):
        super(BaseTestCharmRecipeView, self).setUp()
        self.useFixture(FeatureFixture({CHARM_RECIPE_ALLOW_CREATE: "on"}))
        self.useFixture(FakeLogger())
        self.person = self.factory.makePerson(
            name="test-person", displayname="Test Person")


class TestCharmRecipeView(BaseTestCharmRecipeView):

    def setUp(self):
        super(TestCharmRecipeView, self).setUp()
        self.project = self.factory.makeProduct(
            name="test-project", displayname="Test Project")
        self.ubuntu = getUtility(ILaunchpadCelebrities).ubuntu
        self.distroseries = self.factory.makeDistroSeries(
            distribution=self.ubuntu)
        processor = getUtility(IProcessorSet).getByName("386")
        self.distroarchseries = self.factory.makeDistroArchSeries(
            distroseries=self.distroseries, architecturetag="i386",
            processor=processor)
        self.factory.makeBuilder(virtualized=True)

    def makeCharmRecipe(self, **kwargs):
        if "project" not in kwargs:
            kwargs["project"] = self.project
        if "git_ref" not in kwargs:
            kwargs["git_ref"] = self.factory.makeGitRefs()[0]
        return self.factory.makeCharmRecipe(
            registrant=self.person, owner=self.person, name="charm-name",
            **kwargs)

    def makeBuild(self, recipe=None, date_created=None, **kwargs):
        if recipe is None:
            recipe = self.makeCharmRecipe()
        if date_created is None:
            date_created = datetime.now(pytz.UTC) - timedelta(hours=1)
        build = self.factory.makeCharmRecipeBuild(
            requester=self.person, recipe=recipe,
            distro_arch_series=self.distroarchseries,
            date_created=date_created, **kwargs)
        job = removeSecurityProxy(
            removeSecurityProxy(build.build_request)._job)
        job.job._status = JobStatus.COMPLETED
        return build

    def test_breadcrumb(self):
        recipe = self.makeCharmRecipe()
        view = create_view(recipe, "+index")
        # To test the breadcrumbs we need a correct traversal stack.
        view.request.traversed_objects = [
            recipe.owner, recipe.project, recipe, view]
        view.initialize()
        breadcrumbs_tag = soupmatchers.Tag(
            "breadcrumbs", "ol", attrs={"class": "breadcrumbs"})
        self.assertThat(
            view(),
            soupmatchers.HTMLContains(
                soupmatchers.Within(
                    breadcrumbs_tag,
                    soupmatchers.Tag(
                        "project breadcrumb", "a",
                        text="Test Project",
                        attrs={"href": re.compile(r"/test-project$")})),
                soupmatchers.Within(
                    breadcrumbs_tag,
                    soupmatchers.Tag(
                        "charm breadcrumb", "li",
                        text=re.compile(r"\scharm-name\s")))))

    def test_index_git(self):
        [ref] = self.factory.makeGitRefs(
            owner=self.person, target=self.project, name="charm-repository",
            paths=["refs/heads/master"])
        recipe = self.makeCharmRecipe(git_ref=ref)
        build = self.makeBuild(
            recipe=recipe, status=BuildStatus.FULLYBUILT,
            duration=timedelta(minutes=30))
        self.assertTextMatchesExpressionIgnoreWhitespace(r"""\
            Test Project
            charm-name
            .*
            Charm recipe information
            Owner: Test Person
            Project: Test Project
            Source: ~test-person/test-project/\+git/charm-repository:master
            Build schedule: \(\?\)
            Built on request
            Builds of this charm recipe are not automatically uploaded to
            the store.
            Latest builds
            Status When complete Architecture
            Successfully built 30 minutes ago i386
            """, self.getMainText(build.recipe))

    def test_index_success_with_buildlog(self):
        # The build log is shown if it is there.
        build = self.makeBuild(
            status=BuildStatus.FULLYBUILT, duration=timedelta(minutes=30))
        build.setLog(self.factory.makeLibraryFileAlias())
        self.assertTextMatchesExpressionIgnoreWhitespace(r"""\
            Latest builds
            Status When complete Architecture
            Successfully built 30 minutes ago buildlog \(.*\) i386
            """, self.getMainText(build.recipe))

    def test_index_no_builds(self):
        # A message is shown when there are no builds.
        recipe = self.makeCharmRecipe()
        self.assertIn(
            "This charm recipe has not been built yet.",
            self.getMainText(recipe))

    def test_index_pending_build(self):
        # A pending build is listed as such.
        build = self.makeBuild()
        build.queueBuild()
        self.assertTextMatchesExpressionIgnoreWhitespace(r"""\
            Latest builds
            Status When complete Architecture
            Needs building in .* \(estimated\) i386
            """, self.getMainText(build.recipe))

    def test_index_pending_build_request(self):
        # A pending build request is listed as such.
        recipe = self.makeCharmRecipe()
        with person_logged_in(recipe.owner):
            recipe.requestBuilds(recipe.owner)
        self.assertTextMatchesExpressionIgnoreWhitespace("""\
            Latest builds
            Status When complete Architecture
            Pending build request
            """, self.getMainText(recipe))

    def test_index_failed_build_request(self):
        # A failed build request is listed as such, with its error message.
        recipe = self.makeCharmRecipe()
        with person_logged_in(recipe.owner):
            request = recipe.requestBuilds(recipe.owner)
        job = removeSecurityProxy(removeSecurityProxy(request)._job)
        job.job._status = JobStatus.FAILED
        job.job.date_finished = datetime.now(pytz.UTC) - timedelta(hours=1)
        job.error_message = "Boom"
        self.assertTextMatchesExpressionIgnoreWhitespace(r"""\
            Latest builds
            Status When complete Architecture
            Failed build request 1 hour ago \(Boom\)
            """, self.getMainText(recipe))

    def setStatus(self, build, status):
        build.updateStatus(
            BuildStatus.BUILDING, date_started=build.date_created)
        build.updateStatus(
            status, date_finished=build.date_started + timedelta(minutes=30))

    def test_builds_and_requests(self):
        # CharmRecipeView.builds_and_requests produces reasonable results,
        # interleaving build requests with builds.
        recipe = self.makeCharmRecipe()
        # Create oldest builds first so that they sort properly by id.
        date_gen = time_counter(
            datetime(2000, 1, 1, tzinfo=pytz.UTC), timedelta(days=1))
        builds = [
            self.makeBuild(recipe=recipe, date_created=next(date_gen))
            for i in range(3)]
        self.setStatus(builds[2], BuildStatus.FULLYBUILT)
        with person_logged_in(recipe.owner):
            request = recipe.requestBuilds(recipe.owner)
        job = removeSecurityProxy(removeSecurityProxy(request)._job)
        job.job.date_created = next(date_gen)
        view = CharmRecipeView(recipe, None)
        # The pending build request is interleaved in date order with
        # pending builds, and these are followed by completed builds.
        self.assertThat(view.builds_and_requests, MatchesListwise([
            MatchesStructure.byEquality(id=request.id),
            Equals(builds[1]),
            Equals(builds[0]),
            Equals(builds[2]),
            ]))
        transaction.commit()
        builds.append(self.makeBuild(recipe=recipe))
        del get_property_cache(view).builds_and_requests
        self.assertThat(view.builds_and_requests, MatchesListwise([
            Equals(builds[3]),
            MatchesStructure.byEquality(id=request.id),
            Equals(builds[1]),
            Equals(builds[0]),
            Equals(builds[2]),
            ]))
        # If we pretend that the job failed, it is still listed, but after
        # any pending builds.
        job.job._status = JobStatus.FAILED
        job.job.date_finished = job.date_created + timedelta(minutes=30)
        del get_property_cache(view).builds_and_requests
        self.assertThat(view.builds_and_requests, MatchesListwise([
            Equals(builds[3]),
            Equals(builds[1]),
            Equals(builds[0]),
            MatchesStructure.byEquality(id=request.id),
            Equals(builds[2]),
            ]))

    def test_store_channels_empty(self):
        recipe = self.factory.makeCharmRecipe()
        view = create_initialized_view(recipe, "+index")
        self.assertEqual("", view.store_channels)

    def test_store_channels_display(self):
        recipe = self.factory.makeCharmRecipe(
            store_channels=["track/stable/fix-123", "track/edge/fix-123"])
        view = create_initialized_view(recipe, "+index")
        self.assertEqual(
            "track/stable/fix-123, track/edge/fix-123", view.store_channels)
