# Copyright 2011-2012 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import json
from datetime import datetime, timezone

from zope.security.proxy import removeSecurityProxy

from lp.app.enums import InformationType
from lp.code.enums import (
    BranchSubscriptionDiffSize,
    BranchSubscriptionNotificationLevel,
    CodeReviewNotificationLevel,
)
from lp.code.model.seriessourcepackagebranch import (
    SeriesSourcePackageBranchSet,
)
from lp.registry.interfaces.person import TeamMembershipPolicy
from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.testing import TestCaseWithFactory, anonymous_logged_in, api_url
from lp.testing.layers import DatabaseFunctionalLayer
from lp.testing.pages import webservice_for_person


class TestDistribution(TestCaseWithFactory):
    """Test how distributions behave through the web service."""

    layer = DatabaseFunctionalLayer

    def test_write_without_permission_gives_Unauthorized(self):
        distro = self.factory.makeDistribution()
        distro_url = api_url(distro)
        ws = webservice_for_person(None, default_api_version="devel")
        response = ws.patch(
            distro_url, "application/json", json.dumps({"active": False})
        )
        self.assertEqual(401, response.status)


class TestGetBranchTips(TestCaseWithFactory):
    """Test the getBranchTips method and its exposure to the web service."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.distro = self.factory.makeDistribution()
        self.distro_name = self.distro.name
        self.distro_url = api_url(self.distro)
        series_1 = self.series_1 = self.factory.makeDistroSeries(self.distro)
        series_2 = self.series_2 = self.factory.makeDistroSeries(self.distro)
        source_package = self.factory.makeSourcePackage(distroseries=series_1)
        branch = self.factory.makeBranch(sourcepackage=source_package)
        unofficial_branch = self.factory.makeBranch(
            sourcepackage=source_package
        )
        registrant = self.factory.makePerson()
        now = datetime.now(timezone.utc)
        sourcepackagename = self.factory.makeSourcePackageName()
        SeriesSourcePackageBranchSet.new(
            series_1,
            PackagePublishingPocket.RELEASE,
            sourcepackagename,
            branch,
            registrant,
            now,
        )
        SeriesSourcePackageBranchSet.new(
            series_2,
            PackagePublishingPocket.RELEASE,
            sourcepackagename,
            branch,
            registrant,
            now,
        )
        self.factory.makeRevisionsForBranch(branch)
        self.branch_name = branch.unique_name
        self.unofficial_branch_name = unofficial_branch.unique_name
        self.branch_last_scanned_id = branch.last_scanned_id
        self.ws = webservice_for_person(None, default_api_version="devel")

    def test_structure(self):
        """The structure of the results is what we expect."""
        # The results should be structured as a list of
        # (location, tip revision ID, [official series, official series, ...])
        response = self.ws.named_get(self.distro_url, "getBranchTips")
        self.assertEqual(200, response.status)
        item = response.jsonBody()[0]
        self.assertEqual(item[0], self.branch_name)
        self.assertTrue(item[1], self.branch_last_scanned_id)
        self.assertEqual(
            sorted(item[2]), [self.series_1.name, self.series_2.name]
        )

    def test_same_results(self):
        """Calling getBranchTips directly matches calling it via the API."""
        # The web service transmutes tuples into lists, so we have to do the
        # same to the results of directly calling getBranchTips.
        with anonymous_logged_in():
            listified = [list(x) for x in self.distro.getBranchTips()]
        response = self.ws.named_get(self.distro_url, "getBranchTips")
        self.assertEqual(200, response.status)
        self.assertEqual(listified, response.jsonBody())

    def test_revisions(self):
        """If a branch has revisions then the most recent one is returned."""
        response = self.ws.named_get(self.distro_url, "getBranchTips")
        self.assertEqual(200, response.status)
        revision = response.jsonBody()[0][1]
        self.assertNotEqual(None, revision)

    def test_since(self):
        """If "since" is given, return branches with new tips since then."""
        # There is at least one branch with a tip since the year 2000.
        response = self.ws.named_get(
            self.distro_url,
            "getBranchTips",
            since=datetime(2000, 1, 1).isoformat(),
        )
        self.assertEqual(200, response.status)
        self.assertNotEqual(0, len(response.jsonBody()))
        # There are no branches with a tip since the year 3000.
        response = self.ws.named_get(
            self.distro_url,
            "getBranchTips",
            since=datetime(3000, 1, 1).isoformat(),
        )
        self.assertEqual(200, response.status)
        self.assertEqual(0, len(response.jsonBody()))

    def test_series(self):
        """The official series are included in the data."""
        actual_series_names = sorted([self.series_1.name, self.series_2.name])
        response = self.ws.named_get(self.distro_url, "getBranchTips")
        self.assertEqual(200, response.status)
        returned_series_names = sorted(response.jsonBody()[0][-1])
        self.assertEqual(actual_series_names, returned_series_names)

    def test_unofficial_branch(self):
        """Not all branches are official."""
        # If a branch isn't official, the last skanned ID will be None and the
        # official distro series list will be empty.
        response = self.ws.named_get(self.distro_url, "getBranchTips")
        self.assertEqual(200, response.status)
        tips = response.jsonBody()[1]
        self.assertEqual(tips[0], self.unofficial_branch_name)
        self.assertEqual(tips[1], None)
        self.assertEqual(tips[2], [])


class TestGetBranchTipsSecurity(TestCaseWithFactory):
    """Test the getBranchTips method and its exposure to the web service."""

    layer = DatabaseFunctionalLayer

    # Security tests are inspired by TestGenericBranchCollectionVisibleFilter
    # in lp.code.model.tests.test_branchcollection, and TestAccessBranch in
    # lp.code.tests.test_branch.  Ideally we'd have one code base and one
    # set of tests to handle them all.  We don't. :-/  As a way to try and
    # partially compensate, we verify here that branch.visibleByUser
    # agrees with our results.

    # These tests (and the application code that allows them to pass)
    # consciously ignores the stacked aspect of the branch visibility rules.
    # See https://bugs.launchpad.net/launchpad/+bug/812335/comments/1 .

    # Similarly, we do not support the LAUNCHPAD_SERVICES user because this
    # is a special-cased string in the codehosting xmlrpc machinery and
    # does not correspond to an actual LP Person.

    def makeBranch(self, **kwargs):
        distro = self.factory.makeDistribution()
        series = self.factory.makeDistroSeries(distro)
        source_package = self.factory.makeSourcePackage(distroseries=series)
        branch = self.factory.makeBranch(
            sourcepackage=source_package,
            information_type=InformationType.USERDATA,
            **kwargs,
        )
        return branch, distro

    def test_private_branch_hidden(self):
        # A private branch should not be included for anonymous users or for
        # authenticated users who do not have the necessary privileges.
        branch, distro = self.makeBranch()
        self.assertFalse(  # Double-checking.
            removeSecurityProxy(branch).visibleByUser(None)
        )
        self.assertEqual([], distro.getBranchTips())
        person = self.factory.makePerson()
        self.assertFalse(  # Double-checking.
            removeSecurityProxy(branch).visibleByUser(person)
        )
        self.assertEqual([], distro.getBranchTips(user=person))

    def assertVisible(self, distro, branch, person):
        self.assertTrue(  # Double-checking.
            removeSecurityProxy(branch).visibleByUser(person)
        )
        self.assertEqual(1, len(distro.getBranchTips(user=person)))

    def test_owned_visible(self):
        # If user owns the branch, it is visible.
        person = self.factory.makePerson()
        branch, distro = self.makeBranch(owner=person)
        self.assertVisible(distro, branch, person)

    def test_owner_member_visible(self):
        # If user is a member of the team that owns the branch, it is visible.
        person = self.factory.makePerson()
        team = self.factory.makeTeam(members=[person])
        branch, distro = self.makeBranch(owner=team)
        self.assertVisible(distro, branch, person)

    def test_subscriber_visible(self):
        # If user is a subscriber to the branch, it is visible.
        branch, distro = self.makeBranch()
        person = self.factory.makePerson()
        removeSecurityProxy(branch).subscribe(
            person,
            BranchSubscriptionNotificationLevel.NOEMAIL,
            BranchSubscriptionDiffSize.NODIFF,
            CodeReviewNotificationLevel.NOEMAIL,
            person,
        )
        self.assertVisible(distro, branch, person)

    def test_subscriber_member_visible(self):
        # If user is a member of a team that is a subscriber to the branch,
        # it is visible.
        branch, distro = self.makeBranch()
        person = self.factory.makePerson()
        team = self.factory.makeTeam(
            membership_policy=TeamMembershipPolicy.MODERATED, members=[person]
        )
        removeSecurityProxy(branch).subscribe(
            team,
            BranchSubscriptionNotificationLevel.NOEMAIL,
            BranchSubscriptionDiffSize.NODIFF,
            CodeReviewNotificationLevel.NOEMAIL,
            team,
        )
        self.assertVisible(distro, branch, person)
