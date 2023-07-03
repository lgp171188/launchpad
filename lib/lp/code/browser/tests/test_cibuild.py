# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test CI build views."""

import re

import soupmatchers
import transaction
from fixtures import FakeLogger
from storm.locals import Store
from zope.component import getUtility
from zope.security.interfaces import Unauthorized
from zope.security.proxy import removeSecurityProxy
from zope.testbrowser.browser import LinkNotFoundError

from lp.app.interfaces.launchpad import ILaunchpadCelebrities
from lp.buildmaster.enums import BuildStatus
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


class TestCanonicalUrlForCIBuild(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_canonical_url(self):
        repository = self.factory.makeGitRepository()
        build = self.factory.makeCIBuild(git_repository=repository)
        self.assertEqual(
            "http://launchpad.test/%s/+build/%s"
            % (repository.shortened_path, build.id),
            canonical_url(build),
        )


class TestCIBuildOperations(BrowserTestCase):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.useFixture(FakeLogger())
        self.build = self.factory.makeCIBuild()
        self.build_url = canonical_url(self.build)
        self.repository = self.build.git_repository
        self.buildd_admin = self.factory.makePerson(
            member_of=[getUtility(ILaunchpadCelebrities).buildd_admin]
        )

    def test_retry_build(self):
        # The owner of a build's repository can retry it.
        self.build.updateStatus(BuildStatus.FAILEDTOBUILD)
        transaction.commit()
        browser = self.getViewBrowser(self.build, user=self.repository.owner)
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
        browser = self.getViewBrowser(self.build, user=self.repository.owner)
        self.assertRaises(
            LinkNotFoundError, browser.getLink, "Retry this build"
        )

    def test_cancel_build(self):
        # The owner of a build's repository can cancel it.
        self.build.queueBuild()
        transaction.commit()
        browser = self.getViewBrowser(self.build, user=self.repository.owner)
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
        browser = self.getViewBrowser(self.build, user=self.repository.owner)
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
        with person_logged_in(self.repository.owner):
            self.build.cancel()
        browser = self.getViewBrowser(self.build, user=self.buildd_admin)
        self.assertRaises(LinkNotFoundError, browser.getLink, "Rescore build")

    def test_rescore_build_wrong_state_stale_link(self):
        # An attempt to rescore a non-queued build from a stale link shows a
        # sensible error message.
        self.build.queueBuild()
        with person_logged_in(self.repository.owner):
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
            r"Build history.*%s" % re.escape(title),
            extract_text(find_main_content(browser.contents)),
        )
        self.assertEqual(self.build_url, browser.getLink(title).url)

    def makeBuildingRecipe(self):
        builder = self.factory.makeBuilder()
        build = self.factory.makeCIBuild()
        build.updateStatus(BuildStatus.BUILDING, builder=builder)
        build.queueBuild()
        build.buildqueue_record.builder = builder
        build.buildqueue_record.logtail = "tail of the log"
        return build

    def test_builder_index_public(self):
        build = self.makeBuildingRecipe()
        browser = self.getViewBrowser(build.builder, no_login=True)
        self.assertIn("tail of the log", browser.contents)


class TestCIBuildView(TestCaseWithFactory):
    layer = LaunchpadFunctionalLayer

    def test_files(self):
        # CIBuildView.files returns all the associated files.
        build = self.factory.makeCIBuild(status=BuildStatus.FULLYBUILT)
        reports = [
            build.getOrCreateRevisionStatusReport(job_id)
            for job_id in ("build:0", "build:1")
        ]
        for report in reports:
            # Deliberately use identical filenames for each artifact, since
            # that's the hardest case.
            removeSecurityProxy(report).attach(
                "package.tar.gz", report.title.encode()
            )
        artifacts = build.getArtifacts()
        self.assertContentEqual(
            reports, {artifact.report for artifact in artifacts}
        )
        build_view = create_initialized_view(build, "+index")
        self.assertEqual(
            [
                "%s/+files/%s"
                % (canonical_url(artifact), artifact.library_file.filename)
                for artifact in artifacts
            ],
            [lfa.http_url for lfa in build_view.files],
        )
        # Deleted files won't be included.
        self.assertFalse(artifacts[1].library_file.deleted)
        removeSecurityProxy(artifacts[1].library_file).content = None
        self.assertTrue(artifacts[1].library_file.deleted)
        build_view = create_initialized_view(build, "+index")
        self.assertEqual(
            [
                "%s/+files/%s"
                % (
                    canonical_url(artifacts[0]),
                    artifacts[0].library_file.filename,
                )
            ],
            [lfa.http_url for lfa in build_view.files],
        )
