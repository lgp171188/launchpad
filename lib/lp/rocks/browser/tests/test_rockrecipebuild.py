# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test rock recipe build views."""

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

from lp.app.enums import InformationType
from lp.app.interfaces.launchpad import ILaunchpadCelebrities
from lp.buildmaster.enums import BuildStatus
from lp.rocks.interfaces.rockrecipe import ROCK_RECIPE_ALLOW_CREATE
from lp.services.features.testing import FeatureFixture
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


class TestCanonicalUrlForRockRecipeBuild(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.useFixture(FeatureFixture({ROCK_RECIPE_ALLOW_CREATE: "on"}))

    def test_canonical_url(self):
        owner = self.factory.makePerson(name="person")
        project = self.factory.makeProduct(name="rock-project")
        recipe = self.factory.makeRockRecipe(
            registrant=owner, owner=owner, project=project, name="rock"
        )
        build = self.factory.makeRockRecipeBuild(
            requester=owner, recipe=recipe
        )
        self.assertThat(
            canonical_url(build),
            StartsWith(
                "http://launchpad.test/~person/rock-project/+rock/rock/"
                "+build/"
            ),
        )


class TestRockRecipeBuildView(TestCaseWithFactory):

    layer = LaunchpadFunctionalLayer

    def setUp(self):
        super().setUp()
        self.useFixture(FeatureFixture({ROCK_RECIPE_ALLOW_CREATE: "on"}))

    def test_files(self):
        # RockRecipeBuildView.files returns all the associated files.
        build = self.factory.makeRockRecipeBuild(status=BuildStatus.FULLYBUILT)
        rock_file = self.factory.makeRockFile(build=build)
        build_view = create_initialized_view(build, "+index")
        self.assertEqual(
            [rock_file.library_file.filename],
            [lfa.filename for lfa in build_view.files],
        )
        # Deleted files won't be included.
        self.assertFalse(rock_file.library_file.deleted)
        removeSecurityProxy(rock_file.library_file).content = None
        self.assertTrue(rock_file.library_file.deleted)
        build_view = create_initialized_view(build, "+index")
        self.assertEqual([], build_view.files)

    def test_revision_id(self):
        build = self.factory.makeRockRecipeBuild()
        build.updateStatus(
            BuildStatus.FULLYBUILT, slave_status={"revision_id": "dummy"}
        )
        build_view = create_initialized_view(build, "+index")
        self.assertThat(
            build_view(),
            soupmatchers.HTMLContains(
                soupmatchers.Tag(
                    "revision ID",
                    "li",
                    attrs={"id": "revision-id"},
                    text=re.compile(r"^\s*Revision: dummy\s*$"),
                )
            ),
        )


class TestRockRecipeBuildOperations(BrowserTestCase):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.useFixture(FeatureFixture({ROCK_RECIPE_ALLOW_CREATE: "on"}))
        self.useFixture(FakeLogger())
        self.build = self.factory.makeRockRecipeBuild()
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
            r"Build history.*%s" % re.escape(title),
            extract_text(find_main_content(browser.contents)),
        )
        self.assertEqual(self.build_url, browser.getLink(title).url)

    def makeBuildingRecipe(self, information_type=InformationType.PUBLIC):
        builder = self.factory.makeBuilder()
        build = self.factory.makeRockRecipeBuild(
            information_type=information_type
        )
        build.updateStatus(BuildStatus.BUILDING, builder=builder)
        build.queueBuild()
        build.buildqueue_record.builder = builder
        build.buildqueue_record.logtail = "tail of the log"
        return build

    def test_builder_index_public(self):
        build = self.makeBuildingRecipe()
        browser = self.getViewBrowser(build.builder, no_login=True)
        self.assertIn("tail of the log", browser.contents)
