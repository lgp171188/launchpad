# -*- coding: utf-8 -*-
# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test OCI recipe views."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type

from datetime import (
    datetime,
    timedelta,
    )
from operator import attrgetter
import re

from fixtures import FakeLogger
import pytz
import soupmatchers
from testtools.matchers import (
    MatchesSetwise,
    MatchesStructure,
    )
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
from lp.oci.interfaces.ocipushrule import IOCIPushRuleSet
from lp.oci.interfaces.ocirecipe import (
    CannotModifyOCIRecipeProcessor,
    IOCIRecipeSet,
    OCI_RECIPE_ALLOW_CREATE,
    )
from lp.oci.interfaces.ociregistrycredentials import (
    IOCIRegistryCredentialsSet,
    )
from lp.oci.tests.helpers import OCIConfigHelperMixin
from lp.registry.interfaces.person import IPersonSet
from lp.services.database.constants import UTC_NOW
from lp.services.features.testing import FeatureFixture
from lp.services.propertycache import get_property_cache
from lp.services.webapp import canonical_url
from lp.services.webapp.servers import LaunchpadTestRequest
from lp.testing import (
    anonymous_logged_in,
    BrowserTestCase,
    login,
    login_person,
    person_logged_in,
    record_two_runs,
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
from lp.testing.views import (
    create_initialized_view,
    create_view,
    )


class TestOCIRecipeNavigation(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestOCIRecipeNavigation, self).setUp()
        self.useFixture(FeatureFixture({OCI_RECIPE_ALLOW_CREATE: 'on'}))

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

    def test_recipe_traverse_distribution(self):
        # Make sure we can reach recipe of distro-based OCI projects.
        distro = self.factory.makeDistribution()
        oci_project = self.factory.makeOCIProject(pillar=distro)
        recipe = self.factory.makeOCIRecipe(oci_project=oci_project)
        obj, _, _ = test_traverse(
            "http://launchpad.test/~%s/%s/+oci/%s/+recipe/%s" % (
                recipe.owner.name, recipe.oci_project.pillar.name,
                recipe.oci_project.name, recipe.name))
        self.assertEqual(recipe, obj)

    def test_recipe_traverse_project(self):
        # Make sure we can reach recipe of project-based OCI projects.
        project = self.factory.makeProduct()
        oci_project = self.factory.makeOCIProject(pillar=project)
        recipe = self.factory.makeOCIRecipe(oci_project=oci_project)
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

    def setUp(self):
        super(TestOCIRecipeAddView, self).setUp()
        self.distroseries = self.factory.makeDistroSeries()
        self.distribution = self.distroseries.distribution
        self.useFixture(FeatureFixture({
            OCI_RECIPE_ALLOW_CREATE: "on",
            "oci.build_series.%s" % self.distribution.name:
                self.distroseries.name,
            }))

    def setUpDistroSeries(self):
        """Set up self.distroseries with some available processors."""
        processor_names = ["386", "amd64", "hppa"]
        for name in processor_names:
            processor = getUtility(IProcessorSet).getByName(name)
            self.factory.makeDistroArchSeries(
                distroseries=self.distroseries, architecturetag=name,
                processor=processor)

    def assertProcessorControls(self, processors_control, enabled, disabled):
        matchers = [
            MatchesStructure.byEquality(optionValue=name, disabled=False)
            for name in enabled]
        matchers.extend([
            MatchesStructure.byEquality(optionValue=name, disabled=True)
            for name in disabled])
        self.assertThat(processors_control.controls, MatchesSetwise(*matchers))

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

    def test_create_new_recipe_display_processors(self):
        self.setUpDistroSeries()
        oci_project = self.factory.makeOCIProject(pillar=self.distribution)
        browser = self.getViewBrowser(
            oci_project, view_name="+new-recipe", user=self.person)
        processors = browser.getControl(name="field.processors")
        self.assertContentEqual(
            ["Intel 386 (386)", "AMD 64bit (amd64)", "HPPA Processor (hppa)"],
            [extract_text(option) for option in processors.displayOptions])
        self.assertContentEqual(["386", "amd64", "hppa"], processors.options)
        self.assertContentEqual(["386", "amd64", "hppa"], processors.value)

    def test_create_new_recipe_display_restricted_processors(self):
        # A restricted processor is shown disabled in the UI.
        self.setUpDistroSeries()
        oci_project = self.factory.makeOCIProject(pillar=self.distribution)
        proc_armhf = self.factory.makeProcessor(
            name="armhf", restricted=True, build_by_default=False)
        self.factory.makeDistroArchSeries(
            distroseries=self.distroseries, architecturetag="armhf",
            processor=proc_armhf)
        browser = self.getViewBrowser(
            oci_project, view_name="+new-recipe", user=self.person)
        processors = browser.getControl(name="field.processors")
        self.assertProcessorControls(
            processors, ["386", "amd64", "hppa"], ["armhf"])

    def test_create_new_recipe_processors(self):
        self.setUpDistroSeries()
        oci_project = self.factory.makeOCIProject(pillar=self.distribution)
        [git_ref] = self.factory.makeGitRefs()
        browser = self.getViewBrowser(
            oci_project, view_name="+new-recipe", user=self.person)
        processors = browser.getControl(name="field.processors")
        processors.value = ["386", "amd64"]
        browser.getControl(name="field.name").value = "recipe-name"
        browser.getControl("Git repository").value = (
            git_ref.repository.identity)
        browser.getControl("Git branch").value = git_ref.path
        browser.getControl("Create OCI recipe").click()
        login_person(self.person)
        recipe = getUtility(IOCIRecipeSet).getByName(
            self.person, oci_project, "recipe-name")
        self.assertContentEqual(
            ["386", "amd64"], [proc.name for proc in recipe.processors])


class TestOCIRecipeAdminView(BaseTestOCIRecipeView):

    def setUp(self):
        super(TestOCIRecipeAdminView, self).setUp()
        self.useFixture(FeatureFixture({OCI_RECIPE_ALLOW_CREATE: 'on'}))

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

    def setUp(self):
        super(TestOCIRecipeEditView, self).setUp()
        self.distroseries = self.factory.makeDistroSeries()
        self.distribution = self.distroseries.distribution
        self.useFixture(FeatureFixture({
            OCI_RECIPE_ALLOW_CREATE: "on",
            "oci.build_series.%s" % self.distribution.name:
                self.distroseries.name,
            }))

    def setUpDistroSeries(self):
        """Set up self.distroseries with some available processors."""
        processor_names = ["386", "amd64", "hppa"]
        for name in processor_names:
            processor = getUtility(IProcessorSet).getByName(name)
            self.factory.makeDistroArchSeries(
                distroseries=self.distroseries, architecturetag=name,
                processor=processor)

    def assertRecipeProcessors(self, recipe, names):
        self.assertContentEqual(
            names, [processor.name for processor in recipe.processors])

    def assertProcessorControls(self, processors_control, enabled, disabled):
        matchers = [
            MatchesStructure.byEquality(optionValue=name, disabled=False)
            for name in enabled]
        matchers.extend([
            MatchesStructure.byEquality(optionValue=name, disabled=True)
            for name in disabled])
        self.assertThat(processors_control.controls, MatchesSetwise(*matchers))

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

    def test_display_processors(self):
        self.setUpDistroSeries()
        oci_project = self.factory.makeOCIProject(pillar=self.distribution)
        recipe = self.factory.makeOCIRecipe(
            registrant=self.person, owner=self.person, oci_project=oci_project)
        browser = self.getViewBrowser(
            recipe, view_name="+edit", user=recipe.owner)
        processors = browser.getControl(name="field.processors")
        self.assertContentEqual(
            ["Intel 386 (386)", "AMD 64bit (amd64)", "HPPA Processor (hppa)"],
            [extract_text(option) for option in processors.displayOptions])
        self.assertContentEqual(["386", "amd64", "hppa"], processors.options)

    def test_edit_processors(self):
        self.setUpDistroSeries()
        oci_project = self.factory.makeOCIProject(pillar=self.distribution)
        recipe = self.factory.makeOCIRecipe(
            registrant=self.person, owner=self.person, oci_project=oci_project)
        self.assertRecipeProcessors(recipe, ["386", "amd64", "hppa"])
        browser = self.getViewBrowser(
            recipe, view_name="+edit", user=recipe.owner)
        processors = browser.getControl(name="field.processors")
        self.assertContentEqual(["386", "amd64", "hppa"], processors.value)
        processors.value = ["386", "amd64"]
        browser.getControl("Update OCI recipe").click()
        login_person(self.person)
        self.assertRecipeProcessors(recipe, ["386", "amd64"])

    def test_edit_with_invisible_processor(self):
        # It's possible for existing recipes to have an enabled processor
        # that's no longer usable with the current distroseries, which will
        # mean it's hidden from the UI, but the non-admin
        # OCIRecipe.setProcessors isn't allowed to disable it.  Editing the
        # processor list of such a recipe leaves the invisible processor
        # intact.
        proc_386 = getUtility(IProcessorSet).getByName("386")
        proc_amd64 = getUtility(IProcessorSet).getByName("amd64")
        proc_armel = self.factory.makeProcessor(
            name="armel", restricted=True, build_by_default=False)
        self.setUpDistroSeries()
        oci_project = self.factory.makeOCIProject(pillar=self.distribution)
        recipe = self.factory.makeOCIRecipe(
            registrant=self.person, owner=self.person, oci_project=oci_project)
        recipe.setProcessors([proc_386, proc_amd64, proc_armel])
        browser = self.getViewBrowser(
            recipe, view_name="+edit", user=recipe.owner)
        processors = browser.getControl(name="field.processors")
        self.assertContentEqual(["386", "amd64"], processors.value)
        processors.value = ["amd64"]
        browser.getControl("Update OCI recipe").click()
        login_person(self.person)
        self.assertRecipeProcessors(recipe, ["amd64", "armel"])

    def test_edit_processors_restricted(self):
        # A restricted processor is shown disabled in the UI and cannot be
        # enabled.
        self.setUpDistroSeries()
        proc_armhf = self.factory.makeProcessor(
            name="armhf", restricted=True, build_by_default=False)
        self.factory.makeDistroArchSeries(
            distroseries=self.distroseries, architecturetag="armhf",
            processor=proc_armhf)
        oci_project = self.factory.makeOCIProject(pillar=self.distribution)
        recipe = self.factory.makeOCIRecipe(
            registrant=self.person, owner=self.person, oci_project=oci_project)
        self.assertRecipeProcessors(recipe, ["386", "amd64", "hppa"])
        browser = self.getViewBrowser(
            recipe, view_name="+edit", user=recipe.owner)
        processors = browser.getControl(name="field.processors")
        self.assertContentEqual(["386", "amd64", "hppa"], processors.value)
        self.assertProcessorControls(
            processors, ["386", "amd64", "hppa"], ["armhf"])
        # Even if the user works around the disabled checkbox and forcibly
        # enables it, they can't enable the restricted processor.
        for control in processors.controls:
            if control.optionValue == "armhf":
                del control._control.attrs["disabled"]
        processors.value = ["386", "amd64", "armhf"]
        self.assertRaises(
            CannotModifyOCIRecipeProcessor,
            browser.getControl("Update OCI recipe").click)

    def test_edit_processors_restricted_already_enabled(self):
        # A restricted processor that is already enabled is shown disabled
        # in the UI.  This causes form submission to omit it, but the
        # validation code fixes that up behind the scenes so that we don't
        # get CannotModifyOCIRecipeProcessor.
        proc_386 = getUtility(IProcessorSet).getByName("386")
        proc_amd64 = getUtility(IProcessorSet).getByName("amd64")
        proc_armhf = self.factory.makeProcessor(
            name="armhf", restricted=True, build_by_default=False)
        self.setUpDistroSeries()
        self.factory.makeDistroArchSeries(
            distroseries=self.distroseries, architecturetag="armhf",
            processor=proc_armhf)
        oci_project = self.factory.makeOCIProject(pillar=self.distribution)
        recipe = self.factory.makeOCIRecipe(
            registrant=self.person, owner=self.person, oci_project=oci_project)
        recipe.setProcessors([proc_386, proc_amd64, proc_armhf])
        self.assertRecipeProcessors(recipe, ["386", "amd64", "armhf"])
        browser = self.getUserBrowser(
            canonical_url(recipe) + "/+edit", user=recipe.owner)
        processors = browser.getControl(name="field.processors")
        # armhf is checked but disabled.
        self.assertContentEqual(["386", "amd64", "armhf"], processors.value)
        self.assertProcessorControls(
            processors, ["386", "amd64", "hppa"], ["armhf"])
        processors.value = ["386"]
        browser.getControl("Update OCI recipe").click()
        login_person(self.person)
        self.assertRecipeProcessors(recipe, ["386", "armhf"])


class TestOCIRecipeDeleteView(BaseTestOCIRecipeView):

    def setUp(self):
        super(TestOCIRecipeDeleteView, self).setUp()
        self.useFixture(FeatureFixture({OCI_RECIPE_ALLOW_CREATE: 'on'}))

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
        self.useFixture(FeatureFixture({OCI_RECIPE_ALLOW_CREATE: 'on'}))

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

    def test_index_request_builds_link(self):
        # Recipe owners get a link to allow requesting builds.
        owner = self.factory.makePerson()
        distroseries = self.factory.makeDistroSeries()
        oci_project = self.factory.makeOCIProject(
            pillar=distroseries.distribution)
        recipe = self.factory.makeOCIRecipe(
            registrant=owner, owner=owner, oci_project=oci_project)
        recipe_name = recipe.name
        browser = self.getViewBrowser(recipe, user=owner)
        browser.getLink("Request builds").click()
        self.assertIn("Request builds for %s" % recipe_name, browser.contents)

    def test_index_request_builds_link_unauthorized(self):
        # People who cannot edit the recipe do not get a link to allow
        # requesting builds.
        distroseries = self.factory.makeDistroSeries()
        oci_project = self.factory.makeOCIProject(
            pillar=distroseries.distribution)
        recipe = self.factory.makeOCIRecipe(oci_project=oci_project)
        recipe_url = canonical_url(recipe)
        browser = self.getViewBrowser(recipe, user=self.person)
        self.assertRaises(LinkNotFoundError, browser.getLink, "Request builds")
        self.assertRaises(
            Unauthorized, self.getUserBrowser, recipe_url + "/+request-builds",
            user=self.person)

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


class TestOCIRecipeRequestBuildsView(BaseTestOCIRecipeView):

    def setUp(self):
        super(TestOCIRecipeRequestBuildsView, self).setUp()
        self.ubuntu = getUtility(ILaunchpadCelebrities).ubuntu
        self.distroseries = self.factory.makeDistroSeries(
            distribution=self.ubuntu, name="shiny", displayname="Shiny")
        self.architectures = []
        for processor, architecture in ("386", "i386"), ("amd64", "amd64"):
            das = self.factory.makeDistroArchSeries(
                distroseries=self.distroseries, architecturetag=architecture,
                processor=getUtility(IProcessorSet).getByName(processor))
            das.addOrUpdateChroot(self.factory.makeLibraryFileAlias())
            self.architectures.append(das)
        self.useFixture(FeatureFixture({
            OCI_RECIPE_ALLOW_CREATE: "on",
            "oci.build_series.%s" % self.distroseries.distribution.name:
                self.distroseries.name,
            }))
        oci_project = self.factory.makeOCIProject(
            pillar=self.distroseries.distribution,
            ociprojectname="oci-project-name")
        self.recipe = self.factory.makeOCIRecipe(
            name="recipe-name", registrant=self.person, owner=self.person,
            oci_project=oci_project)

    def test_request_builds_page(self):
        # The +request-builds page is sane.
        self.assertTextMatchesExpressionIgnoreWhitespace("""
            Request builds for recipe-name
            oci-project-name OCI project
            recipe-name
            Request builds
            Architectures:
            amd64
            i386
            or
            Cancel
            """,
            self.getMainText(self.recipe, "+request-builds", user=self.person))

    def test_request_builds_not_owner(self):
        # A user without launchpad.Edit cannot request builds.
        self.assertRaises(
            Unauthorized, self.getViewBrowser, self.recipe, "+request-builds")

    def test_request_builds_action(self):
        # Requesting a build creates pending builds.
        browser = self.getViewBrowser(
            self.recipe, "+request-builds", user=self.person)
        self.assertTrue(browser.getControl("amd64").selected)
        self.assertTrue(browser.getControl("i386").selected)
        browser.getControl("Request builds").click()

        login_person(self.person)
        builds = self.recipe.pending_builds
        self.assertContentEqual(
            ["amd64", "i386"],
            [build.distro_arch_series.architecturetag for build in builds])
        self.assertContentEqual(
            [2510], set(build.buildqueue_record.lastscore for build in builds))

    def test_request_builds_rejects_duplicate(self):
        # A duplicate build request causes a notification.
        self.recipe.requestBuild(self.person, self.distroseries["amd64"])
        browser = self.getViewBrowser(
            self.recipe, "+request-builds", user=self.person)
        self.assertTrue(browser.getControl("amd64").selected)
        self.assertTrue(browser.getControl("i386").selected)
        browser.getControl("Request builds").click()
        main_text = extract_text(find_main_content(browser.contents))
        self.assertIn("1 new build has been queued.", main_text)
        self.assertIn(
            "An identical build is already pending for amd64.", main_text)

    def test_request_builds_no_architectures(self):
        # Selecting no architectures causes a validation failure.
        browser = self.getViewBrowser(
            self.recipe, "+request-builds", user=self.person)
        browser.getControl("amd64").selected = False
        browser.getControl("i386").selected = False
        browser.getControl("Request builds").click()
        self.assertIn(
            "You need to select at least one architecture.",
            extract_text(find_main_content(browser.contents)))


class TestOCIRecipePushRulesView(OCIConfigHelperMixin,
                                 BaseTestOCIRecipeView):
    def setUp(self):
        super(TestOCIRecipePushRulesView, self).setUp()
        self.ubuntu = getUtility(ILaunchpadCelebrities).ubuntu
        self.distroseries = self.factory.makeDistroSeries(
            distribution=self.ubuntu, name="shiny", displayname="Shiny")
        self.useFixture(FeatureFixture({
            OCI_RECIPE_ALLOW_CREATE: "on",
            "oci.build_series.%s" % self.distroseries.distribution.name:
                self.distroseries.name,
        }))
        oci_project = self.factory.makeOCIProject(
            pillar=self.distroseries.distribution,
            ociprojectname="oci-project-name")
        self.recipe = self.factory.makeOCIRecipe(
            name="recipe-name", registrant=self.person, owner=self.person,
            oci_project=oci_project)
        self.setConfig()

    def test_view_oci_push_rules(self):
        url = unicode(self.factory.getUniqueURL())
        credentials = {'username': 'foo', 'password': 'bar'}
        registry_credentials = getUtility(IOCIRegistryCredentialsSet).new(
            owner=self.person,
            url=url,
            credentials=credentials)
        image_name = self.factory.getUniqueUnicode()
        push_rule = getUtility(IOCIPushRuleSet).new(
            recipe=self.recipe,
            registry_credentials=registry_credentials,
            image_name=image_name)
        view = create_initialized_view(
                self.recipe, "+index", principal=self.person)

        # Display the Registry URL and the Username
        # for the credentials owner
        with person_logged_in(self.person):
            rendered_view = view.render()
            row = soupmatchers.Tag("push rule row", "tr",
                                   attrs={"id": "rule-%d" % push_rule.id})
            self.assertThat(rendered_view, soupmatchers.HTMLContains(
                soupmatchers.Within(
                    row,
                    soupmatchers.Tag("Registry URL", "td",
                                     text=registry_credentials.url)),
                soupmatchers.Within(
                    row,
                    soupmatchers.Tag("Username", "td",
                                     text=registry_credentials.username)),
                soupmatchers.Within(
                    row,
                    soupmatchers.Tag(
                        "Image name", "td", text=image_name))))

    def test_view_oci_push_rules_non_owner(self):
        url = unicode(self.factory.getUniqueURL())
        credentials = {'username': 'foo', 'password': 'bar'}
        registry_credentials = getUtility(IOCIRegistryCredentialsSet).new(
            owner=self.person,
            url=url,
            credentials=credentials)
        image_name = self.factory.getUniqueUnicode()
        push_rule = getUtility(IOCIPushRuleSet).new(
            recipe=self.recipe,
            registry_credentials=registry_credentials,
            image_name=image_name)
        non_owner = self.factory.makePerson()
        admin = self.factory.makePerson(
            member_of=[getUtility(IPersonSet).getByName('admins')])
        view = create_initialized_view(
                self.recipe, "+index", principal=non_owner)

        # Display only the image name for users
        # who are not the registry credentials owner
        with person_logged_in(non_owner):
            rendered_view = view.render()
            row = soupmatchers.Tag("push rule row", "tr",
                                   attrs={"id": "rule-%d" % push_rule.id})
            self.assertThat(rendered_view, soupmatchers.HTMLContains(
                soupmatchers.Within(
                    row,
                    soupmatchers.Tag("Registry URL", "td")),
                soupmatchers.Within(
                    row,
                    soupmatchers.Tag("Username", "td")),
                soupmatchers.Within(
                    row,
                    soupmatchers.Tag(
                        "Image name", "td", text=image_name))))

        # Anonymous users can't see registry credentials
        # even though they can see the push rule
        with anonymous_logged_in():
            rendered_view = view.render()
            row = soupmatchers.Tag("push rule row", "tr",
                                   attrs={"id": "rule-%d" % push_rule.id})
            self.assertThat(rendered_view, soupmatchers.HTMLContains(
                soupmatchers.Within(
                    row,
                    soupmatchers.Tag("Registry URL", "td")),
                soupmatchers.Within(
                    row,
                    soupmatchers.Tag("Username", "td")),
                soupmatchers.Within(
                    row,
                    soupmatchers.Tag(
                        "Image name", "td", text=image_name))))

        # Although not the owner of the registry credentials
        # the admin user has launchpad.View permission on
        # OCI registry credentials and should be able to see
        # the registry URL and username of the owner.
        # see ViewOCIRegistryCredentials
        with person_logged_in(admin):
            rendered_view = view.render()
            row = soupmatchers.Tag("push rule row", "tr",
                                   attrs={"id": "rule-%d" % push_rule.id})
            self.assertThat(rendered_view, soupmatchers.HTMLContains(
                soupmatchers.Within(
                    row,
                    soupmatchers.Tag("Registry URL", "td",
                                     text=registry_credentials.url)),
                soupmatchers.Within(
                    row,
                    soupmatchers.Tag("Username", "td",
                                     text=registry_credentials.username)),
                soupmatchers.Within(
                    row,
                    soupmatchers.Tag(
                        "Image name", "td", text=image_name))))


class TestOCIProjectRecipesView(BaseTestOCIRecipeView):
    def setUp(self):
        super(TestOCIProjectRecipesView, self).setUp()
        self.ubuntu = getUtility(ILaunchpadCelebrities).ubuntu
        self.distroseries = self.factory.makeDistroSeries(
            distribution=self.ubuntu, name="shiny", displayname="Shiny")
        self.architectures = []
        for processor, architecture in ("386", "i386"), ("amd64", "amd64"):
            das = self.factory.makeDistroArchSeries(
                distroseries=self.distroseries, architecturetag=architecture,
                processor=getUtility(IProcessorSet).getByName(processor))
            das.addOrUpdateChroot(self.factory.makeLibraryFileAlias())
            self.architectures.append(das)
        self.useFixture(FeatureFixture({OCI_RECIPE_ALLOW_CREATE: 'on'}))
        self.oci_project = self.factory.makeOCIProject(
            pillar=self.distroseries.distribution,
            ociprojectname="oci-project-name")

    def makeRecipes(self, count=1):
        with person_logged_in(self.person):
            owner = self.factory.makePerson()
            return [self.factory.makeOCIRecipe(
                registrant=owner, owner=owner, oci_project=self.oci_project)
                for _ in range(count)]

    def test_shows_no_recipe(self):
        browser = self.getViewBrowser(
            self.oci_project, "+recipes", user=self.person)
        main_text = extract_text(find_main_content(browser.contents))
        with person_logged_in(self.person):
            self.assertIn(
                "There are no recipes registered for %s"
                % self.oci_project.name,
                main_text)

    def test_paginates_recipes(self):
        batch_size = 5
        self.pushConfig("launchpad", default_batch_size=batch_size)
        recipes = self.makeRecipes(10)
        browser = self.getViewBrowser(
            self.oci_project, "+recipes", user=self.person)

        main_text = extract_text(find_main_content(browser.contents))
        no_wrap_main_text = main_text.replace('\n', ' ')
        with person_logged_in(self.person):
            self.assertIn(
                "There are 10 recipes registered for %s"
                % self.oci_project.name,
                no_wrap_main_text)
            self.assertIn("1 → 5 of 10 results", no_wrap_main_text)
            self.assertIn("First • Previous • Next • Last", no_wrap_main_text)

            # Make sure it's listing the first set of recipes
            items = sorted(recipes, key=attrgetter('name'))
            for recipe in items[:batch_size]:
                self.assertIn(recipe.name, main_text)

    def test_constant_query_count(self):
        batch_size = 3
        self.pushConfig("launchpad", default_batch_size=batch_size)

        def getView():
            view = self.getViewBrowser(
                self.oci_project, "+recipes", user=self.person)
            return view

        def do_login():
            self.useFixture(FeatureFixture({OCI_RECIPE_ALLOW_CREATE: 'on'}))
            login_person(self.person)

        recorder1, recorder2 = record_two_runs(
            getView, self.makeRecipes, 1, 15, login_method=do_login)

        # The first run (with no extra pages) makes BatchNavigator issue one
        # extra count(*) on OCIRecipe. Shouldn't be a big deal.
        self.assertEqual(recorder1.count, recorder2.count - 1)
