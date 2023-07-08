# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test OCI recipe build views."""

import re

import soupmatchers
import transaction
from fixtures import FakeLogger
from storm.locals import Store
from testtools.matchers import StartsWith
from zope.component import getUtility
from zope.security.interfaces import Unauthorized
from zope.security.proxy import removeSecurityProxy
from zope.testbrowser.browser import LinkNotFoundError

from lp.app.interfaces.launchpad import ILaunchpadCelebrities
from lp.buildmaster.enums import BuildStatus
from lp.oci.interfaces.ocirecipe import OCI_RECIPE_ALLOW_CREATE
from lp.oci.interfaces.ocirecipebuildjob import IOCIRegistryUploadJobSource
from lp.services.features.testing import FeatureFixture
from lp.services.job.interfaces.job import JobStatus
from lp.services.webapp import canonical_url
from lp.testing import (
    ANONYMOUS,
    BrowserTestCase,
    TestCaseWithFactory,
    login,
    person_logged_in,
)
from lp.testing.layers import DatabaseFunctionalLayer, LaunchpadFunctionalLayer
from lp.testing.pages import (
    extract_text,
    find_main_content,
    find_tags_by_class,
)
from lp.testing.views import create_initialized_view


class TestCanonicalUrlForOCIRecipeBuild(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.useFixture(FeatureFixture({OCI_RECIPE_ALLOW_CREATE: "on"}))

    def test_canonical_url(self):
        owner = self.factory.makePerson(name="person")
        distribution = self.factory.makeDistribution(name="distro")
        oci_project = self.factory.makeOCIProject(
            pillar=distribution, ociprojectname="oci-project"
        )
        recipe = self.factory.makeOCIRecipe(
            name="recipe",
            registrant=owner,
            owner=owner,
            oci_project=oci_project,
        )
        build = self.factory.makeOCIRecipeBuild(requester=owner, recipe=recipe)
        self.assertThat(
            canonical_url(build),
            StartsWith(
                "http://launchpad.test/~person/distro/+oci/oci-project/"
                "+recipe/recipe/+build/"
            ),
        )


class TestOCIRecipeBuildView(BrowserTestCase):
    layer = LaunchpadFunctionalLayer

    def setUp(self):
        super().setUp()
        self.useFixture(FeatureFixture({OCI_RECIPE_ALLOW_CREATE: "on"}))

    def test_index(self):
        build = self.factory.makeOCIRecipeBuild()
        recipe = build.recipe
        oci_project = recipe.oci_project
        self.assertTextMatchesExpressionIgnoreWhitespace(
            """\
            386 build of .*
            created .*
            Build status
            Needs building
            Build details
            Recipe: OCI recipe %s/%s/%s for %s
            Architecture: i386
            """
            % (
                oci_project.pillar.name,
                oci_project.name,
                recipe.name,
                recipe.owner.display_name,
            ),
            self.getMainText(build),
        )

    def test_files(self):
        # OCIRecipeBuildView.files returns all the associated files.
        build = self.factory.makeOCIRecipeBuild(status=BuildStatus.FULLYBUILT)
        oci_file = self.factory.makeOCIFile(build=build)
        build_view = create_initialized_view(build, "+index")
        self.assertEqual(
            [oci_file.library_file.filename],
            [lfa.filename for lfa in build_view.files],
        )
        # Deleted files won't be included.
        self.assertFalse(oci_file.library_file.deleted)
        removeSecurityProxy(oci_file.library_file).content = None
        self.assertTrue(oci_file.library_file.deleted)
        build_view = create_initialized_view(build, "+index")
        self.assertEqual([], build_view.files)

    def test_registry_upload_status_in_progress(self):
        build = self.factory.makeOCIRecipeBuild(status=BuildStatus.FULLYBUILT)
        getUtility(IOCIRegistryUploadJobSource).create(build)
        build_view = create_initialized_view(build, "+index")
        self.assertThat(
            build_view(),
            soupmatchers.HTMLContains(
                soupmatchers.Tag(
                    "registry upload status",
                    "li",
                    attrs={"id": "registry-upload-status"},
                    text=re.compile(r"^\s*Registry upload in progress\s*$"),
                )
            ),
        )

    def test_registry_upload_status_completed(self):
        build = self.factory.makeOCIRecipeBuild(status=BuildStatus.FULLYBUILT)
        job = getUtility(IOCIRegistryUploadJobSource).create(build)
        naked_job = removeSecurityProxy(job)
        naked_job.job._status = JobStatus.COMPLETED
        build_view = create_initialized_view(build, "+index")
        self.assertThat(
            build_view(),
            soupmatchers.HTMLContains(
                soupmatchers.Tag(
                    "registry upload status",
                    "li",
                    attrs={"id": "registry-upload-status"},
                    text=re.compile(r"^\s*Registry upload complete\s*$"),
                )
            ),
        )

    def test_registry_upload_status_failed(self):
        build = self.factory.makeOCIRecipeBuild(status=BuildStatus.FULLYBUILT)
        job = getUtility(IOCIRegistryUploadJobSource).create(build)
        naked_job = removeSecurityProxy(job)
        naked_job.job._status = JobStatus.FAILED
        naked_job.error_summary = "Upload of test-digest for test-image failed"
        build_view = create_initialized_view(build, "+index")
        self.assertThat(
            build_view(),
            soupmatchers.HTMLContains(
                soupmatchers.Within(
                    soupmatchers.Tag(
                        "registry upload status",
                        "li",
                        attrs={"id": "registry-upload-status"},
                        text=re.compile(
                            r"^\s*Registry upload failed:\s+"
                            r"Upload of test-digest for test-image failed\s*$"
                        ),
                    ),
                    soupmatchers.Tag(
                        "retry button",
                        "input",
                        attrs={
                            "type": "submit",
                            "name": "field.actions.upload",
                            "value": "Retry",
                        },
                    ),
                )
            ),
        )


class TestOCIRecipeBuildOperations(BrowserTestCase):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.useFixture(FakeLogger())
        self.useFixture(FeatureFixture({OCI_RECIPE_ALLOW_CREATE: "on"}))
        self.build = self.factory.makeOCIRecipeBuild()
        self.build_url = canonical_url(self.build)
        self.requester = self.build.requester
        self.buildd_admin = self.factory.makePerson(
            member_of=[getUtility(ILaunchpadCelebrities).buildd_admin]
        )

    def test_retry_build(self):
        # The requester of a build can retry it.
        self.build.updateStatus(BuildStatus.FAILEDTOBUILD)
        transaction.commit()
        browser = self.getViewBrowser(self.build, user=self.requester)
        browser.getLink("Retry this build").click()
        self.assertEqual(self.build_url, browser.getLink("Cancel").url)
        browser.getControl("Retry build").click()
        self.assertEqual(self.build_url, browser.url)
        login(ANONYMOUS)
        self.assertEqual(BuildStatus.NEEDSBUILD, self.build.status)

    def test_retry_build_random_user(self):
        # An unrelated non-admin user cannot retry a build.
        self.build.updateStatus(BuildStatus.FAILEDTOBUILD)
        transaction.commit()
        user = self.factory.makePerson()
        browser = self.getViewBrowser(self.build, user=user)
        self.assertRaises(
            LinkNotFoundError, browser.getLink, "Retry this build"
        )
        self.assertRaises(
            Unauthorized,
            self.getUserBrowser,
            self.build_url + "/+retry",
            user=user,
        )

    def test_retry_build_wrong_state(self):
        # If the build isn't in an unsuccessful terminal state, you can't
        # retry it.
        self.build.updateStatus(BuildStatus.FULLYBUILT)
        browser = self.getViewBrowser(self.build, user=self.requester)
        self.assertRaises(
            LinkNotFoundError, browser.getLink, "Retry this build"
        )

    def test_cancel_build(self):
        # The requester of a build can cancel it.
        self.build.queueBuild()
        transaction.commit()
        browser = self.getViewBrowser(self.build, user=self.requester)
        browser.getLink("Cancel build").click()
        self.assertEqual(self.build_url, browser.getLink("Cancel").url)
        browser.getControl("Cancel build").click()
        self.assertEqual(self.build_url, browser.url)
        login(ANONYMOUS)
        self.assertEqual(BuildStatus.CANCELLED, self.build.status)

    def test_cancel_build_random_user(self):
        # An unrelated non-admin user cannot cancel a build.
        self.build.queueBuild()
        transaction.commit()
        user = self.factory.makePerson()
        browser = self.getViewBrowser(self.build, user=user)
        self.assertRaises(LinkNotFoundError, browser.getLink, "Cancel build")
        self.assertRaises(
            Unauthorized,
            self.getUserBrowser,
            self.build_url + "/+cancel",
            user=user,
        )

    def test_cancel_build_wrong_state(self):
        # If the build isn't queued, you can't cancel it.
        browser = self.getViewBrowser(self.build, user=self.requester)
        self.assertRaises(LinkNotFoundError, browser.getLink, "Cancel build")

    def test_rescore_build(self):
        # A buildd admin can rescore a build.
        self.build.queueBuild()
        transaction.commit()
        browser = self.getViewBrowser(self.build, user=self.buildd_admin)
        browser.getLink("Rescore build").click()
        self.assertEqual(self.build_url, browser.getLink("Cancel").url)
        browser.getControl("Priority").value = "1024"
        browser.getControl("Rescore build").click()
        self.assertEqual(self.build_url, browser.url)
        login(ANONYMOUS)
        self.assertEqual(1024, self.build.buildqueue_record.lastscore)

    def test_rescore_build_invalid_score(self):
        # Build scores can only take numbers.
        self.build.queueBuild()
        transaction.commit()
        browser = self.getViewBrowser(self.build, user=self.buildd_admin)
        browser.getLink("Rescore build").click()
        self.assertEqual(self.build_url, browser.getLink("Cancel").url)
        browser.getControl("Priority").value = "tentwentyfour"
        browser.getControl("Rescore build").click()
        self.assertEqual(
            "Invalid integer data",
            extract_text(find_tags_by_class(browser.contents, "message")[1]),
        )

    def test_rescore_build_not_admin(self):
        # A non-admin user cannot cancel a build.
        self.build.queueBuild()
        transaction.commit()
        user = self.factory.makePerson()
        browser = self.getViewBrowser(self.build, user=user)
        self.assertRaises(LinkNotFoundError, browser.getLink, "Rescore build")
        self.assertRaises(
            Unauthorized,
            self.getUserBrowser,
            self.build_url + "/+rescore",
            user=user,
        )

    def test_rescore_build_wrong_state(self):
        # If the build isn't NEEDSBUILD, you can't rescore it.
        self.build.queueBuild()
        with person_logged_in(self.requester):
            self.build.cancel()
        browser = self.getViewBrowser(self.build, user=self.buildd_admin)
        self.assertRaises(LinkNotFoundError, browser.getLink, "Rescore build")

    def test_rescore_build_wrong_state_stale_link(self):
        # An attempt to rescore a non-queued build from a stale link shows a
        # sensible error message.
        self.build.queueBuild()
        with person_logged_in(self.requester):
            self.build.cancel()
        browser = self.getViewBrowser(
            self.build, "+rescore", user=self.buildd_admin
        )
        self.assertEqual(self.build_url, browser.url)
        self.assertThat(
            browser.contents,
            soupmatchers.HTMLContains(
                soupmatchers.Tag(
                    "notification",
                    "div",
                    attrs={"class": "warning message"},
                    text="Cannot rescore this build because it is not queued.",
                )
            ),
        )

    def test_builder_history(self):
        Store.of(self.build).flush()
        self.build.updateStatus(
            BuildStatus.FULLYBUILT, builder=self.factory.makeBuilder()
        )
        title = self.build.title
        browser = self.getViewBrowser(self.build.builder, "+history")
        self.assertTextMatchesExpressionIgnoreWhitespace(
            "Build history.*%s" % re.escape(title),
            extract_text(find_main_content(browser.contents)),
        )
        self.assertEqual(self.build_url, browser.getLink(title).url)

    def makeBuildingOCIRecipe(self):
        builder = self.factory.makeBuilder()
        build = self.factory.makeOCIRecipeBuild()
        build.updateStatus(BuildStatus.BUILDING, builder=builder)
        build.queueBuild()
        build.buildqueue_record.builder = builder
        build.buildqueue_record.logtail = "tail of the log"
        return build

    def test_builder_index(self):
        build = self.makeBuildingOCIRecipe()
        browser = self.getViewBrowser(build.builder, no_login=True)
        self.assertIn("tail of the log", browser.contents)
