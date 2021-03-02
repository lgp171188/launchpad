# Copyright 2010-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test the request_git_repack script."""
import base64
from collections import defaultdict
import json
import threading
from wsgiref.simple_server import (
    make_server,
    WSGIRequestHandler,
    )
import transaction
from zope.security.proxy import removeSecurityProxy

from lp.code.interfaces.codehosting import BRANCH_ID_ALIAS_PREFIX
from lp.services.config import config
from lp.services.config.fixture import ConfigFixture, ConfigUseFixture
from lp.testing import TestCaseWithFactory
from lp.testing.layers import ZopelessAppServerLayer
from lp.services.scripts.tests import run_script


class SilentWSGIRequestHandler(WSGIRequestHandler):
    """A request handler that doesn't log requests."""

    def log_message(self, fmt, *args):
        pass


class FakeTurnipApplication:
    """A WSGI application that provides some fake turnip endpoints."""

    def __init__(self):
        self.contents = defaultdict(dict)

    def _not_found(self, start_response):
        start_response('404 Not Found', [('Content-Type', 'text/plain')])
        return [b'']

    def __call__(self, environ, start_response):
        segments = environ['PATH_INFO'].lstrip('/').split('/')
        if (len(segments) < 4 or
                segments[0] != 'repo' or segments[2] != 'blob'):
            return self._not_found(start_response)
        repository_id = segments[1]
        if repository_id not in self.contents:
            return self._not_found(start_response)
        filename = '/'.join(segments[3:])
        if filename not in self.contents[repository_id]:
            return self._not_found(start_response)
        blob = self.contents[repository_id][filename]
        response = {'size': len(blob), 'data': base64.b64encode(blob)}
        start_response(
            '200 OK', [('Content-Type', 'application/octet-stream')])
        return [json.dumps(response).encode('UTF-8')]

    def addBlob(self, repository, filename, contents):
        self.contents[repository.getInternalPath()][filename] = contents


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

    def addBlob(self, repository_id, filename, contents):
        self.app.addBlob(repository_id, filename, contents)

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

    def test_request_git_repack(self):
        """Ensure the request_git_repack script requests the repacks."""
        repo = self.factory.makeGitRepository()
        repo = removeSecurityProxy(repo)
        repo.loose_object_count = 7000
        repo.pack_count = 43
        transaction.commit()

        turnip_server = self.makeTurnipServer()
        turnip_server.addBlob(
            repo, 'repo', b'name: prod_repo')

        retcode, stdout, stderr = run_script(
            'cronscripts/request_git_repack.py', [])

        self.assertIsNotNone(repo.date_last_repacked)
        self.assertIn('Requested 0 automatic git repository repack.', stderr)
