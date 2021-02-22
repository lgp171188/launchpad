# Copyright 2010-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test the request_git_repack script."""
from collections import defaultdict
import json
import threading
from wsgiref.simple_server import (
    make_server,
    WSGIRequestHandler,
    )
import transaction

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


class FakeLoggerheadApplication:
    """A WSGI application that provides some fake loggerhead endpoints."""

    def __init__(self):
        self.file_ids = defaultdict(dict)
        self.contents = defaultdict(dict)

    def _not_found(self, start_response):
        start_response('404 Not Found', [('Content-Type', 'text/plain')])
        return [b'']

    def __call__(self, environ, start_response):
        segments = environ['PATH_INFO'].lstrip('/').split('/')
        if len(segments) < 3 or segments[0] != BRANCH_ID_ALIAS_PREFIX:
            return self._not_found(start_response)
        try:
            branch_id = int(segments[1])
        except ValueError:
            return self._not_found(start_response)
        if segments[2:4] == ['+json', 'files']:
            if branch_id not in self.file_ids or len(segments) < 5:
                return self._not_found(start_response)
            directory = '/'.join(segments[5:])
            files = {
                path: file_id
                for path, file_id in self.file_ids[branch_id].items()
                if '/'.join(path.split('/')[:-1]) == directory
                }
            if not files:
                return self._not_found(start_response)
            response = {
                'filelist': [
                    {
                        'filename': path.split('/')[-1],
                        'file_id': file_id,
                        } for path, file_id in files.items()
                    ],
                }
            start_response('200 OK', [('Content-Type', 'application/json')])
            return [json.dumps(response).encode('UTF-8')]
        elif segments[2:3] == ['download']:
            if branch_id not in self.contents or len(segments) != 5:
                return self._not_found(start_response)
            file_id = segments[4]
            if file_id not in self.contents[branch_id]:
                return self._not_found(start_response)
            start_response(
                '200 OK', [('Content-Type', 'application/octet-stream')])
            return [self.contents[branch_id][file_id]]
        else:
            return self._not_found(start_response)

    def addInventory(self, branch_id, path, file_id):
        self.file_ids[branch_id][path] = file_id

    def addBlob(self, branch_id, file_id, contents):
        self.contents[branch_id][file_id] = contents


class FakeLoggerheadServer(threading.Thread):
    """Thread that runs a fake loggerhead server."""

    def __init__(self):
        super(FakeLoggerheadServer, self).__init__()
        self.app = FakeLoggerheadApplication()
        self.server = make_server(
            'localhost', 0, self.app, handler_class=SilentWSGIRequestHandler)

    def run(self):
        self.server.serve_forever()

    def getURL(self):
        host, port = self.server.server_address
        return 'http://%s:%d/' % (host, port)

    def addInventory(self, branch, path, file_id):
        self.app.addInventory(branch.id, path, file_id)

    def addBlob(self, branch, file_id, contents):
        self.app.addBlob(branch.id, file_id, contents)

    def stop(self):
        self.server.shutdown()

class TestRequestGitRepack(TestCaseWithFactory):

    layer = ZopelessAppServerLayer

    def setUp(self):
        super(TestRequestGitRepack, self).setUp()

    def makeLoggerheadServer(self):
        loggerhead_server = FakeLoggerheadServer()
        config_name = self.factory.getUniqueString()
        config_fixture = self.useFixture(ConfigFixture(
            config_name, config.instance_name))
        setting_lines = [
            '[codehosting]',
            'internal_bzr_api_endpoint: %s' % loggerhead_server.getURL(),
            ]
        config_fixture.add_section('\n' + '\n'.join(setting_lines))
        self.useFixture(ConfigUseFixture(config_name))
        loggerhead_server.start()
        self.addCleanup(loggerhead_server.stop)
        return loggerhead_server

    def test_request_git_repack(self):
        """Ensure the request_git_repack script requests the repacks."""
        repo = self.factory.makeGitRepository()
        transaction.commit()

        loggerhead_server = self.makeLoggerheadServer()
        loggerhead_server.addInventory(repo, 'repository', 'prod_repo')

        retcode, stdout, stderr = run_script(
            'cronscripts/request_git_repack.py', [])
        self.assertIn('Requested 0 automatic git repository repack.', stderr)
