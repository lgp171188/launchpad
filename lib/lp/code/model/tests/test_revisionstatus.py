# Copyright 2021-2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for revision status reports and artifacts."""

import hashlib
import io

from testtools.matchers import (
    AnyMatch,
    Equals,
    MatchesStructure,
    )
from zope.component import getUtility

from lp.code.enums import (
    RevisionStatusArtifactType,
    RevisionStatusResult,
    )
from lp.code.interfaces.revisionstatus import IRevisionStatusArtifactSet
from lp.services.auth.enums import AccessTokenScope
from lp.testing import (
    api_url,
    person_logged_in,
    TestCaseWithFactory,
    )
from lp.testing.layers import LaunchpadFunctionalLayer
from lp.testing.pages import webservice_for_person


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

        self.webservice = webservice_for_person(
            None, default_api_version="devel")
        with person_logged_in(self.requester):
            self.report_url = api_url(self.report)

            secret, _ = self.factory.makeAccessToken(
                owner=self.requester, target=self.repository,
                scopes=[AccessTokenScope.REPOSITORY_BUILD_STATUS])
            self.header = {'Authorization': 'Token %s' % secret}

    def test_setLog(self):
        content = b'log_content_data'
        response = self.webservice.named_post(
            self.report_url, "setLog",
            headers=self.header,
            log_data=io.BytesIO(content))
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

    def test_update(self):
        response = self.webservice.named_post(
            self.report_url, "update",
            headers=self.header,
            title='updated-report-title')
        self.assertEqual(200, response.status)
        with person_logged_in(self.requester):
            self.assertEqual('updated-report-title', self.report.title)
            self.assertEqual(self.commit_sha1, self.report.commit_sha1)
            self.assertEqual(self.result_summary, self.report.result_summary)
            self.assertEqual(RevisionStatusResult.FAILED, self.report.result)
            date_finished_before_update = self.report.date_finished
        response = self.webservice.named_post(
            self.report_url, "update",
            headers=self.header,
            result='Succeeded')
        self.assertEqual(200, response.status)
        with person_logged_in(self.requester):
            self.assertEqual('updated-report-title', self.report.title)
            self.assertEqual(self.commit_sha1, self.report.commit_sha1)
            self.assertEqual(self.result_summary, self.report.result_summary)
            self.assertEqual(RevisionStatusResult.SUCCEEDED,
                             self.report.result)
            self.assertGreater(self.report.date_finished,
                               date_finished_before_update)
