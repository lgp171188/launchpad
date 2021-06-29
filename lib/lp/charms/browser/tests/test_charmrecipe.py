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
from zope.publisher.interfaces import NotFound
from zope.security.interfaces import Unauthorized
from zope.security.proxy import removeSecurityProxy
from zope.testbrowser.browser import LinkNotFoundError

from lp.app.enums import InformationType
from lp.app.interfaces.launchpad import ILaunchpadCelebrities
from lp.buildmaster.enums import BuildStatus
from lp.buildmaster.interfaces.processor import IProcessorSet
from lp.charms.browser.charmrecipe import (
    CharmRecipeAdminView,
    CharmRecipeEditView,
    CharmRecipeView,
    )
from lp.charms.interfaces.charmrecipe import CHARM_RECIPE_ALLOW_CREATE
from lp.registry.enums import PersonVisibility
from lp.services.database.constants import UTC_NOW
from lp.services.features.testing import FeatureFixture
from lp.services.job.interfaces.job import JobStatus
from lp.services.propertycache import get_property_cache
from lp.services.webapp import canonical_url
from lp.services.webapp.servers import LaunchpadTestRequest
from lp.testing import (
    BrowserTestCase,
    login,
    login_admin,
    login_person,
    person_logged_in,
    TestCaseWithFactory,
    time_counter,
    )
from lp.testing.layers import (
    DatabaseFunctionalLayer,
    LaunchpadFunctionalLayer,
    )
from lp.testing.matchers import (
    MatchesPickerText,
    MatchesTagText,
    )
from lp.testing.pages import (
    extract_text,
    find_main_content,
    find_tags_by_class,
    find_tag_by_id,
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


class TestCharmRecipeAddView(BaseTestCharmRecipeView):

    def test_create_new_recipe_not_logged_in(self):
        [git_ref] = self.factory.makeGitRefs()
        self.assertRaises(
            Unauthorized, self.getViewBrowser, git_ref,
            view_name="+new-charm-recipe", no_login=True)

    def test_create_new_recipe_git(self):
        self.factory.makeProduct(
            name="test-project", displayname="Test Project")
        [git_ref] = self.factory.makeGitRefs(
            owner=self.person, target=self.person)
        source_display = git_ref.display_name
        browser = self.getViewBrowser(
            git_ref, view_name="+new-charm-recipe", user=self.person)
        browser.getControl(name="field.name").value = "charm-name"
        self.assertEqual("", browser.getControl(name="field.project").value)
        browser.getControl(name="field.project").value = "test-project"
        browser.getControl("Create charm recipe").click()

        content = find_main_content(browser.contents)
        self.assertEqual("charm-name", extract_text(content.h1))
        self.assertThat(
            "Test Person", MatchesPickerText(content, "edit-owner"))
        self.assertThat(
            "Project:\nTest Project\nEdit charm recipe",
            MatchesTagText(content, "project"))
        self.assertThat(
            "Source:\n%s\nEdit charm recipe" % source_display,
            MatchesTagText(content, "source"))
        self.assertThat(
            "Build schedule:\n(?)\nBuilt on request\nEdit charm recipe\n",
            MatchesTagText(content, "auto_build"))
        self.assertIsNone(find_tag_by_id(content, "auto_build_channels"))
        self.assertThat(
            "Builds of this charm recipe are not automatically uploaded to "
            "the store.\nEdit charm recipe",
            MatchesTagText(content, "store_upload"))

    def test_create_new_recipe_git_project_namespace(self):
        # If the Git repository is already in a project namespace, then that
        # project is the default for the new recipe.
        project = self.factory.makeProduct(
            name="test-project", displayname="Test Project")
        [git_ref] = self.factory.makeGitRefs(target=project)
        source_display = git_ref.display_name
        browser = self.getViewBrowser(
            git_ref, view_name="+new-charm-recipe", user=self.person)
        browser.getControl(name="field.name").value = "charm-name"
        self.assertEqual(
            "test-project", browser.getControl(name="field.project").value)
        browser.getControl("Create charm recipe").click()

        content = find_main_content(browser.contents)
        self.assertEqual("charm-name", extract_text(content.h1))
        self.assertThat(
            "Test Person", MatchesPickerText(content, "edit-owner"))
        self.assertThat(
            "Project:\nTest Project\nEdit charm recipe",
            MatchesTagText(content, "project"))
        self.assertThat(
            "Source:\n%s\nEdit charm recipe" % source_display,
            MatchesTagText(content, "source"))
        self.assertThat(
            "Build schedule:\n(?)\nBuilt on request\nEdit charm recipe\n",
            MatchesTagText(content, "auto_build"))
        self.assertIsNone(find_tag_by_id(content, "auto_build_channels"))
        self.assertThat(
            "Builds of this charm recipe are not automatically uploaded to "
            "the store.\nEdit charm recipe",
            MatchesTagText(content, "store_upload"))

    def test_create_new_recipe_project(self):
        project = self.factory.makeProduct(displayname="Test Project")
        [git_ref] = self.factory.makeGitRefs()
        source_display = git_ref.display_name
        browser = self.getViewBrowser(
            project, view_name="+new-charm-recipe", user=self.person)
        browser.getControl(name="field.name").value = "charm-name"
        browser.getControl(name="field.git_ref.repository").value = (
            git_ref.repository.shortened_path)
        browser.getControl(name="field.git_ref.path").value = git_ref.path
        browser.getControl("Create charm recipe").click()

        content = find_main_content(browser.contents)
        self.assertEqual("charm-name", extract_text(content.h1))
        self.assertThat(
            "Test Person", MatchesPickerText(content, "edit-owner"))
        self.assertThat(
            "Project:\nTest Project\nEdit charm recipe",
            MatchesTagText(content, "project"))
        self.assertThat(
            "Source:\n%s\nEdit charm recipe" % source_display,
            MatchesTagText(content, "source"))
        self.assertThat(
            "Build schedule:\n(?)\nBuilt on request\nEdit charm recipe\n",
            MatchesTagText(content, "auto_build"))
        self.assertIsNone(find_tag_by_id(content, "auto_build_channels"))
        self.assertThat(
            "Builds of this charm recipe are not automatically uploaded to "
            "the store.\nEdit charm recipe",
            MatchesTagText(content, "store_upload"))

    def test_create_new_recipe_users_teams_as_owner_options(self):
        # Teams that the user is in are options for the charm recipe owner.
        self.factory.makeTeam(
            name="test-team", displayname="Test Team", members=[self.person])
        [git_ref] = self.factory.makeGitRefs()
        browser = self.getViewBrowser(
            git_ref, view_name="+new-charm-recipe", user=self.person)
        options = browser.getControl("Owner").displayOptions
        self.assertEqual(
            ["Test Person (test-person)", "Test Team (test-team)"],
            sorted(str(option) for option in options))

    def test_create_new_recipe_auto_build(self):
        # Creating a new recipe and asking for it to be automatically built
        # sets all the appropriate fields.
        self.factory.makeProduct(
            name="test-project", displayname="Test Project")
        [git_ref] = self.factory.makeGitRefs()
        browser = self.getViewBrowser(
            git_ref, view_name="+new-charm-recipe", user=self.person)
        browser.getControl(name="field.name").value = "charm-name"
        browser.getControl(name="field.project").value = "test-project"
        browser.getControl(
            "Automatically build when branch changes").selected = True
        browser.getControl(
            name="field.auto_build_channels.charmcraft").value = "edge"
        browser.getControl(
            name="field.auto_build_channels.core").value = "stable"
        browser.getControl(
            name="field.auto_build_channels.core18").value = "beta"
        browser.getControl(
            name="field.auto_build_channels.core20").value = "edge/feature"
        browser.getControl("Create charm recipe").click()

        content = find_main_content(browser.contents)
        self.assertThat(
            "Build schedule:\n(?)\nBuilt automatically\nEdit charm recipe\n",
            MatchesTagText(content, "auto_build"))
        self.assertThat(
            "Source snap channels for automatic builds:\nEdit charm recipe\n"
            "charmcraft\nedge\ncore\nstable\ncore18\nbeta\n"
            "core20\nedge/feature\n",
            MatchesTagText(content, "auto_build_channels"))


class TestCharmRecipeAdminView(BaseTestCharmRecipeView):

    def test_unauthorized(self):
        # A non-admin user cannot administer a charm recipe.
        login_person(self.person)
        recipe = self.factory.makeCharmRecipe(registrant=self.person)
        recipe_url = canonical_url(recipe)
        browser = self.getViewBrowser(recipe, user=self.person)
        self.assertRaises(
            LinkNotFoundError, browser.getLink, "Administer charm recipe")
        self.assertRaises(
            Unauthorized, self.getUserBrowser, recipe_url + "/+admin",
            user=self.person)

    def test_admin_recipe(self):
        # Admins can change require_virtualized.
        login("admin@canonical.com")
        admin = self.factory.makePerson(
            member_of=[getUtility(ILaunchpadCelebrities).admin])
        login_person(self.person)
        recipe = self.factory.makeCharmRecipe(registrant=self.person)
        self.assertTrue(recipe.require_virtualized)

        browser = self.getViewBrowser(recipe, user=admin)
        browser.getLink("Administer charm recipe").click()
        browser.getControl("Require virtualized builders").selected = False
        browser.getControl("Update charm recipe").click()

        login_admin()
        self.assertFalse(recipe.require_virtualized)

    def test_admin_recipe_sets_date_last_modified(self):
        # Administering a charm recipe sets the date_last_modified property.
        login("admin@canonical.com")
        ppa_admin = self.factory.makePerson(
            member_of=[getUtility(ILaunchpadCelebrities).ppa_admin])
        login_person(self.person)
        date_created = datetime(2000, 1, 1, tzinfo=pytz.UTC)
        recipe = self.factory.makeCharmRecipe(
            registrant=self.person, date_created=date_created)
        login_person(ppa_admin)
        view = CharmRecipeAdminView(recipe, LaunchpadTestRequest())
        view.initialize()
        view.request_action.success({"require_virtualized": False})
        self.assertSqlAttributeEqualsDate(
            recipe, "date_last_modified", UTC_NOW)


class TestCharmRecipeEditView(BaseTestCharmRecipeView):

    def test_edit_recipe(self):
        [old_git_ref] = self.factory.makeGitRefs()
        recipe = self.factory.makeCharmRecipe(
            registrant=self.person, owner=self.person, git_ref=old_git_ref)
        self.factory.makeTeam(
            name="new-team", displayname="New Team", members=[self.person])
        [new_git_ref] = self.factory.makeGitRefs()

        browser = self.getViewBrowser(recipe, user=self.person)
        browser.getLink("Edit charm recipe").click()
        browser.getControl("Owner").value = ["new-team"]
        browser.getControl(name="field.name").value = "new-name"
        browser.getControl(name="field.git_ref.repository").value = (
            new_git_ref.repository.identity)
        browser.getControl(name="field.git_ref.path").value = new_git_ref.path
        browser.getControl(
            "Automatically build when branch changes").selected = True
        browser.getControl(
            name="field.auto_build_channels.charmcraft").value = "edge"
        browser.getControl("Update charm recipe").click()

        content = find_main_content(browser.contents)
        self.assertEqual("new-name", extract_text(content.h1))
        self.assertThat("New Team", MatchesPickerText(content, "edit-owner"))
        self.assertThat(
            "Source:\n%s\nEdit charm recipe" % new_git_ref.display_name,
            MatchesTagText(content, "source"))
        self.assertThat(
            "Build schedule:\n(?)\nBuilt automatically\nEdit charm recipe\n",
            MatchesTagText(content, "auto_build"))
        self.assertThat(
            "Source snap channels for automatic builds:\nEdit charm recipe\n"
            "charmcraft\nedge",
            MatchesTagText(content, "auto_build_channels"))
        self.assertThat(
            "Builds of this charm recipe are not automatically uploaded to "
            "the store.\nEdit charm recipe",
            MatchesTagText(content, "store_upload"))

    def test_edit_recipe_sets_date_last_modified(self):
        # Editing a charm recipe sets the date_last_modified property.
        date_created = datetime(2000, 1, 1, tzinfo=pytz.UTC)
        recipe = self.factory.makeCharmRecipe(
            registrant=self.person, date_created=date_created)
        with person_logged_in(self.person):
            view = CharmRecipeEditView(recipe, LaunchpadTestRequest())
            view.initialize()
            view.request_action.success({
                "owner": recipe.owner,
                "name": "changed",
                })
        self.assertSqlAttributeEqualsDate(
            recipe, "date_last_modified", UTC_NOW)

    def test_edit_recipe_already_exists(self):
        project = self.factory.makeProduct(displayname="Test Project")
        recipe = self.factory.makeCharmRecipe(
            registrant=self.person, project=project, owner=self.person,
            name="one")
        self.factory.makeCharmRecipe(
            registrant=self.person, project=project, owner=self.person,
            name="two")
        browser = self.getViewBrowser(recipe, user=self.person)
        browser.getLink("Edit charm recipe").click()
        browser.getControl(name="field.name").value = "two"
        browser.getControl("Update charm recipe").click()
        self.assertEqual(
            "There is already a charm recipe owned by Test Person in "
            "Test Project with this name.",
            extract_text(find_tags_by_class(browser.contents, "message")[1]))

    def test_edit_public_recipe_private_owner(self):
        login_person(self.person)
        recipe = self.factory.makeCharmRecipe(
            registrant=self.person, owner=self.person)
        private_team = self.factory.makeTeam(
            owner=self.person, visibility=PersonVisibility.PRIVATE)
        private_team_name = private_team.name
        browser = self.getViewBrowser(recipe, user=self.person)
        browser.getLink("Edit charm recipe").click()
        browser.getControl("Owner").value = [private_team_name]
        browser.getControl("Update charm recipe").click()
        self.assertEqual(
            "A public charm recipe cannot have a private owner.",
            extract_text(find_tags_by_class(browser.contents, "message")[1]))

    def test_edit_public_recipe_private_git_ref(self):
        login_person(self.person)
        recipe = self.factory.makeCharmRecipe(
            registrant=self.person, owner=self.person,
            git_ref=self.factory.makeGitRefs()[0])
        login_person(self.person)
        [private_ref] = self.factory.makeGitRefs(
            owner=self.person,
            information_type=InformationType.PRIVATESECURITY)
        private_ref_identity = private_ref.repository.identity
        private_ref_path = private_ref.path
        browser = self.getViewBrowser(recipe, user=self.person)
        browser.getLink("Edit charm recipe").click()
        browser.getControl(name="field.git_ref.repository").value = (
            private_ref_identity)
        browser.getControl(name="field.git_ref.path").value = private_ref_path
        browser.getControl("Update charm recipe").click()
        self.assertEqual(
            "A public charm recipe cannot have a private repository.",
            extract_text(find_tags_by_class(browser.contents, "message")[1]))


class TestCharmRecipeDeleteView(BaseTestCharmRecipeView):

    def test_unauthorized(self):
        # A user without edit access cannot delete a charm recipe.
        recipe = self.factory.makeCharmRecipe(
            registrant=self.person, owner=self.person)
        recipe_url = canonical_url(recipe)
        other_person = self.factory.makePerson()
        browser = self.getViewBrowser(recipe, user=other_person)
        self.assertRaises(
            LinkNotFoundError, browser.getLink, "Delete charm recipe")
        self.assertRaises(
            Unauthorized, self.getUserBrowser, recipe_url + "/+delete",
            user=other_person)

    def test_delete_recipe_without_builds(self):
        # A charm recipe without builds can be deleted.
        recipe = self.factory.makeCharmRecipe(
            registrant=self.person, owner=self.person)
        recipe_url = canonical_url(recipe)
        owner_url = canonical_url(self.person)
        browser = self.getViewBrowser(recipe, user=self.person)
        browser.getLink("Delete charm recipe").click()
        browser.getControl("Delete charm recipe").click()
        self.assertEqual(owner_url + "/+charm-recipes", browser.url)
        self.assertRaises(NotFound, browser.open, recipe_url)

    def test_delete_recipe_with_builds(self):
        # A charm recipe with builds can be deleted.
        recipe = self.factory.makeCharmRecipe(
            registrant=self.person, owner=self.person)
        build = self.factory.makeCharmRecipeBuild(recipe=recipe)
        self.factory.makeCharmFile(build=build)
        recipe_url = canonical_url(recipe)
        owner_url = canonical_url(self.person)
        browser = self.getViewBrowser(recipe, user=self.person)
        browser.getLink("Delete charm recipe").click()
        browser.getControl("Delete charm recipe").click()
        self.assertEqual(owner_url + "/+charm-recipes", browser.url)
        self.assertRaises(NotFound, browser.open, recipe_url)


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
