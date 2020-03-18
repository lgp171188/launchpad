# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test OCI recipe views."""

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
from zope.component import getUtility
from zope.publisher.interfaces import NotFound
from zope.security.interfaces import Unauthorized
from zope.testbrowser.browser import LinkNotFoundError

from lp.app.interfaces.launchpad import ILaunchpadCelebrities
from lp.buildmaster.enums import BuildStatus
from lp.buildmaster.interfaces.processor import IProcessorSet
from lp.oci.browser.ocirecipe import (
    OCIRecipeAdminView,
    OCIRecipeEditView,
    OCIRecipeView,
    )
from lp.services.database.constants import UTC_NOW
from lp.services.propertycache import get_property_cache
from lp.services.webapp import canonical_url
from lp.services.webapp.servers import LaunchpadTestRequest
from lp.testing import (
    BrowserTestCase,
    login,
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
    )
from lp.testing.publication import test_traverse
from lp.testing.views import create_view


class TestOCIRecipeNavigation(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_canonical_url(self):
        owner = self.factory.makePerson(name="person")
        distribution = self.factory.makeDistribution(name="distro")
        oci_project = self.factory.makeOCIProject(
            pillar=distribution, ociprojectname="oci-project")
        recipe = self.factory.makeOCIRecipe(
            name="recipe", registrant=owner, owner=owner,
            oci_project=oci_project)
        self.assertEqual(
            "http://launchpad.test/~person/distro/+oci/oci-project/"
            "+recipe/recipe", canonical_url(recipe))

    def test_recipe(self):
        recipe = self.factory.makeOCIRecipe()
        obj, _, _ = test_traverse(
            "http://launchpad.test/~%s/%s/+oci/%s/+recipe/%s" % (
                recipe.owner.name, recipe.oci_project.pillar.name,
                recipe.oci_project.name, recipe.name))
        self.assertEqual(recipe, obj)


class BaseTestOCIRecipeView(BrowserTestCase):

    layer = LaunchpadFunctionalLayer

    def setUp(self):
        super(BaseTestOCIRecipeView, self).setUp()
        self.useFixture(FakeLogger())
        self.person = self.factory.makePerson(
            name="test-person", displayname="Test Person")


class TestOCIRecipeAddView(BaseTestOCIRecipeView):

    def test_create_new_recipe_not_logged_in(self):
        oci_project = self.factory.makeOCIProject()
        self.assertRaises(
            Unauthorized, self.getViewBrowser, oci_project,
            view_name="+new-recipe", no_login=True)

    def test_create_new_recipe(self):
        oci_project = self.factory.makeOCIProject()
        oci_project_display = oci_project.display_name
        [git_ref] = self.factory.makeGitRefs()
        source_display = git_ref.display_name
        browser = self.getViewBrowser(
            oci_project, view_name="+new-recipe", user=self.person)
        browser.getControl(name="field.name").value = "recipe-name"
        browser.getControl("Description").value = "Recipe description"
        browser.getControl("Git repository").value = (
            git_ref.repository.identity)
        browser.getControl("Git branch").value = git_ref.path
        browser.getControl("Create OCI recipe").click()

        content = find_main_content(browser.contents)
        self.assertEqual("recipe-name", extract_text(content.h1))
        self.assertThat(
            "Recipe description",
            MatchesTagText(content, "recipe-description"))
        self.assertThat(
            "Test Person", MatchesPickerText(content, "edit-owner"))
        self.assertThat(
            "OCI project:\n%s" % oci_project_display,
            MatchesTagText(content, "oci-project"))
        self.assertThat(
            "Source:\n%s\nEdit OCI recipe" % source_display,
            MatchesTagText(content, "source"))
        self.assertThat(
            "Build file path:\nDockerfile\nEdit OCI recipe",
            MatchesTagText(content, "build-file"))
        self.assertThat(
            "Build schedule:\nBuilt on request\nEdit OCI recipe\n",
            MatchesTagText(content, "build-schedule"))

    def test_create_new_recipe_users_teams_as_owner_options(self):
        # Teams that the user is in are options for the OCI recipe owner.
        self.factory.makeTeam(
            name="test-team", displayname="Test Team", members=[self.person])
        oci_project = self.factory.makeOCIProject()
        browser = self.getViewBrowser(
            oci_project, view_name="+new-recipe", user=self.person)
        options = browser.getControl("Owner").displayOptions
        self.assertEqual(
            ["Test Person (test-person)", "Test Team (test-team)"],
            sorted(str(option) for option in options))


class TestOCIRecipeAdminView(BaseTestOCIRecipeView):

    def test_unauthorized(self):
        # A non-admin user cannot administer an OCI recipe.
        login_person(self.person)
        recipe = self.factory.makeOCIRecipe(registrant=self.person)
        recipe_url = canonical_url(recipe)
        browser = self.getViewBrowser(recipe, user=self.person)
        self.assertRaises(
            LinkNotFoundError, browser.getLink, "Administer OCI recipe")
        self.assertRaises(
            Unauthorized, self.getUserBrowser, recipe_url + "/+admin",
            user=self.person)

    def test_admin_recipe(self):
        # Admins can change require_virtualized.
        login("admin@canonical.com")
        commercial_admin = self.factory.makePerson(
            member_of=[getUtility(ILaunchpadCelebrities).commercial_admin])
        login_person(self.person)
        recipe = self.factory.makeOCIRecipe(registrant=self.person)
        self.assertTrue(recipe.require_virtualized)

        browser = self.getViewBrowser(recipe, user=commercial_admin)
        browser.getLink("Administer OCI recipe").click()
        browser.getControl("Require virtualized builders").selected = False
        browser.getControl("Update OCI recipe").click()

        login_person(self.person)
        self.assertFalse(recipe.require_virtualized)

    def test_admin_recipe_sets_date_last_modified(self):
        # Administering an OCI recipe sets the date_last_modified property.
        login("admin@canonical.com")
        ppa_admin = self.factory.makePerson(
            member_of=[getUtility(ILaunchpadCelebrities).ppa_admin])
        login_person(self.person)
        date_created = datetime(2000, 1, 1, tzinfo=pytz.UTC)
        recipe = self.factory.makeOCIRecipe(
            registrant=self.person, date_created=date_created)
        login_person(ppa_admin)
        view = OCIRecipeAdminView(recipe, LaunchpadTestRequest())
        view.initialize()
        view.request_action.success({"require_virtualized": False})
        self.assertSqlAttributeEqualsDate(
            recipe, "date_last_modified", UTC_NOW)


class TestOCIRecipeEditView(BaseTestOCIRecipeView):

    def test_edit_recipe(self):
        oci_project = self.factory.makeOCIProject()
        oci_project_display = oci_project.display_name
        [old_git_ref] = self.factory.makeGitRefs()
        recipe = self.factory.makeOCIRecipe(
            registrant=self.person, owner=self.person,
            oci_project=oci_project, git_ref=old_git_ref)
        self.factory.makeTeam(
            name="new-team", displayname="New Team", members=[self.person])
        [new_git_ref] = self.factory.makeGitRefs()

        browser = self.getViewBrowser(recipe, user=self.person)
        browser.getLink("Edit OCI recipe").click()
        browser.getControl("Owner").value = ["new-team"]
        browser.getControl(name="field.name").value = "new-name"
        browser.getControl("Description").value = "New description"
        browser.getControl("Git repository").value = (
            new_git_ref.repository.identity)
        browser.getControl("Git branch").value = new_git_ref.path
        browser.getControl("Build file path").value = "Dockerfile-2"
        browser.getControl("Build daily").selected = True
        browser.getControl("Update OCI recipe").click()

        content = find_main_content(browser.contents)
        self.assertEqual("new-name", extract_text(content.h1))
        self.assertThat("New Team", MatchesPickerText(content, "edit-owner"))
        self.assertThat(
            "OCI project:\n%s" % oci_project_display,
            MatchesTagText(content, "oci-project"))
        self.assertThat(
            "Source:\n%s\nEdit OCI recipe" % new_git_ref.display_name,
            MatchesTagText(content, "source"))
        self.assertThat(
            "Build file path:\nDockerfile-2\nEdit OCI recipe",
            MatchesTagText(content, "build-file"))
        self.assertThat(
            "Build schedule:\nBuilt daily\nEdit OCI recipe\n",
            MatchesTagText(content, "build-schedule"))

    def test_edit_recipe_sets_date_last_modified(self):
        # Editing an OCI recipe sets the date_last_modified property.
        date_created = datetime(2000, 1, 1, tzinfo=pytz.UTC)
        recipe = self.factory.makeOCIRecipe(
            registrant=self.person, date_created=date_created)
        with person_logged_in(self.person):
            view = OCIRecipeEditView(recipe, LaunchpadTestRequest())
            view.initialize()
            view.request_action.success({
                "owner": recipe.owner,
                "name": "changed",
                "description": "changed",
                })
        self.assertSqlAttributeEqualsDate(
            recipe, "date_last_modified", UTC_NOW)

    def test_edit_recipe_already_exists(self):
        oci_project = self.factory.makeOCIProject()
        oci_project_display = oci_project.display_name
        recipe = self.factory.makeOCIRecipe(
            registrant=self.person, owner=self.person,
            oci_project=oci_project, name="one")
        self.factory.makeOCIRecipe(
            registrant=self.person, owner=self.person,
            oci_project=oci_project, name="two")
        browser = self.getViewBrowser(recipe, user=self.person)
        browser.getLink("Edit OCI recipe").click()
        browser.getControl(name="field.name").value = "two"
        browser.getControl("Update OCI recipe").click()
        self.assertEqual(
            "There is already an OCI recipe owned by Test Person in %s with "
            "this name." % oci_project_display,
            extract_text(find_tags_by_class(browser.contents, "message")[1]))


class TestOCIRecipeDeleteView(BaseTestOCIRecipeView):

    def test_unauthorized(self):
        # A user without edit access cannot delete an OCI recipe.
        recipe = self.factory.makeOCIRecipe(
            registrant=self.person, owner=self.person)
        recipe_url = canonical_url(recipe)
        other_person = self.factory.makePerson()
        browser = self.getViewBrowser(recipe, user=other_person)
        self.assertRaises(
            LinkNotFoundError, browser.getLink, "Delete OCI recipe")
        self.assertRaises(
            Unauthorized, self.getUserBrowser, recipe_url + "/+delete",
            user=other_person)

    def test_delete_recipe_without_builds(self):
        # An OCI recipe without builds can be deleted.
        recipe = self.factory.makeOCIRecipe(
            registrant=self.person, owner=self.person)
        recipe_url = canonical_url(recipe)
        oci_project_url = canonical_url(recipe.oci_project)
        browser = self.getViewBrowser(recipe, user=self.person)
        browser.getLink("Delete OCI recipe").click()
        browser.getControl("Delete OCI recipe").click()
        self.assertEqual(oci_project_url, browser.url)
        self.assertRaises(NotFound, browser.open, recipe_url)

    def test_delete_recipe_with_builds(self):
        # An OCI recipe with builds can be deleted.
        recipe = self.factory.makeOCIRecipe(
            registrant=self.person, owner=self.person)
        self.factory.makeOCIRecipeBuild(recipe=recipe)
        # XXX cjwatson 2020-02-19: This should also add a file to the build
        # once that works.
        recipe_url = canonical_url(recipe)
        oci_project_url = canonical_url(recipe.oci_project)
        browser = self.getViewBrowser(recipe, user=self.person)
        browser.getLink("Delete OCI recipe").click()
        browser.getControl("Delete OCI recipe").click()
        self.assertEqual(oci_project_url, browser.url)
        self.assertRaises(NotFound, browser.open, recipe_url)


class TestOCIRecipeView(BaseTestOCIRecipeView):

    def setUp(self):
        super(TestOCIRecipeView, self).setUp()
        self.distroseries = self.factory.makeDistroSeries()
        processor = getUtility(IProcessorSet).getByName("386")
        self.distroarchseries = self.factory.makeDistroArchSeries(
            distroseries=self.distroseries, architecturetag="i386",
            processor=processor)
        self.factory.makeBuilder(virtualized=True)

    def makeOCIRecipe(self, oci_project=None, **kwargs):
        if oci_project is None:
            oci_project = self.factory.makeOCIProject(
                pillar=self.distroseries.distribution)
        return self.factory.makeOCIRecipe(
            registrant=self.person, owner=self.person, name="recipe-name",
            oci_project=oci_project, **kwargs)

    def makeBuild(self, recipe=None, date_created=None, **kwargs):
        if recipe is None:
            recipe = self.makeOCIRecipe()
        if date_created is None:
            date_created = datetime.now(pytz.UTC) - timedelta(hours=1)
        return self.factory.makeOCIRecipeBuild(
            requester=self.person, recipe=recipe,
            distro_arch_series=self.distroarchseries,
            date_created=date_created, **kwargs)

    def test_breadcrumb(self):
        oci_project = self.factory.makeOCIProject(
            pillar=self.distroseries.distribution)
        oci_project_name = oci_project.name
        oci_project_url = canonical_url(oci_project)
        recipe = self.makeOCIRecipe(oci_project=oci_project)
        view = create_view(recipe, "+index")
        # To test the breadcrumbs we need a correct traversal stack.
        view.request.traversed_objects = [self.person, recipe, view]
        view.initialize()
        breadcrumbs_tag = soupmatchers.Tag(
            "breadcrumbs", "ol", attrs={"class": "breadcrumbs"})
        self.assertThat(
            view(),
            soupmatchers.HTMLContains(
                soupmatchers.Within(
                    breadcrumbs_tag,
                    soupmatchers.Tag(
                        "OCI project breadcrumb", "a",
                        text="%s OCI project" % oci_project_name,
                        attrs={"href": oci_project_url})),
                soupmatchers.Within(
                    breadcrumbs_tag,
                    soupmatchers.Tag(
                        "OCI recipe breadcrumb", "li",
                        text=re.compile(r"\srecipe-name\s")))))

    def test_index(self):
        oci_project = self.factory.makeOCIProject(
            pillar=self.distroseries.distribution)
        oci_project_name = oci_project.name
        oci_project_display = oci_project.display_name
        [ref] = self.factory.makeGitRefs(
            owner=self.person, target=self.person, name="recipe-repository",
            paths=["refs/heads/master"])
        recipe = self.makeOCIRecipe(
            oci_project=oci_project, git_ref=ref, build_file="Dockerfile")
        build = self.makeBuild(
            recipe=recipe, status=BuildStatus.FULLYBUILT,
            duration=timedelta(minutes=30))
        self.assertTextMatchesExpressionIgnoreWhitespace("""\
            %s OCI project
            recipe-name
            .*
            OCI recipe information
            Owner: Test Person
            OCI project: %s
            Source: ~test-person/\\+git/recipe-repository:master
            Build file path: Dockerfile
            Build schedule: Built on request
            Latest builds
            Status When complete Architecture
            Successfully built 30 minutes ago 386
            """ % (oci_project_name, oci_project_display),
            self.getMainText(build.recipe))

    def test_index_success_with_buildlog(self):
        # The build log is shown if it is there.
        build = self.makeBuild(
            status=BuildStatus.FULLYBUILT, duration=timedelta(minutes=30))
        build.setLog(self.factory.makeLibraryFileAlias())
        self.assertTextMatchesExpressionIgnoreWhitespace("""\
            Latest builds
            Status When complete Architecture
            Successfully built 30 minutes ago buildlog \(.*\) 386
            """, self.getMainText(build.recipe))

    def test_index_no_builds(self):
        # A message is shown when there are no builds.
        recipe = self.factory.makeOCIRecipe()
        self.assertIn(
            "This OCI recipe has not been built yet.",
            self.getMainText(recipe))

    def test_index_pending_build(self):
        # A pending build is listed as such.
        build = self.makeBuild()
        build.queueBuild()
        self.assertTextMatchesExpressionIgnoreWhitespace("""\
            Latest builds
            Status When complete Architecture
            Needs building in .* \(estimated\) 386
            """, self.getMainText(build.recipe))

    def setStatus(self, build, status):
        build.updateStatus(
            BuildStatus.BUILDING, date_started=build.date_created)
        build.updateStatus(
            status, date_finished=build.date_started + timedelta(minutes=30))

    def test_builds(self):
        # OCIRecipeView.builds produces reasonable results.
        recipe = self.makeOCIRecipe()
        # Create oldest builds first so that they sort properly by id.
        date_gen = time_counter(
            datetime(2000, 1, 1, tzinfo=pytz.UTC), timedelta(days=1))
        builds = [
            self.makeBuild(recipe=recipe, date_created=next(date_gen))
            for i in range(11)]
        view = OCIRecipeView(recipe, None)
        self.assertEqual(list(reversed(builds)), view.builds)
        self.setStatus(builds[10], BuildStatus.FULLYBUILT)
        self.setStatus(builds[9], BuildStatus.FAILEDTOBUILD)
        del get_property_cache(view).builds
        # When there are >= 9 pending builds, only the most recent of any
        # completed builds is returned.
        self.assertEqual(
            list(reversed(builds[:9])) + [builds[10]], view.builds)
        for build in builds[:9]:
            self.setStatus(build, BuildStatus.FULLYBUILT)
        del get_property_cache(view).builds
        self.assertEqual(list(reversed(builds[1:])), view.builds)
