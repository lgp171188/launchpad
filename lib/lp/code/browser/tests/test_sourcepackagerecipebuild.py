# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the source package recipe view classes and templates."""

import transaction
from fixtures import FakeLogger
from storm.locals import Store
from testtools.matchers import StartsWith
from zope.component import getUtility
from zope.security.interfaces import Unauthorized
from zope.security.proxy import removeSecurityProxy
from zope.testbrowser.browser import LinkNotFoundError

from lp.buildmaster.enums import BuildStatus
from lp.buildmaster.interfaces.processor import IProcessorSet
from lp.registry.interfaces.person import IPersonSet
from lp.services.webapp import canonical_url
from lp.testing import (
    ANONYMOUS,
    BrowserTestCase,
    TestCaseWithFactory,
    admin_logged_in,
    login,
    logout,
)
from lp.testing.layers import DatabaseFunctionalLayer
from lp.testing.pages import (
    extract_text,
    find_main_content,
    find_tags_by_class,
)
from lp.testing.sampledata import ADMIN_EMAIL


class TestCanonicalUrlForRecipeBuild(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_canonical_url(self):
        owner = self.factory.makePerson(name="ppa-owner")
        ppa = self.factory.makeArchive(owner=owner, name="ppa")
        build = self.factory.makeSourcePackageRecipeBuild(archive=ppa)
        self.assertThat(
            canonical_url(build),
            StartsWith(
                "http://launchpad.test/~ppa-owner/+archive/ubuntu/ppa/"
                "+recipebuild/"
            ),
        )


class TestSourcePackageRecipeBuild(BrowserTestCase):
    """Create some sample data for recipe tests."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        """Provide useful defaults."""
        super().setUp()
        self.admin = getUtility(IPersonSet).getByEmail(ADMIN_EMAIL)
        self.chef = self.factory.makePerson(
            displayname="Master Chef", name="chef"
        )
        self.user = self.chef
        self.ppa = self.factory.makeArchive(
            displayname="Secret PPA", owner=self.chef, name="ppa"
        )
        self.squirrel = self.factory.makeDistroSeries(
            displayname="Secret Squirrel",
            name="secret",
            version="100.04",
            distribution=self.ppa.distribution,
        )
        naked_squirrel = removeSecurityProxy(self.squirrel)
        naked_squirrel.nominatedarchindep = self.squirrel.newArch(
            "i386",
            getUtility(IProcessorSet).getByName("386"),
            False,
            self.chef,
        )

    def makeRecipeBuild(self):
        """Create and return a specific recipe."""
        chocolate = self.factory.makeProduct(name="chocolate")
        cake_branch = self.factory.makeProductBranch(
            owner=self.chef, name="cake", product=chocolate
        )
        recipe = self.factory.makeSourcePackageRecipe(
            owner=self.chef,
            distroseries=self.squirrel,
            name="cake_recipe",
            description="This recipe builds a foo for distro bar, with my"
            " Secret Squirrel changes.",
            branches=[cake_branch],
            daily_build_archive=self.ppa,
        )
        build = self.factory.makeSourcePackageRecipeBuild(recipe=recipe)
        build.queueBuild()
        return build

    def test_cancel_build(self):
        """The archive owner can cancel a build."""
        queue = self.factory.makeSourcePackageRecipeBuild().queueBuild()
        build = queue.specific_build
        transaction.commit()
        build_url = canonical_url(build)
        owner = build.archive.owner
        logout()

        browser = self.getUserBrowser(build_url, user=owner)
        browser.getLink("Cancel build").click()

        self.assertEqual(browser.getLink("Cancel").url, build_url)

        browser.getControl("Cancel build").click()

        self.assertEqual(browser.url, build_url)

        login(ANONYMOUS)
        self.assertEqual(BuildStatus.CANCELLED, build.status)

    def test_cancel_build_not_owner(self):
        """A normal user can't cancel a build."""
        self.useFixture(FakeLogger())
        queue = self.factory.makeSourcePackageRecipeBuild().queueBuild()
        build = queue.specific_build
        transaction.commit()
        build_url = canonical_url(build)
        logout()

        browser = self.getUserBrowser(build_url, user=self.chef)
        self.assertRaises(LinkNotFoundError, browser.getLink, "Cancel build")

        self.assertRaises(
            Unauthorized,
            self.getUserBrowser,
            build_url + "/+cancel",
            user=self.chef,
        )

    def test_cancel_build_wrong_state(self):
        """If the build isn't queued, you can't cancel it."""
        build = self.makeRecipeBuild()
        with admin_logged_in():
            build.cancel()
        transaction.commit()
        build_url = canonical_url(build)
        owner = build.archive.owner
        logout()

        browser = self.getUserBrowser(build_url, user=owner)
        self.assertRaises(LinkNotFoundError, browser.getLink, "Cancel build")

    def test_rescore_build(self):
        """An admin can rescore a build."""
        queue = self.factory.makeSourcePackageRecipeBuild().queueBuild()
        build = queue.specific_build
        transaction.commit()
        build_url = canonical_url(build)
        logout()

        browser = self.getUserBrowser(build_url, user=self.admin)
        browser.getLink("Rescore build").click()

        self.assertEqual(browser.getLink("Cancel").url, build_url)

        browser.getControl("Score").value = "1024"

        browser.getControl("Rescore build").click()

        self.assertEqual(browser.url, build_url)

        login(ANONYMOUS)
        self.assertEqual(build.buildqueue_record.lastscore, 1024)

    def test_rescore_build_invalid_score(self):
        """Build scores can only take numbers."""
        queue = self.factory.makeSourcePackageRecipeBuild().queueBuild()
        build = queue.specific_build
        transaction.commit()
        build_url = canonical_url(build)
        logout()

        browser = self.getUserBrowser(build_url, user=self.admin)
        browser.getLink("Rescore build").click()

        self.assertEqual(browser.getLink("Cancel").url, build_url)

        browser.getControl("Score").value = "tentwentyfour"

        browser.getControl("Rescore build").click()

        self.assertEqual(
            extract_text(find_tags_by_class(browser.contents, "message")[1]),
            "Invalid integer data",
        )

    def test_rescore_build_not_admin(self):
        """No one but admin can rescore a build."""
        self.useFixture(FakeLogger())
        queue = self.factory.makeSourcePackageRecipeBuild().queueBuild()
        build = queue.specific_build
        transaction.commit()
        build_url = canonical_url(build)
        logout()

        browser = self.getUserBrowser(build_url, user=self.chef)
        self.assertRaises(LinkNotFoundError, browser.getLink, "Rescore build")

        self.assertRaises(
            Unauthorized,
            self.getUserBrowser,
            build_url + "/+rescore",
            user=self.chef,
        )

    def test_rescore_build_wrong_state(self):
        """If the build isn't queued, you can't rescore it."""
        build = self.makeRecipeBuild()
        with admin_logged_in():
            build.cancel()
        transaction.commit()
        build_url = canonical_url(build)
        logout()

        browser = self.getUserBrowser(build_url, user=self.admin)
        self.assertRaises(LinkNotFoundError, browser.getLink, "Rescore build")

    def test_rescore_build_wrong_state_stale_link(self):
        """Show sane error if you attempt to rescore a non-queued build.

        This is the case where the user has a stale link that they click on.
        """
        build = self.factory.makeSourcePackageRecipeBuild()
        build.queueBuild()
        with admin_logged_in():
            build.cancel()
        index_url = canonical_url(build)
        browser = self.getViewBrowser(build, "+rescore", user=self.admin)
        self.assertEqual(index_url, browser.url)
        self.assertIn(
            "Cannot rescore this build because it is not queued.",
            browser.contents,
        )

    def test_builder_history(self):
        build = self.makeRecipeBuild()
        Store.of(build).flush()
        build_url = canonical_url(build)
        build.updateStatus(
            BuildStatus.FULLYBUILT, builder=self.factory.makeBuilder()
        )
        browser = self.getViewBrowser(build.builder, "+history")
        self.assertTextMatchesExpressionIgnoreWhitespace(
            "Build history.*~chef/chocolate/cake recipe build",
            extract_text(find_main_content(browser.contents)),
        )
        self.assertEqual(
            build_url, browser.getLink("~chef/chocolate/cake recipe build").url
        )

    def makeBuildingRecipe(self, archive=None):
        builder = self.factory.makeBuilder()
        build = self.factory.makeSourcePackageRecipeBuild(archive=archive)
        build.updateStatus(BuildStatus.BUILDING, builder=builder)
        build.queueBuild()
        build.buildqueue_record.builder = builder
        build.buildqueue_record.logtail = "i am failing"
        return build

    def test_builder_index_public(self):
        build = self.makeBuildingRecipe()
        browser = self.getViewBrowser(build.builder, no_login=True)
        self.assertIn("i am failing", browser.contents)

    def test_builder_index_private(self):
        archive = self.factory.makeArchive(private=True)
        with admin_logged_in():
            build = self.makeBuildingRecipe(archive=archive)
        builder = removeSecurityProxy(build).builder

        # An unrelated user can't see the logtail of a private build.
        browser = self.getViewBrowser(builder)
        self.assertNotIn("i am failing", browser.contents)

        # But someone who can see the archive can.
        browser = self.getViewBrowser(builder, user=archive.owner)
        self.assertIn("i am failing", browser.contents)
