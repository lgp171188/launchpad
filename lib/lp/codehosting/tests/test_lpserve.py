# Copyright 2009 Canonical Ltd.  All rights reserved.

"""Tests for the lp-serve plugin."""

__metaclass__ = type

import os
from subprocess import PIPE
import unittest

from bzrlib import errors, osutils
from bzrlib.smart import medium
from bzrlib.tests import TestCaseWithTransport
from bzrlib.transport import remote

from canonical.config import config

from lp.codehosting import get_bzr_path, get_bzr_plugins_path
from lp.codehosting.bzrutils import make_error_utility


class TestLaunchpadServe(TestCaseWithTransport):
    """Tests for the lp-serve plugin.

    Most of the helper methods here are copied from bzrlib.tests and
    bzrlib.tests.blackbox.test_serve in bzr.dev r4445. They have since been
    modified for the Launchpad environment.
    """

    def assertFinishedCleanly(self, result):
        """Assert that a server process finished cleanly."""
        self.assertEqual((0, '', ''), tuple(result))

    def get_python_path(self):
        """Return the path to the Python interpreter."""
        return '%s/bin/py' % config.root

    def start_bzr_subprocess(self, process_args, env_changes=None,
                             working_dir=None):
        """Start bzr in a subprocess for testing.

        This starts a new Python interpreter and runs bzr in there.

        :param process_args: a list of arguments to pass to the bzr
            executable, for example ``['--version']``.
        :param env_changes: A dictionary which lists changes to environment
            variables. A value of None will unset the env variable.
            The values must be strings. The change will only occur in the
            child, so you don't need to fix the environment after running.

        :return: Popen object for the started process.
        """
        if env_changes is None:
            env_changes = {}
        env_changes['BZR_PLUGIN_PATH'] = get_bzr_plugins_path()
        old_env = {}

        def cleanup_environment():
            for env_var, value in env_changes.iteritems():
                old_env[env_var] = osutils.set_or_unset_env(env_var, value)

        def restore_environment():
            for env_var, value in old_env.iteritems():
                osutils.set_or_unset_env(env_var, value)

        cwd = None
        if working_dir is not None:
            cwd = osutils.getcwd()
            os.chdir(working_dir)

        # Because of buildout, we need to get a custom Python binary, not
        # sys.executable.
        python_path = self.get_python_path()
        # We can't use self.get_bzr_path(), since it'll find lib/bzrlib,
        # rather than the path to sourcecode/bzr/bzr.
        bzr_path = get_bzr_path()
        try:
            # win32 subprocess doesn't support preexec_fn
            # so we will avoid using it on all platforms, just to
            # make sure the code path is used, and we don't break on win32
            cleanup_environment()
            command = [python_path, bzr_path]
            command.extend(process_args)
            process = self._popen(
                command, stdin=PIPE, stdout=PIPE, stderr=PIPE)
        finally:
            restore_environment()
            if cwd is not None:
                os.chdir(cwd)

        return process

    def finish_lpserve_subprocess(self, process):
        """Shut down the server process.

        :return: A tuple of (retcode, stdout, stderr).
        """
        # Shutdown the server: the server should shut down when it cannot read
        # from stdin anymore.
        process.stdin.close()
        # Hide stdin from the subprocess module, so it won't fail to close it.
        process.stdin = None
        # Finish the process without asserting anything about the return code.
        # We'll leave that to assertFinishedCleanly.
        stdout_and_stderr = self.finish_bzr_subprocess(process, retcode=None)
        return (
            process.returncode,
            stdout_and_stderr[0],
            stdout_and_stderr[1],
            )

    def start_server_inet(self, user_id=None):
        """Start an lp-serve server subprocess.

        :param user_id: The database id of the user to run as. If not
            provided, defaults to 1.

        :return: a tuple with the bzr process handle for passing to
            finish_lpserve_subprocess, a client for the server, and a
            transport.
        """
        # Serve from the current directory
        if user_id is None:
            user_id = 1
        process = self.start_bzr_subprocess(
            ['lp-serve', '--inet', str(user_id)])

        # Connect to the server.
        # We use this url because while this is no valid URL to connect to
        # this server instance, the transport needs a URL.
        url = 'bzr://localhost/'
        client_medium = medium.SmartSimplePipesClientMedium(
            process.stdout, process.stdin, url)
        transport = remote.RemoteTransport(url, medium=client_medium)
        return process, transport

    def test_successful_start_then_stop(self):
        # We can start and stop the lpserve process.
        process, transport = self.start_server_inet()
        result = self.finish_lpserve_subprocess(process)
        self.assertFinishedCleanly(result)

    def test_successful_start_then_stop_logs_no_oops(self):
        # Starting and stopping the lp-serve process leaves no OOPS.
        process, transport = self.start_server_inet()
        error_utility = make_error_utility(process.pid)
        self.finish_lpserve_subprocess(process)
        self.assertIs(None, error_utility.getLastOopsReport())

    def test_unexpected_error_logs_oops(self):
        # If an unexpected error is raised in the plugin, then an OOPS is
        # recorded.
        process, transport = self.start_server_inet()
        error_utility = make_error_utility(process.pid)
        # This will trigger an error, because the XML-RPC server is not
        # running, and any filesystem access tries to get at the XML-RPC
        # server. If this *doesn'* raise, then the test is no longer valid and
        # we need a new way of triggering errors in the smart server.
        self.assertRaises(
            errors.UnknownErrorFromSmartServer,
            transport.list_dir, 'foo/bar/baz')
        result = self.finish_lpserve_subprocess(process)
        self.assertFinishedCleanly(result)
        self.assertIsNot(None, error_utility.getLastOopsReport())


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
