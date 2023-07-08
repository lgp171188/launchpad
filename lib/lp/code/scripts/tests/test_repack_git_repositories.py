# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test the repack_git_repositories script."""

import logging
import threading
from datetime import datetime, timedelta, timezone
from wsgiref.simple_server import WSGIRequestHandler, make_server

import transaction
from zope.security.proxy import removeSecurityProxy

from lp.code.scripts.repackgitrepository import RepackTunableLoop
from lp.services.config import config
from lp.services.config.fixture import ConfigFixture, ConfigUseFixture
from lp.testing import TestCaseWithFactory
from lp.testing.layers import ZopelessAppServerLayer
from lp.testing.script import run_script


class SilentWSGIRequestHandler(WSGIRequestHandler):
    """A request handler that doesn't log requests."""

    def log_message(self, fmt, *args):
        pass


class FakeTurnipApplication:
    """A WSGI application that provides a fake turnip endpoint."""

    def __init__(self):
        self.contents = []

    def __call__(self, environ, start_response):
        self.contents.append(environ["PATH_INFO"])
        start_response("200 OK", [("Content-Type", "text/plain")])
        return [b""]


class FakeTurnipServer(threading.Thread):
    """Thread that runs a fake turnip server."""

    def __init__(self):
        super().__init__()
        self.name = "FakeTurnipServer"
        self.app = FakeTurnipApplication()
        self.server = make_server(
            "localhost", 0, self.app, handler_class=SilentWSGIRequestHandler
        )

    def run(self):
        self.server.serve_forever()

    def getURL(self):
        host, port = self.server.server_address
        return "http://%s:%d/" % (host, port)

    def stop(self):
        self.server.shutdown()


class TestRequestGitRepack(TestCaseWithFactory):
    layer = ZopelessAppServerLayer

    def setUp(self):
        super().setUp()
        self.log = logging.getLogger("repack")

    def runScript_no_Turnip(self):
        transaction.commit()

        (ret, out, err) = run_script("cronscripts/repack_git_repositories.py")
        self.assertIn(
            "An error occurred while requesting repository repack", err
        )
        self.assertIn("Failed to repack Git repository 1", err)
        self.assertIn(
            "Requested a total of 1 automatic git repository repacks "
            "in this run of the Automated Repack Job",
            err,
        )
        transaction.commit()

    def runScript_with_Turnip(self, expected_count=1):
        transaction.commit()
        (ret, out, err) = run_script("cronscripts/repack_git_repositories.py")
        self.assertIn(
            "Requested a total of %d automatic git repository repacks "
            "in this run of the Automated Repack Job." % expected_count,
            err,
        )
        transaction.commit()

    def makeTurnipServer(self):
        self.turnip_server = FakeTurnipServer()
        config_name = self.factory.getUniqueString()
        config_fixture = self.useFixture(
            ConfigFixture(config_name, config.instance_name)
        )
        setting_lines = [
            "[codehosting]",
            "internal_git_api_endpoint: %s" % self.turnip_server.getURL(),
        ]
        config_fixture.add_section("\n" + "\n".join(setting_lines))
        self.useFixture(ConfigUseFixture(config_name))
        self.turnip_server.start()
        self.addCleanup(self.turnip_server.stop)
        return self.turnip_server

    def test_auto_repack_without_Turnip(self):
        repo = self.factory.makeGitRepository()
        repo = removeSecurityProxy(repo)
        repo.loose_object_count = 7000
        repo.pack_count = 43

        # Do not start the fake turnip server here
        # to test if the RequestGitRepack will catch and
        # log correctly the failure to establish
        # a connection to Turnip
        self.runScript_no_Turnip()
        self.assertIsNone(repo.date_last_repacked)

    def test_auto_repack_with_Turnip_one_repo(self):
        # Test repack works when only one repository
        # qualifies for a repack
        repo = self.factory.makeGitRepository()
        repo = removeSecurityProxy(repo)
        repo.loose_object_count = 7000
        repo.pack_count = 43
        transaction.commit()

        self.makeTurnipServer()

        self.runScript_with_Turnip()

        self.assertIsNotNone(repo.date_last_repacked)

    def test_auto_repack_with_Turnip_multiple_repos(self):
        # Test repack works when 10 repositories
        # qualify for a repack
        repo = []
        for i in range(10):
            repo.append(self.factory.makeGitRepository())
            repo[i] = removeSecurityProxy(repo[i])
            repo[i].loose_object_count = 7000
            repo[i].pack_count = 43
        transaction.commit()

        self.makeTurnipServer()

        self.runScript_with_Turnip(expected_count=10)

        for i in range(10):
            self.assertIsNotNone(repo[i].date_last_repacked)
            self.assertEqual(
                "/repo/%s/repack" % repo[i].getInternalPath(),
                self.turnip_server.app.contents[i],
            )

    def test_auto_repack_zero_repackCandidates(self):
        self.makeTurnipServer()
        repo = []
        for i in range(2):
            repo.append(self.factory.makeGitRepository())
            repo[i] = removeSecurityProxy(repo[i])
            repo[i].loose_object_count = 3
            repo[i].pack_count = 2
        transaction.commit()

        # zero candidates
        # assert on the log contents and the content that makes it to Turnip
        (ret, out, err) = run_script("cronscripts/repack_git_repositories.py")
        self.assertIn(
            "Requested a total of 0 automatic git repository repacks in this "
            "run of the Automated Repack Job.",
            err,
        )
        self.assertEqual([], self.turnip_server.app.contents)

        # exactly one candidate
        repo[0].loose_object_count = 7000
        repo[0].pack_count = 43
        transaction.commit()
        (ret, out, err) = run_script("cronscripts/repack_git_repositories.py")
        self.assertIn(
            "Requested a total of 1 automatic git repository repacks in "
            "this run of the Automated Repack Job.",
            err,
        )
        self.assertEqual(
            "/repo/%s/repack" % repo[0].getInternalPath(),
            self.turnip_server.app.contents[0],
        )

    def test_auto_repack_loop_throttle(self):
        repacker = RepackTunableLoop(self.log, None)
        # We throttle at 7 for this test, we use a limit
        # of 1 000 repositories in reality
        repacker.targets = 7

        # We want to allow a maximum of 3 repack requests
        # per loop run for this test, we have a chunk size of
        # 5 defined in reality
        repacker.maximum_chunk_size = 3

        # Test repack works when 10 repositories
        # qualify for a repack but throttle at 7
        repo = []
        for i in range(10):
            repo.append(self.factory.makeGitRepository())
            repo[i] = removeSecurityProxy(repo[i])
            repo[i].loose_object_count = 7000
            repo[i].pack_count = 43
        transaction.commit()

        # Confirm the initial state is sane.
        self.assertFalse(repacker.isDone())

        # First run.
        repacker(repacker.maximum_chunk_size)

        self.assertFalse(repacker.isDone())
        self.assertEqual(repacker.num_repacked, 3)
        self.assertEqual(repacker.start_at, 3)

        # Second run.
        # The number of repos repacked so far (6) plus the number of
        # repos we can request in one loop (maximum_chunk_size = 3) would
        # put us over the maximum number of repositories we are targeting
        # with the repack job: "targets" defined as 7 for this test.
        repacker(repacker.maximum_chunk_size)

        self.assertTrue(repacker.isDone())
        self.assertEqual(repacker.num_repacked, 6)
        self.assertEqual(repacker.start_at, 6)

    def test_auto_repack_frequency(self):
        self.makeTurnipServer()

        repo = self.factory.makeGitRepository()
        removeSecurityProxy(repo).loose_object_count = (
            config.codehosting.loose_objects_threshold + 50
        )
        removeSecurityProxy(repo).pack_count = (
            config.codehosting.packs_threshold + 5
        )
        self.assertIsNone(repo.date_last_repacked)

        # An initial run requests a repack.
        self.runScript_with_Turnip(expected_count=1)
        self.assertIsNotNone(repo.date_last_repacked)

        # A second run does not request a repack, since the repository
        # already had a repack requested recently.
        self.runScript_with_Turnip(expected_count=0)
        self.assertIsNotNone(repo.date_last_repacked)

        # If we pretend that the last repack request was long enough ago,
        # then a third run requests another repack.
        removeSecurityProxy(repo).date_last_repacked = datetime.now(
            timezone.utc
        ) - timedelta(minutes=config.codehosting.auto_repack_frequency + 1)
        self.runScript_with_Turnip(expected_count=1)

    def test_auto_repack_findRepackCandidates(self):
        repacker = RepackTunableLoop(self.log, None)

        repo = []
        for i in range(7):
            repo.append(self.factory.makeGitRepository())
            repo[i] = removeSecurityProxy(repo[i])
            repo[i].loose_object_count = 7000
            repo[i].pack_count = 43

        for i in range(3):
            repo.append(self.factory.makeGitRepository())

        # we should only have 7 candidates at this point
        self.assertEqual(7, len(list(repacker.findRepackCandidates())))

        # there should be 0 candidates now
        for i in range(7):
            repo[i].loose_object_count = 3
            repo[i].pack_count = 5
        self.assertEqual(0, len(list(repacker.findRepackCandidates())))
