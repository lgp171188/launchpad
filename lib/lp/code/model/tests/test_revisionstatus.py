# Copyright 2021-2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for revision status reports and artifacts."""

import hashlib
import io

from testtools.matchers import (
    AnyMatch,
    Equals,
    MatchesSetwise,
    MatchesStructure,
    )
from zope.component import getUtility

from lp.app.enums import InformationType
from lp.code.enums import (
    RevisionStatusArtifactType,
    RevisionStatusResult,
    )
from lp.code.interfaces.revisionstatus import IRevisionStatusArtifactSet
from lp.services.auth.enums import AccessTokenScope
from lp.services.webapp.authorization import check_permission
from lp.testing import (
    anonymous_logged_in,
    api_url,
    person_logged_in,
    TestCaseWithFactory,
    )
from lp.testing.layers import (
    DatabaseFunctionalLayer,
    LaunchpadFunctionalLayer,
    )
from lp.testing.pages import webservice_for_person


class TestRevisionStatusReport(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def makeRevisionStatusArtifact(self, report):
        # We don't need to upload files to the librarian in this test suite.
        lfa = self.factory.makeLibraryFileAlias(db_only=True)
        return self.factory.makeRevisionStatusArtifact(lfa=lfa, report=report)

    def test_owner_public(self):
        # The owner of a public repository can view and edit its reports and
        # artifacts.
        report = self.factory.makeRevisionStatusReport()
        artifact = self.makeRevisionStatusArtifact(report=report)
        with person_logged_in(report.git_repository.owner):
            self.assertTrue(check_permission("launchpad.View", report))
            self.assertTrue(check_permission("launchpad.View", artifact))
            self.assertTrue(check_permission("launchpad.Edit", report))
            self.assertTrue(check_permission("launchpad.Edit", artifact))

    def test_owner_private(self):
        # The owner of a private repository can view and edit its reports
        # and artifacts.
        with person_logged_in(self.factory.makePerson()) as owner:
            report = self.factory.makeRevisionStatusReport(
                git_repository=self.factory.makeGitRepository(
                    owner=owner, information_type=InformationType.USERDATA))
            artifact = self.makeRevisionStatusArtifact(report=report)
            self.assertTrue(check_permission("launchpad.View", report))
            self.assertTrue(check_permission("launchpad.View", artifact))
            self.assertTrue(check_permission("launchpad.Edit", report))
            self.assertTrue(check_permission("launchpad.Edit", artifact))

    def test_random_public(self):
        # An unrelated user can view but not edit reports and artifacts in
        # public repositories.
        report = self.factory.makeRevisionStatusReport()
        artifact = self.makeRevisionStatusArtifact(report=report)
        with person_logged_in(self.factory.makePerson()):
            self.assertTrue(check_permission("launchpad.View", report))
            self.assertTrue(check_permission("launchpad.View", artifact))
            self.assertFalse(check_permission("launchpad.Edit", report))
            self.assertFalse(check_permission("launchpad.Edit", artifact))

    def test_random_private(self):
        # An unrelated user can neither view nor edit reports and artifacts
        # in private repositories.
        with person_logged_in(self.factory.makePerson()) as owner:
            report = self.factory.makeRevisionStatusReport(
                git_repository=self.factory.makeGitRepository(
                    owner=owner, information_type=InformationType.USERDATA))
            artifact = self.makeRevisionStatusArtifact(report=report)
        with person_logged_in(self.factory.makePerson()):
            self.assertFalse(check_permission("launchpad.View", report))
            self.assertFalse(check_permission("launchpad.View", artifact))
            self.assertFalse(check_permission("launchpad.Edit", report))
            self.assertFalse(check_permission("launchpad.Edit", artifact))

    def test_anonymous_public(self):
        # Anonymous users can view but not edit reports and artifacts in
        # public repositories.
        report = self.factory.makeRevisionStatusReport()
        artifact = self.makeRevisionStatusArtifact(report=report)
        with anonymous_logged_in():
            self.assertTrue(check_permission("launchpad.View", report))
            self.assertTrue(check_permission("launchpad.View", artifact))
            self.assertFalse(check_permission("launchpad.Edit", report))
            self.assertFalse(check_permission("launchpad.Edit", artifact))

    def test_anonymous_private(self):
        # Anonymous users can neither view nor edit reports and artifacts in
        # private repositories.
        with person_logged_in(self.factory.makePerson()) as owner:
            report = self.factory.makeRevisionStatusReport(
                git_repository=self.factory.makeGitRepository(
                    owner=owner, information_type=InformationType.USERDATA))
            artifact = self.makeRevisionStatusArtifact(report=report)
        with anonymous_logged_in():
            self.assertFalse(check_permission("launchpad.View", report))
            self.assertFalse(check_permission("launchpad.View", artifact))
            self.assertFalse(check_permission("launchpad.Edit", report))
            self.assertFalse(check_permission("launchpad.Edit", artifact))


class TestRevisionStatusReportWebservice(TestCaseWithFactory):
    layer = LaunchpadFunctionalLayer

    def setUp(self):
        super().setUp()
        self.repository = self.factory.makeGitRepository()
        self.requester = self.repository.owner
        self.title = self.factory.getUniqueUnicode('report-title')
        self.commit_sha1 = hashlib.sha1(b"Some content").hexdigest()
        self.result_summary = "120/120 tests passed"

        self.report = self.factory.makeRevisionStatusReport(
            user=self.repository.owner, git_repository=self.repository,
            title=self.title, commit_sha1=self.commit_sha1,
            result_summary=self.result_summary,
            result=RevisionStatusResult.FAILED)

        with person_logged_in(self.requester):
            self.report_url = api_url(self.report)

            secret, _ = self.factory.makeAccessToken(
                owner=self.requester, target=self.repository,
                scopes=[AccessTokenScope.REPOSITORY_BUILD_STATUS])
        self.webservice = webservice_for_person(
            self.requester, default_api_version="devel",
            access_token_secret=secret)

    def test_setLog(self):
        content = b'log_content_data'
        response = self.webservice.named_post(
            self.report_url, "setLog", log_data=io.BytesIO(content))
        self.assertEqual(200, response.status)

        # A report may have multiple artifacts.
        # We verify that the content we just submitted via API now
        # matches one of the artifacts in the DB for the report.
        with person_logged_in(self.requester):
            artifacts = list(getUtility(
                IRevisionStatusArtifactSet).findByReport(self.report))
            self.assertThat(artifacts, AnyMatch(
                MatchesStructure(
                    report=Equals(self.report),
                    library_file=MatchesStructure(
                        content=MatchesStructure.byEquality(
                            sha256=hashlib.sha256(content).hexdigest()),
                        filename=Equals(
                            "%s-%s.txt" % (self.title, self.commit_sha1)),
                        mimetype=Equals("text/plain")),
                    artifact_type=Equals(RevisionStatusArtifactType.LOG))))

    def test_attach(self):
        filenames = ["artifact-1", "artifact-2"]
        contents = [b"artifact 1", b"artifact 2"]
        for filename, content in zip(filenames, contents):
            response = self.webservice.named_post(
                self.report_url, "attach", name=filename,
                data=io.BytesIO(content))
            self.assertEqual(200, response.status)

        with person_logged_in(self.requester):
            artifacts = list(getUtility(
                IRevisionStatusArtifactSet).findByReport(self.report))
            self.assertThat(artifacts, MatchesSetwise(*(
                MatchesStructure(
                    report=Equals(self.report),
                    library_file=MatchesStructure(
                        content=MatchesStructure.byEquality(
                            sha256=hashlib.sha256(content).hexdigest()),
                        filename=Equals(filename),
                        mimetype=Equals("application/octet-stream")),
                    artifact_type=Equals(RevisionStatusArtifactType.BINARY))
                for filename, content in zip(filenames, contents))))

    def test_update(self):
        response = self.webservice.named_post(
            self.report_url, "update", title="updated-report-title")
        self.assertEqual(200, response.status)
        with person_logged_in(self.requester):
            self.assertEqual('updated-report-title', self.report.title)
            self.assertEqual(self.commit_sha1, self.report.commit_sha1)
            self.assertEqual(self.result_summary, self.report.result_summary)
            self.assertEqual(RevisionStatusResult.FAILED, self.report.result)
            date_finished_before_update = self.report.date_finished
        response = self.webservice.named_post(
            self.report_url, "update", result="Succeeded")
        self.assertEqual(200, response.status)
        with person_logged_in(self.requester):
            self.assertEqual('updated-report-title', self.report.title)
            self.assertEqual(self.commit_sha1, self.report.commit_sha1)
            self.assertEqual(self.result_summary, self.report.result_summary)
            self.assertEqual(RevisionStatusResult.SUCCEEDED,
                             self.report.result)
            self.assertGreater(self.report.date_finished,
                               date_finished_before_update)
