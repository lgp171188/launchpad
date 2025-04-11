# Copyright 2012-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""CVE related tests."""

from datetime import datetime, timezone

from testtools.matchers import MatchesStructure
from testtools.testcase import ExpectedException
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.bugs.interfaces.bugtasksearch import BugTaskSearchParams
from lp.bugs.interfaces.cve import CveStatus, ICveSet
from lp.bugs.scripts.uct.models import CVSS
from lp.testing import (
    TestCaseWithFactory,
    login_person,
    person_logged_in,
    verifyObject,
)
from lp.testing.layers import DatabaseFunctionalLayer


class TestCveSet(TestCaseWithFactory):
    """Tests for CveSet."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        """Create a few bugtasks and CVEs."""
        super().setUp()
        self.distroseries = self.factory.makeDistroSeries()
        self.bugs = []
        self.cves = []
        self.cve_index = 0
        with person_logged_in(self.distroseries.owner):
            for _ in range(4):
                task = self.factory.makeBugTask(target=self.distroseries)
                bug = task.bug
                self.bugs.append(bug)
                cve = self.makeCVE()
                self.cves.append(cve)
                bug.linkCVE(cve, self.distroseries.owner)

    def makeCVE(self):
        """Create a CVE."""
        self.cve_index += 1
        return self.factory.makeCVE("2000-%04i" % self.cve_index)

    def test_CveSet_implements_ICveSet(self):
        cveset = getUtility(ICveSet)
        self.assertTrue(verifyObject(ICveSet, cveset))

    def test_getBugCvesForBugTasks(self):
        # ICveSet.getBugCvesForBugTasks() returns tuples (bug, cve)
        # for the given bugtasks.
        bugtasks = self.distroseries.searchTasks(
            BugTaskSearchParams(self.distroseries.owner, has_cve=True)
        )
        bug_cves = getUtility(ICveSet).getBugCvesForBugTasks(bugtasks)
        found_bugs = [bug for bug, cve in bug_cves]
        found_cves = [cve for bug, cve in bug_cves]
        self.assertEqual(self.bugs, found_bugs)
        self.assertEqual(self.cves, found_cves)

    def test_getBugCvesForBugTasks_with_mapper(self):
        # ICveSet.getBugCvesForBugTasks() takes a function f as an
        # optional argeument. This function is applied to each CVE
        # related to the given bugs; the method return a sequence of
        # tuples (bug, f(cve)).
        def cve_name(cve):
            return cve.displayname

        bugtasks = self.distroseries.searchTasks(
            BugTaskSearchParams(self.distroseries.owner, has_cve=True)
        )
        bug_cves = getUtility(ICveSet).getBugCvesForBugTasks(
            bugtasks, cve_name
        )
        found_bugs = [bug for bug, cve in bug_cves]
        cve_data = [cve for bug, cve in bug_cves]
        self.assertEqual(self.bugs, found_bugs)
        expected = [
            "CVE-2000-0001",
            "CVE-2000-0002",
            "CVE-2000-0003",
            "CVE-2000-0004",
        ]
        self.assertEqual(expected, cve_data)

    def test_getBugCveCount(self):
        login_person(self.factory.makePerson())

        base = getUtility(ICveSet).getBugCveCount()
        bug1 = self.factory.makeBug()
        bug2 = self.factory.makeBug()
        cve1 = self.factory.makeCVE(sequence="2099-1234")
        cve2 = self.factory.makeCVE(sequence="2099-2468")
        self.assertEqual(base, getUtility(ICveSet).getBugCveCount())
        cve1.linkBug(bug1)
        self.assertEqual(base + 1, getUtility(ICveSet).getBugCveCount())
        cve1.linkBug(bug2)
        self.assertEqual(base + 2, getUtility(ICveSet).getBugCveCount())
        cve2.linkBug(bug1)
        self.assertEqual(base + 3, getUtility(ICveSet).getBugCveCount())
        cve1.unlinkBug(bug1)
        cve1.unlinkBug(bug2)
        cve2.unlinkBug(bug1)
        self.assertEqual(base, getUtility(ICveSet).getBugCveCount())


class TestBugLinks(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_link_and_unlink(self):
        login_person(self.factory.makePerson())

        bug1 = self.factory.makeBug()
        bug2 = self.factory.makeBug()
        cve1 = self.factory.makeCVE(sequence="2099-1234")
        cve2 = self.factory.makeCVE(sequence="2099-2468")
        self.assertContentEqual([], bug1.cves)
        self.assertContentEqual([], bug2.cves)
        self.assertContentEqual([], cve1.bugs)
        self.assertContentEqual([], cve2.bugs)

        cve1.linkBug(bug1)
        cve2.linkBug(bug1)
        cve1.linkBug(bug2)
        self.assertContentEqual([bug1, bug2], cve1.bugs)
        self.assertContentEqual([bug1], cve2.bugs)
        self.assertContentEqual([cve1, cve2], bug1.cves)
        self.assertContentEqual([cve1], bug2.cves)

        cve1.unlinkBug(bug1)
        self.assertContentEqual([bug2], cve1.bugs)
        self.assertContentEqual([bug1], cve2.bugs)
        self.assertContentEqual([cve2], bug1.cves)
        self.assertContentEqual([cve1], bug2.cves)

        cve1.unlinkBug(bug2)
        self.assertContentEqual([], cve1.bugs)
        self.assertContentEqual([bug1], cve2.bugs)
        self.assertContentEqual([cve2], bug1.cves)
        self.assertContentEqual([], bug2.cves)


class TestCve(TestCaseWithFactory):
    """Tests for Cve fields and methods."""

    layer = DatabaseFunctionalLayer

    def test_cveset_new_method_optional_parameters(self):
        cve = getUtility(ICveSet).new(
            sequence="2099-1234",
            description="A critical vulnerability",
            status=CveStatus.CANDIDATE,
        )
        self.assertThat(
            cve,
            MatchesStructure.byEquality(
                sequence="2099-1234",
                status=CveStatus.CANDIDATE,
                description="A critical vulnerability",
                date_made_public=None,
                discovered_by=None,
                cvss={},
            ),
        )

    def test_cveset_new_method_parameters(self):
        today = datetime.now(tz=timezone.utc)
        cvss = {"nvd": ["CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"]}
        cve = getUtility(ICveSet).new(
            sequence="2099-1234",
            description="A critical vulnerability",
            status=CveStatus.CANDIDATE,
            date_made_public=today,
            discovered_by="A person",
            cvss=cvss,
        )
        self.assertThat(
            cve,
            MatchesStructure.byEquality(
                sequence="2099-1234",
                status=CveStatus.CANDIDATE,
                description="A critical vulnerability",
                date_made_public=today,
                discovered_by="A person",
                cvss=cvss,
            ),
        )

    def test_cve_date_made_public_invalid_values(self):
        invalid_values = [
            "",
            "abcd",
            {"a": 1},
            [1, "a", "2", "b"],
            "2022-01-01",
        ]
        cve = self.factory.makeCVE(
            sequence="2099-1234",
            description="A critical vulnerability",
            cvestate=CveStatus.CANDIDATE,
        )
        for invalid_value in invalid_values:
            with ExpectedException(TypeError, "Expected datetime,.*"):
                removeSecurityProxy(cve).date_made_public = invalid_value

    def test_cve_cvss_invalid_values(self):
        invalid_values = ["", "abcd", "2022-01-01", datetime.now()]
        cve = self.factory.makeCVE(
            sequence="2099-1234",
            description="A critical vulnerability",
            cvestate=CveStatus.CANDIDATE,
        )
        for invalid_value in invalid_values:
            with ExpectedException(AssertionError):
                removeSecurityProxy(cve).cvss = invalid_value

    def test_cvss_value_returned_when_null(self):
        cve = self.factory.makeCVE(
            sequence="2099-1234",
            description="A critical vulnerability",
            cvestate=CveStatus.CANDIDATE,
        )
        cve = removeSecurityProxy(cve)
        self.assertIsNone(cve._cvss)
        self.assertEqual({}, cve.cvss)

    def test_setCVSSVectorForAuthority_initially_unset(self):
        cve = self.factory.makeCVE(
            sequence="2099-1234",
            description="A critical vulnerability",
            cvestate=CveStatus.CANDIDATE,
        )
        unproxied_cve = removeSecurityProxy(cve)
        self.assertIsNone(unproxied_cve._cvss)
        self.assertEqual({}, unproxied_cve.cvss)

        cve.setCVSSVectorForAuthority(
            [
                CVSS(
                    authority="nvd",
                    vector_string=(
                        "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"
                    ),
                ),
            ]
        )

        self.assertEqual(
            {"nvd": ["CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"]},
            unproxied_cve.cvss,
        )

    def test_setCVSSVectorForAuthority_overwrite_existing_key_value(self):
        cve = self.factory.makeCVE(
            sequence="2099-1234",
            description="A critical vulnerability",
            cvestate=CveStatus.CANDIDATE,
            cvss={"nvd": ["CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"]},
        )
        unproxied_cve = removeSecurityProxy(cve)
        self.assertEqual(
            {"nvd": ["CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"]},
            unproxied_cve.cvss,
        )

        cve.setCVSSVectorForAuthority(
            [
                CVSS(
                    authority="nvd",
                    vector_string=(
                        "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N"
                    ),
                )
            ]
        )

        self.assertEqual(
            {"nvd": ["CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N"]},
            unproxied_cve.cvss,
        )

    def test_setCVSSVectorForAuthority_add_new_when_initial_value_set(self):
        """Checks that we override CVSS although its not the same authority"""
        cve = self.factory.makeCVE(
            sequence="2099-1234",
            description="A critical vulnerability",
            cvestate=CveStatus.CANDIDATE,
            cvss={"nvd": ["CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"]},
        )
        unproxied_cve = removeSecurityProxy(cve)
        self.assertEqual(
            {"nvd": ["CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"]},
            unproxied_cve.cvss,
        )

        cve.setCVSSVectorForAuthority(
            [
                CVSS(
                    authority="nist",
                    vector_string=(
                        "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N"
                    ),
                ),
            ]
        )

        self.assertEqual(
            {
                "nist": ["CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N"],
            },
            unproxied_cve.cvss,
        )

    def test_setCVSSVectorForAuthority_remove_one_when_initial_value_set(self):
        cve = self.factory.makeCVE(
            sequence="2099-1234",
            description="A critical vulnerability",
            cvestate=CveStatus.CANDIDATE,
            cvss={
                "nvd": [
                    "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
                    "CVSS:3.0/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
                ]
            },
        )
        unproxied_cve = removeSecurityProxy(cve)
        self.assertEqual(
            {
                "nvd": [
                    "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
                    "CVSS:3.0/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
                ]
            },
            unproxied_cve.cvss,
        )

        cve.setCVSSVectorForAuthority(
            [
                CVSS(
                    authority="nvd",
                    vector_string=(
                        "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"
                    ),
                ),
            ]
        )

        self.assertEqual(
            {
                "nvd": ["CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"],
            },
            unproxied_cve.cvss,
        )
