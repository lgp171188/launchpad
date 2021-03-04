# Copyright 2010-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test the request_git_repack script."""
from collections import defaultdict
import threading
from wsgiref.simple_server import (
    make_server,
    WSGIRequestHandler,
    )

import transaction
from zope.security.proxy import removeSecurityProxy

from lp.services.config import config
from lp.services.config.fixture import (
    ConfigFixture,
    ConfigUseFixture,
    )
from lp.services.scripts.tests import run_script
from lp.testing import TestCaseWithFactory
from lp.testing.layers import ZopelessAppServerLayer


class SilentWSGIRequestHandler(WSGIRequestHandler):
    """A request handler that doesn't log requests."""

    def log_message(self, fmt, *args):
        pass


class FakeTurnipApplication:
    """A WSGI application that provides a fake turnip endpoint."""

    def __init__(self):
        self.contents = defaultdict(dict)

    def __call__(self, environ, start_response):
        start_response('200 OK', [('Content-Type', 'text/plain')])
        return [b'']


class FakeTurnipServer(threading.Thread):
    """Thread that runs a fake turnip server."""

    def __init__(self):
        super(FakeTurnipServer, self).__init__()
        self.app = FakeTurnipApplication()
        self.server = make_server(
            'localhost', 0, self.app, handler_class=SilentWSGIRequestHandler)

    def run(self):
        self.server.serve_forever()

    def getURL(self):
        host, port = self.server.server_address
        return 'http://%s:%d/' % (host, port)

    def stop(self):
        self.server.shutdown()


class TestRequestGitRepack(TestCaseWithFactory):

    layer = ZopelessAppServerLayer

    def setUp(self):
        super(TestRequestGitRepack, self).setUp()

    def makeTurnipServer(self):
        turnip_server = FakeTurnipServer()
        config_name = self.factory.getUniqueString()
        config_fixture = self.useFixture(ConfigFixture(
            config_name, config.instance_name))
        setting_lines = [
            '[codehosting]',
            'internal_git_api_endpoint: %s' % turnip_server.getURL(),
            ]
        config_fixture.add_section('\n' + '\n'.join(setting_lines))
        self.useFixture(ConfigUseFixture(config_name))
        turnip_server.start()
        self.addCleanup(turnip_server.stop)
        return turnip_server

    def test_request_git_repack_fails(self):
        """Ensure the request_git_repack script requests the repacks."""

        repo = self.factory.makeGitRepository()
        repo = removeSecurityProxy(repo)
        repo.loose_object_count = 7000
        repo.pack_count = 43
        transaction.commit()

        retcode, stdout, stderr = run_script(
            'cronscripts/repack_git_repositories.py', [])

        # Do not start the fake turnip server here
        # to test if the RequestGitRepack will catch and
        # log correctly the expected CannotRepackRepository
        self.assertIsNone(repo.date_last_repacked)
        self.assertIn(
            'An error occurred while requesting repository repack',
            stderr)
        self.assertIn(
            'Failed to repack Git repository 1', stderr)
        self.assertIn(
            'Requested 0 automatic git repository '
            'repack out of the 1 qualifying for repack.', stderr)

    def test_request_git_repack(self):
        """Ensure the request_git_repack script requests the repacks."""

        repo = self.factory.makeGitRepository()
        repo = removeSecurityProxy(repo)
        repo.loose_object_count = 7000
        repo.pack_count = 43
        transaction.commit()

        self.makeTurnipServer()

        retcode, stdout, stderr = run_script(
            'cronscripts/repack_git_repositories.py', [])

        self.assertIsNotNone(repo.date_last_repacked)
        self.assertIn(
            'Requested 1 automatic git repository repack '
            'out of the 1 qualifying for repack.', stderr)
