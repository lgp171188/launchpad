# Copyright 2019-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test OCI project views."""

__all__ = []

import re
from datetime import datetime, timezone

import soupmatchers
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.app.enums import InformationType
from lp.code.interfaces.gitrepository import IGitRepositorySet
from lp.oci.tests.helpers import OCIConfigHelperMixin
from lp.registry.interfaces.ociproject import (
    OCI_PROJECT_ALLOW_CREATE,
    OCIProjectCreateFeatureDisabled,
)
from lp.services.database.constants import UTC_NOW
from lp.services.features.testing import FeatureFixture
from lp.services.webapp import canonical_url
from lp.services.webapp.escaping import structured
from lp.testing import (
    BrowserTestCase,
    TestCaseWithFactory,
    admin_logged_in,
    login_person,
    person_logged_in,
    record_two_runs,
    test_tales,
)
from lp.testing.layers import DatabaseFunctionalLayer
from lp.testing.matchers import MatchesTagText
from lp.testing.pages import (
    extract_text,
    find_main_content,
    find_tag_by_id,
    find_tags_by_class,
)
from lp.testing.publication import test_traverse
from lp.testing.views import create_initialized_view


class TestOCIProjectFormatterAPI(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_link(self):
        oci_project = self.factory.makeOCIProject()
        markup = structured(
            '<a href="/%s/+oci/%s">%s</a>',
            oci_project.pillar.name,
            oci_project.name,
            oci_project.display_name,
        ).escapedtext
        self.assertEqual(
            markup, test_tales("oci_project/fmt:link", oci_project=oci_project)
        )


class TestOCIProjectNavigation(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_canonical_url(self):
        distribution = self.factory.makeDistribution(name="mydistro")
        oci_project = self.factory.makeOCIProject(
            pillar=distribution, ociprojectname="myociproject"
        )
        self.assertEqual(
            "http://launchpad.test/mydistro/+oci/myociproject",
            canonical_url(oci_project),
        )

    def test_traversal(self):
        oci_project = self.factory.makeOCIProject()
        obj, _, _ = test_traverse(
            "http://launchpad.test/%s/+oci/%s"
            % (oci_project.pillar.name, oci_project.name)
        )
        self.assertEqual(oci_project, obj)


class TestOCIProjectView(OCIConfigHelperMixin, BrowserTestCase):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.setConfig()

    def test_facet_top_links(self):
        oci_project = self.factory.makeOCIProject()
        browser = self.getViewBrowser(oci_project)
        menu = soupmatchers.Tag(
            "facetmenu", "ul", attrs={"class": "facetmenu"}
        )

        with admin_logged_in():
            # Expected links with (title, link, "<li> element's css classes")
            expected_links = [
                ("Overview", None, "overview active"),
                (
                    "Code",
                    canonical_url(
                        oci_project, view_name="+code", rootsite="code"
                    ),
                    None,
                ),
                (
                    "Bugs",
                    canonical_url(
                        oci_project, view_name="+bugs", rootsite="bugs"
                    ),
                    None,
                ),
                ("Blueprints", None, "specifications disabled-tab"),
                ("Translations", None, "translations disabled-tab"),
                ("Answers", None, "answers disabled-tab"),
            ]

        tags = []
        for text, link, css_classes in expected_links:
            if link:
                tags.append(
                    soupmatchers.Tag(
                        text, "a", text=text, attrs={"href": link}
                    )
                )
            else:
                tags.append(
                    soupmatchers.Tag(
                        text, "li", text=text, attrs={"class": css_classes}
                    )
                )

        self.assertThat(
            browser.contents,
            soupmatchers.HTMLContains(
                *[soupmatchers.Within(menu, tag) for tag in tags]
            ),
        )

    def test_index_distribution_pillar(self):
        distribution = self.factory.makeDistribution(displayname="My Distro")
        oci_project = self.factory.makeOCIProject(
            pillar=distribution, ociprojectname="oci-name"
        )
        self.assertTextMatchesExpressionIgnoreWhitespace(
            """\
            OCI project oci-name for My Distro
            .*
            OCI project information
            Distribution: My Distro
            Name: oci-name
            """,
            self.getMainText(oci_project),
        )

    def test_index_project_pillar(self):
        product = self.factory.makeProduct(displayname="My Project")
        oci_project = self.factory.makeOCIProject(
            pillar=product, ociprojectname="oci-name"
        )
        self.assertTextMatchesExpressionIgnoreWhitespace(
            """\
            OCI project oci-name for My Project
            .*
            OCI project information
            Project: My Project
            Name: oci-name
            """,
            self.getMainText(oci_project),
        )

    def test_hides_recipes_link_if_no_recipe_is_present(self):
        oci_project = self.factory.makeOCIProject(ociprojectname="oci-name")
        browser = self.getViewBrowser(oci_project)
        actions = extract_text(
            find_tag_by_id(browser.contents, "global-actions")
        )
        expected_links = ["Create OCI recipe"]
        self.assertEqual("\n".join(expected_links), actions)

    def test_shows_recipes_link_if_public_recipe_is_present(self):
        oci_project = self.factory.makeOCIProject(ociprojectname="oci-name")
        self.factory.makeOCIRecipe(oci_project=oci_project)
        browser = self.getViewBrowser(oci_project)
        actions = extract_text(
            find_tag_by_id(browser.contents, "global-actions")
        )
        expected_links = ["Create OCI recipe", "View all recipes"]
        self.assertEqual("\n".join(expected_links), actions)

    def test_hides_recipes_link_if_only_non_visible_recipe_exists(self):
        oci_project = self.factory.makeOCIProject(ociprojectname="oci-name")
        owner = self.factory.makePerson()
        self.factory.makeOCIRecipe(
            owner=owner,
            registrant=owner,
            oci_project=oci_project,
            information_type=InformationType.PRIVATESECURITY,
        )
        another_user = self.factory.makePerson()
        browser = self.getViewBrowser(oci_project, user=another_user)
        actions = extract_text(
            find_tag_by_id(browser.contents, "global-actions")
        )
        expected_links = ["Create OCI recipe"]
        self.assertEqual("\n".join(expected_links), actions)

    def test_shows_recipes_link_if_user_has_access_to_private_recipe(self):
        oci_project = self.factory.makeOCIProject(ociprojectname="oci-name")
        owner = self.factory.makePerson()
        recipe = self.factory.makeOCIRecipe(
            owner=owner,
            registrant=owner,
            oci_project=oci_project,
            information_type=InformationType.PRIVATESECURITY,
        )
        another_user = self.factory.makePerson()
        with admin_logged_in():
            recipe.subscribe(another_user, recipe.owner)
        browser = self.getViewBrowser(oci_project, user=another_user)
        actions = extract_text(
            find_tag_by_id(browser.contents, "global-actions")
        )
        expected_links = ["Create OCI recipe", "View all recipes"]
        self.assertEqual("\n".join(expected_links), actions)

    def test_git_repo_hint_cannot_push(self):
        owner = self.factory.makePerson()
        pillar = self.factory.makeProduct(name="a-pillar")
        oci_project = self.factory.makeOCIProject(
            pillar=pillar, ociprojectname="oci-name"
        )
        self.assertNotIn(
            "You can create a git repository",
            self.getMainText(oci_project, user=owner),
        )

    def test_git_repo_hint_can_push(self):
        pillar = self.factory.makeProduct(name="a-pillar")
        oci_project = self.factory.makeOCIProject(
            pillar=pillar, ociprojectname="oci-name"
        )
        self.factory.makeGitRepository(
            name=oci_project.name,
            target=oci_project,
            owner=pillar.owner,
            registrant=pillar.owner,
        )
        git_url = "git+ssh://%s@git.launchpad.test/a-pillar/+oci/oci-name" % (
            pillar.owner.name
        )
        self.assertTextMatchesExpressionIgnoreWhitespace(
            """\
            OCI project oci-name for A-pillar
            .*
            You can create a git repository for this OCI project in order
            to build your OCI recipes by using the following commands:
            git remote add origin %s
            git push --set-upstream origin master

            OCI project information
            Project: A-pillar
            Edit OCI project
            Name: oci-name
            Edit OCI project
            """
            % re.escape(git_url),
            self.getMainText(oci_project, user=pillar.owner),
        )

    def test_shows_existing_default_git_repo(self):
        pillar = self.factory.makeProduct(name="a-pillar")
        oci_project = self.factory.makeOCIProject(
            pillar=pillar, ociprojectname="oci-name"
        )
        repository = self.factory.makeGitRepository(
            name=oci_project.name, target=oci_project
        )
        with person_logged_in(pillar.owner):
            getUtility(IGitRepositorySet).setDefaultRepository(
                oci_project, repository
            )
        git_url = "lp:a-pillar/+oci/oci-name"
        self.assertTextMatchesExpressionIgnoreWhitespace(
            """\
            OCI project oci-name for A-pillar
            .*
            The default git repository for this project is %s.

            OCI project information
            Project: A-pillar
            Name: oci-name
            """
            % re.escape(git_url),
            self.getMainText(oci_project),
        )

    def test_shows_official_recipes(self):
        distribution = self.factory.makeDistribution(displayname="My Distro")
        oci_project = self.factory.makeOCIProject(
            pillar=distribution, ociprojectname="oci-name"
        )
        self.factory.makeOCIRecipe(oci_project=oci_project, official=True)
        browser = self.getViewBrowser(
            oci_project, view_name="+index", user=distribution.owner
        )
        self.assertIn("Official recipes", browser.contents)
        self.assertNotIn("unofficial recipe", browser.contents)
        self.assertNotIn(
            "There are no recipes registered for this OCI project.",
            browser.contents,
        )

    def test_shows_official_and_unofficial_recipes(self):
        distribution = self.factory.makeDistribution(displayname="My Distro")
        oci_project = self.factory.makeOCIProject(
            pillar=distribution, ociprojectname="oci-name"
        )
        self.factory.makeOCIRecipe(oci_project=oci_project, official=True)
        self.factory.makeOCIRecipe(oci_project=oci_project, official=False)
        browser = self.getViewBrowser(
            oci_project, view_name="+index", user=distribution.owner
        )
        self.assertIn("Official recipes", browser.contents)
        self.assertIn(
            "There is <strong>1</strong> unofficial recipe.", browser.contents
        )
        self.assertNotIn(
            "There are no recipes registered for this OCI project.",
            browser.contents,
        )

    def test_shows_unofficial_recipes(self):
        distribution = self.factory.makeDistribution(displayname="My Distro")
        oci_project = self.factory.makeOCIProject(
            pillar=distribution, ociprojectname="oci-name"
        )
        self.factory.makeOCIRecipe(oci_project=oci_project, official=False)
        self.factory.makeOCIRecipe(oci_project=oci_project, official=False)

        browser = self.getViewBrowser(
            oci_project, view_name="+index", user=distribution.owner
        )
        self.assertNotIn("Official recipes", browser.contents)
        self.assertIn(
            "There are <strong>2</strong> unofficial recipes.",
            browser.contents,
        )
        self.assertNotIn(
            "There are no recipes registered for this OCI project.",
            browser.contents,
        )

    def test_shows_private_recipes_with_proper_grants(self):
        distribution = self.factory.makeDistribution(displayname="My Distro")
        oci_project = self.factory.makeOCIProject(
            pillar=distribution, ociprojectname="oci-name"
        )
        owner = self.factory.makePerson()
        official_recipe = self.factory.makeOCIRecipe(
            owner=owner,
            registrant=owner,
            oci_project=oci_project,
            official=True,
            information_type=InformationType.PRIVATESECURITY,
        )
        unofficial_recipe = self.factory.makeOCIRecipe(
            owner=owner,
            registrant=owner,
            oci_project=oci_project,
            official=False,
            information_type=InformationType.PRIVATESECURITY,
        )

        granted_user = self.factory.makePerson()
        with admin_logged_in():
            unofficial_recipe.subscribe(granted_user, official_recipe.owner)
            official_recipe.subscribe(granted_user, official_recipe.owner)
            official_recipe_url = canonical_url(
                official_recipe, force_local_path=True
            )
        browser = self.getViewBrowser(oci_project, user=granted_user)

        self.assertIn(
            "There is <strong>1</strong> unofficial recipe.", browser.contents
        )
        self.assertIn("<h3>Official recipes</h3>", browser.contents)

        recipes_tag = find_tag_by_id(browser.contents, "mirrors_list")
        rows = recipes_tag.find_all("tr")
        self.assertEqual(2, len(rows), "We should have a header and 1 row")
        self.assertIn(official_recipe_url, str(rows[1]))

    def test_shows_no_recipes(self):
        distribution = self.factory.makeDistribution(displayname="My Distro")
        oci_project = self.factory.makeOCIProject(
            pillar=distribution, ociprojectname="oci-name"
        )

        # Make sure we don't include private recipes that the visitor
        # doesn't have access to.
        owner = self.factory.makePerson()
        self.factory.makeOCIRecipe(
            owner=owner,
            registrant=owner,
            oci_project=oci_project,
            information_type=InformationType.PRIVATESECURITY,
        )
        self.factory.makeOCIRecipe(
            owner=owner,
            registrant=owner,
            oci_project=oci_project,
            official=True,
            information_type=InformationType.PRIVATESECURITY,
        )

        browser = self.getViewBrowser(
            oci_project, view_name="+index", user=self.factory.makePerson()
        )
        self.assertNotIn("Official recipes", browser.contents)
        self.assertNotIn("unofficial recipe", browser.contents)
        self.assertIn(
            "There are no recipes registered for this OCI project.",
            browser.contents,
        )


class TestOCIProjectEditView(BrowserTestCase):
    layer = DatabaseFunctionalLayer

    def submitEditForm(self, browser, name):
        browser.getLink("Edit OCI project").click()
        browser.getControl(name="field.name").value = name
        browser.getControl("Update OCI project").click()

    def test_edit_oci_project(self):
        oci_project = self.factory.makeOCIProject()
        new_distribution = self.factory.makeDistribution(
            owner=oci_project.pillar.owner
        )
        new_distribution_name = new_distribution.name
        new_distribution_display_name = new_distribution.display_name

        browser = self.getViewBrowser(
            oci_project, user=oci_project.pillar.owner
        )
        browser.getLink("Edit OCI project").click()
        browser.getControl(name="field.distribution").value = [
            new_distribution_name
        ]
        browser.getControl(name="field.name").value = "new-name"
        browser.getControl("Update OCI project").click()

        content = find_main_content(browser.contents)
        self.assertEqual(
            "OCI project new-name for %s" % new_distribution_display_name,
            extract_text(content.h1),
        )
        self.assertThat(
            "Distribution:\n%s\nEdit OCI project"
            % (new_distribution_display_name),
            MatchesTagText(content, "pillar"),
        )
        self.assertThat(
            "Name:\nnew-name\nEdit OCI project",
            MatchesTagText(content, "name"),
        )

    def test_edit_oci_project_change_project_pillar(self):
        with admin_logged_in():
            owner = self.factory.makePerson()
            project = self.factory.makeProduct(owner=owner)
            new_project = self.factory.makeProduct(owner=owner)
            oci_project = self.factory.makeOCIProject(pillar=project)
            new_project_name = new_project.name

        browser = self.getViewBrowser(
            oci_project, user=oci_project.pillar.owner
        )
        browser.getLink("Edit OCI project").click()
        browser.getControl(name="field.project").value = [new_project_name]
        browser.getControl(name="field.name").value = "new-name"
        browser.getControl("Update OCI project").click()

        content = find_main_content(browser.contents)
        with person_logged_in(owner):
            self.assertEqual(
                "OCI project new-name for %s" % new_project.display_name,
                extract_text(content.h1),
            )
            self.assertThat(
                "Project:\n%s\nEdit OCI project" % (new_project.display_name),
                MatchesTagText(content, "pillar"),
            )
            self.assertThat(
                "Name:\nnew-name\nEdit OCI project",
                MatchesTagText(content, "name"),
            )

    def test_edit_oci_project_ad_oci_project_admin(self):
        admin_person = self.factory.makePerson()
        admin_team = self.factory.makeTeam(members=[admin_person])
        original_distribution = self.factory.makeDistribution(
            oci_project_admin=admin_team
        )
        oci_project = self.factory.makeOCIProject(pillar=original_distribution)
        new_distribution = self.factory.makeDistribution(
            oci_project_admin=admin_team
        )
        new_distribution_name = new_distribution.name
        new_distribution_display_name = new_distribution.display_name

        browser = self.getViewBrowser(oci_project, user=admin_person)
        browser.getLink("Edit OCI project").click()
        browser.getControl(name="field.distribution").value = [
            new_distribution_name
        ]
        browser.getControl(name="field.name").value = "new-name"
        browser.getControl("Update OCI project").click()

        content = find_main_content(browser.contents)
        self.assertEqual(
            "OCI project new-name for %s" % new_distribution_display_name,
            extract_text(content.h1),
        )
        self.assertThat(
            "Distribution:\n%s\nEdit OCI project"
            % (new_distribution_display_name),
            MatchesTagText(content, "pillar"),
        )
        self.assertThat(
            "Name:\nnew-name\nEdit OCI project",
            MatchesTagText(content, "name"),
        )

    def test_edit_oci_project_sets_date_last_modified(self):
        # Editing an OCI project sets the date_last_modified property.
        date_created = datetime(2000, 1, 1, tzinfo=timezone.utc)
        oci_project = self.factory.makeOCIProject(date_created=date_created)
        self.assertEqual(date_created, oci_project.date_last_modified)
        with person_logged_in(oci_project.pillar.owner):
            view = create_initialized_view(
                oci_project, name="+edit", principal=oci_project.pillar.owner
            )
            view.update_action.success({"name": "changed"})
        self.assertSqlAttributeEqualsDate(
            oci_project, "date_last_modified", UTC_NOW
        )

    def test_edit_oci_project_already_exists(self):
        oci_project = self.factory.makeOCIProject(ociprojectname="one")
        self.factory.makeOCIProject(
            pillar=oci_project.pillar, ociprojectname="two"
        )
        pillar_display_name = oci_project.pillar.display_name
        browser = self.getViewBrowser(
            oci_project, user=oci_project.pillar.owner
        )
        self.submitEditForm(browser, "two")
        self.assertEqual(
            "There is already an OCI project in distribution %s with this "
            "name." % (pillar_display_name),
            extract_text(find_tags_by_class(browser.contents, "message")[1]),
        )

    def test_edit_oci_project_invalid_name(self):
        oci_project = self.factory.makeOCIProject()
        browser = self.getViewBrowser(
            oci_project, user=oci_project.pillar.owner
        )
        self.submitEditForm(browser, "invalid name")

        self.assertStartsWith(
            extract_text(find_tags_by_class(browser.contents, "message")[1]),
            "Invalid name 'invalid name'.",
        )


class TestOCIProjectAddView(BrowserTestCase):
    layer = DatabaseFunctionalLayer

    def test_create_oci_project(self):
        oci_project = self.factory.makeOCIProject()
        user = oci_project.pillar.owner
        new_distribution = self.factory.makeDistribution(
            owner=user, oci_project_admin=user
        )
        new_distribution_display_name = new_distribution.display_name
        browser = self.getViewBrowser(
            new_distribution, user=user, view_name="+new-oci-project"
        )
        browser.getControl(name="field.name").value = "new-name"
        browser.getControl("Create OCI Project").click()

        content = find_main_content(browser.contents)
        self.assertEqual(
            "OCI project new-name for %s" % new_distribution_display_name,
            extract_text(content.h1),
        )
        self.assertThat(
            "Distribution:\n%s\nEdit OCI project"
            % (new_distribution_display_name),
            MatchesTagText(content, "pillar"),
        )
        self.assertThat(
            "Name:\nnew-name\nEdit OCI project",
            MatchesTagText(content, "name"),
        )

    def test_create_oci_project_for_project(self):
        oci_project = self.factory.makeOCIProject()
        user = oci_project.pillar.owner
        project = self.factory.makeProduct(owner=user)
        browser = self.getViewBrowser(
            project, user=user, view_name="+new-oci-project"
        )
        browser.getControl(name="field.name").value = "new-name"
        browser.getControl("Create OCI Project").click()

        content = find_main_content(browser.contents)
        with person_logged_in(user):
            self.assertEqual(
                "OCI project new-name for %s" % project.display_name,
                extract_text(content.h1),
            )
            self.assertThat(
                "Project:\n%s\nEdit OCI project" % (project.display_name),
                MatchesTagText(content, "pillar"),
            )
            self.assertThat(
                "Name:\nnew-name\nEdit OCI project",
                MatchesTagText(content, "name"),
            )

    def test_create_oci_project_already_exists(self):
        person = self.factory.makePerson()
        distribution = self.factory.makeDistribution(oci_project_admin=person)
        distribution_display_name = distribution.display_name
        self.factory.makeOCIProject(
            ociprojectname="new-name", pillar=distribution, registrant=person
        )

        browser = self.getViewBrowser(
            distribution, user=person, view_name="+new-oci-project"
        )
        browser.getControl(name="field.name").value = "new-name"
        browser.getControl("Create OCI Project").click()

        expected_msg = (
            "There is already an OCI project in distribution %s with this "
            "name." % distribution_display_name
        )
        self.assertEqual(
            expected_msg,
            extract_text(find_tags_by_class(browser.contents, "message")[1]),
        )

    def test_create_oci_project_no_permission(self):
        self.useFixture(FeatureFixture({OCI_PROJECT_ALLOW_CREATE: ""}))
        another_person = self.factory.makePerson()
        new_distribution = self.factory.makeDistribution()
        self.assertRaises(
            OCIProjectCreateFeatureDisabled,
            self.getViewBrowser,
            new_distribution,
            user=another_person,
            view_name="+new-oci-project",
        )


class TestOCIProjectSearchView(BrowserTestCase):
    layer = DatabaseFunctionalLayer

    def assertPaginationIsPresent(
        self, browser, results_in_page, total_result
    ):
        """Checks that pagination is shown at the browser."""
        nav_index = find_tags_by_class(
            browser.contents, "batch-navigation-index"
        )[0]
        nav_index_text = extract_text(nav_index).replace("\n", " ")
        self.assertIn(
            "1 → %s of %s results" % (results_in_page, total_result),
            nav_index_text,
        )

        nav_links = find_tags_by_class(
            browser.contents, "batch-navigation-links"
        )[0]
        nav_links_text = extract_text(nav_links).replace("\n", " ")
        self.assertIn("First • Previous • Next • Last", nav_links_text)

    def assertOCIProjectsArePresent(self, browser, oci_projects):
        table = find_tag_by_id(browser.contents, "projects_list")
        with admin_logged_in():
            for oci_project in oci_projects:
                url = canonical_url(oci_project, force_local_path=True)
                self.assertIn(url, str(table))
                self.assertIn(oci_project.name, str(table))

    def assertOCIProjectsAreNotPresent(self, browser, oci_projects):
        table = find_tag_by_id(browser.contents, "projects_list")
        with admin_logged_in():
            for oci_project in oci_projects:
                url = canonical_url(oci_project, force_local_path=True)
                self.assertNotIn(url, str(table))
                self.assertNotIn(oci_project.name, str(table))

    def check_search_no_oci_projects(self, pillar):
        pillar = removeSecurityProxy(pillar)
        person = self.factory.makePerson()

        browser = self.getViewBrowser(
            pillar, user=person, view_name="+search-oci-project"
        )

        main_portlet = find_tags_by_class(browser.contents, "main-portlet")[0]
        self.assertIn(
            "There are no OCI projects registered for %s" % pillar.name,
            extract_text(main_portlet).replace("\n", " "),
        )

    def test_search_no_oci_projects_distribution_pillar(self):
        return self.check_search_no_oci_projects(
            self.factory.makeDistribution()
        )

    def test_search_no_oci_projects_project_pillar(self):
        return self.check_search_no_oci_projects(self.factory.makeProduct())

    def check_oci_projects_no_search_keyword(self, pillar):
        pillar = removeSecurityProxy(pillar)
        person = pillar.owner

        # Creates 3 OCI Projects
        oci_projects = [
            self.factory.makeOCIProject(
                ociprojectname="test-project-%s" % i,
                registrant=person,
                pillar=pillar,
            )
            for i in range(3)
        ]

        browser = self.getViewBrowser(
            pillar, user=person, view_name="+search-oci-project"
        )

        # Check top message.
        main_portlet = find_tags_by_class(browser.contents, "main-portlet")[0]
        self.assertIn(
            "There are 3 OCI projects registered for %s" % pillar.name,
            extract_text(main_portlet).replace("\n", " "),
        )

        self.assertOCIProjectsArePresent(browser, oci_projects)
        self.assertPaginationIsPresent(browser, 3, 3)

    def test_oci_projects_no_search_keyword_for_distribution(self):
        return self.check_oci_projects_no_search_keyword(
            self.factory.makeDistribution()
        )

    def test_oci_projects_no_search_keyword_for_project(self):
        return self.check_oci_projects_no_search_keyword(
            self.factory.makeProduct()
        )

    def check_oci_projects_with_search_keyword(self, pillar):
        pillar = removeSecurityProxy(pillar)
        person = pillar.owner

        # And 2 OCI projects that will match the name
        oci_projects = [
            self.factory.makeOCIProject(
                ociprojectname="find-me-%s" % i,
                registrant=person,
                pillar=pillar,
            )
            for i in range(2)
        ]

        # Creates 2 OCI Projects that will not match search
        other_oci_projects = [
            self.factory.makeOCIProject(
                ociprojectname="something-%s" % i,
                registrant=person,
                pillar=pillar,
            )
            for i in range(2)
        ]

        browser = self.getViewBrowser(
            pillar, user=person, view_name="+search-oci-project"
        )
        browser.getControl(name="text").value = "find-me"
        browser.getControl("Search").click()

        # Check top message.
        main_portlet = find_tags_by_class(browser.contents, "main-portlet")[0]
        self.assertIn(
            'There are 2 OCI projects registered for %s matching "%s"'
            % (pillar.name, "find-me"),
            extract_text(main_portlet).replace("\n", " "),
        )

        self.assertOCIProjectsArePresent(browser, oci_projects)
        self.assertOCIProjectsAreNotPresent(browser, other_oci_projects)
        self.assertPaginationIsPresent(browser, 2, 2)

    def test_oci_projects_with_search_keyword_for_distribution(self):
        self.check_oci_projects_with_search_keyword(
            self.factory.makeDistribution()
        )

    def test_oci_projects_with_search_keyword_for_project(self):
        self.check_oci_projects_with_search_keyword(self.factory.makeProduct())

    def check_query_count_is_constant(self, pillar):
        batch_size = 3
        self.pushConfig("launchpad", default_batch_size=batch_size)

        person = self.factory.makePerson()
        distro = self.factory.makeDistribution(owner=person)
        name_pattern = "find-me-"

        def createOCIProject():
            self.factory.makeOCIProject(
                ociprojectname=self.factory.getUniqueString(name_pattern),
                pillar=distro,
            )

        viewer = self.factory.makePerson()

        def getView():
            browser = self.getViewBrowser(
                distro, user=viewer, view_name="+search-oci-project"
            )
            browser.getControl(name="text").value = name_pattern
            browser.getControl("Search").click()
            return browser

        def do_login():
            login_person(person)

        recorder1, recorder2 = record_two_runs(
            getView, createOCIProject, 1, 10, login_method=do_login
        )
        self.assertEqual(recorder1.count, recorder2.count)

    def test_query_count_is_constant_for_distribution(self):
        self.check_query_count_is_constant(self.factory.makeDistribution())

    def test_query_count_is_constant_for_project(self):
        self.check_query_count_is_constant(self.factory.makeProduct())
