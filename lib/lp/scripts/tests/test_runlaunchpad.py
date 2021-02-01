# Copyright 2009-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for runlaunchpad.py"""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    'CommandLineArgumentProcessing',
    'ServersToStart',
    ]


import os
import shutil
import tempfile
from textwrap import dedent

import testtools

from lp.scripts.runlaunchpad import (
    get_services_to_run,
    gunicornify_zope_config_file,
    process_config_arguments,
    SERVICES,
    split_out_runlaunchpad_arguments,
    start_launchpad,
    )
from lp.services.compat import mock
import lp.services.config
from lp.services.config import config
import lp.testing


class CommandLineArgumentProcessing(lp.testing.TestCase):
    """runlaunchpad.py's command line arguments fall into two parts. The first
    part specifies which services to run, then second part is passed directly
    on to the Zope webserver start up.
    """

    def test_no_parameter(self):
        """Given no arguments, return no services and no Zope arguments."""
        self.assertEqual(([], []), split_out_runlaunchpad_arguments([]))

    def test_run_options(self):
        """Services to run are specified with an optional `-r` option.

        If a service is specified, it should appear as the first value in the
        returned tuple.
        """
        self.assertEqual(
            (['foo'], []), split_out_runlaunchpad_arguments(['-r', 'foo']))

    def test_run_lots_of_things(self):
        """The `-r` option can be used to specify multiple services.

        Multiple services are separated with commas. e.g. `-r foo,bar`.
        """
        self.assertEqual(
            (['foo', 'bar'], []),
            split_out_runlaunchpad_arguments(['-r', 'foo,bar']))

    def test_run_with_zope_params(self):
        """Any arguments after the initial `-r` option should be passed
        straight through to Zope.
        """
        self.assertEqual(
            (['foo', 'bar'], ['-o', 'foo', '--bar=baz']),
            split_out_runlaunchpad_arguments(['-r', 'foo,bar', '-o', 'foo',
                                              '--bar=baz']))

    def test_run_with_only_zope_params(self):
        """Pass all the options to zope when the `-r` option is not given."""
        self.assertEqual(
            ([], ['-o', 'foo', '--bar=baz']),
            split_out_runlaunchpad_arguments(['-o', 'foo', '--bar=baz']))


class TestDefaultConfigArgument(lp.testing.TestCase):
    """Tests for the processing of the -C argument."""

    def setUp(self):
        super(TestDefaultConfigArgument, self).setUp()
        self.config_root = tempfile.mkdtemp('configs')
        self.saved_instance = config.instance_name
        self.saved_config_roots = lp.services.config.CONFIG_ROOT_DIRS
        lp.services.config.CONFIG_ROOT_DIRS = [self.config_root]
        self.addCleanup(self.cleanUp)

    def cleanUp(self):
        shutil.rmtree(self.config_root)
        lp.services.config.CONFIG_ROOT_DIRS = self.saved_config_roots
        config.setInstance(self.saved_instance)

    def test_keep_argument(self):
        """Make sure that a -C is processed unchanged."""
        self.assertEqual(
            ['-v', '-C', 'a_file.conf', '-h'],
            process_config_arguments(['-v', '-C', 'a_file.conf', '-h']))

    def test_default_config(self):
        """Make sure that the -C option is set to the correct instance."""
        instance_config_dir = os.path.join(self.config_root, 'instance1')
        os.mkdir(instance_config_dir)
        open(os.path.join(instance_config_dir, 'launchpad.conf'), 'w').close()
        config.setInstance('instance1')
        self.assertEqual(
            ['-a_flag', '-C', '%s/launchpad.conf' % instance_config_dir],
            process_config_arguments(['-a_flag']))

    def test_instance_not_found_raises_ValueError(self):
        """Make sure that an unknown instance fails."""
        config.setInstance('unknown')
        self.assertRaises(ValueError, process_config_arguments, [])

    def test_i_sets_the_instance(self):
        """The -i parameter will set the config instance name."""
        instance_config_dir = os.path.join(self.config_root, 'test')
        os.mkdir(instance_config_dir)
        open(os.path.join(instance_config_dir, 'launchpad.conf'), 'w').close()
        self.assertEqual(
            ['-o', 'foo', '-C', '%s/launchpad.conf' % instance_config_dir],
            process_config_arguments(
                ['-i', 'test', '-o', 'foo']))
        self.assertEqual('test', config.instance_name)


class ServersToStart(testtools.TestCase):
    """Test server startup control."""

    def setUp(self):
        """Make sure that only the Librarian is configured to launch."""
        testtools.TestCase.setUp(self)
        launch_data = """
            [librarian_server]
            launch: True
            [codehosting]
            launch: False
            [launchpad]
            launch: False
            """
        config.push('launch_data', launch_data)
        self.addCleanup(config.pop, 'launch_data')

    def test_nothing_explicitly_requested(self):
        """Implicitly start services based on the config.*.launch property.
        """
        services = sorted(get_services_to_run([]))
        expected = [SERVICES['librarian']]

        # The search test services may or may not be asked to run.
        if config.bing_test_service.launch:
            expected.append(SERVICES['bing-webservice'])

        # RabbitMQ may or may not be asked to run.
        if config.rabbitmq.launch:
            expected.append(SERVICES['rabbitmq'])

        expected = sorted(expected)
        self.assertEqual(expected, services)

    def test_explicit_request_overrides(self):
        """Only start those services which are explicitly requested,
        ignoring the configuration properties.
        """
        services = get_services_to_run(['sftp'])
        self.assertEqual([SERVICES['sftp']], services)

    def test_launchpad_systems_red(self):
        self.assertFalse(config.launchpad.launch)


class TestAppServerStart(lp.testing.TestCase):
    @mock.patch('lp.scripts.runlaunchpad.zope_main')
    @mock.patch('lp.scripts.runlaunchpad.gunicorn_main')
    @mock.patch('lp.scripts.runlaunchpad.make_pidfile')
    def test_call_correct_method(self, make_pidfile, gmain, zmain):
        # Makes sure zope_main or gunicorn_main is called according to
        # launchpad configuration.
        patched_cfg = mock.patch(
            'lp.services.config.LaunchpadConfig.use_gunicorn',
            new_callable=mock.PropertyMock)
        with patched_cfg as mock_use_gunicorn:
            mock_use_gunicorn.return_value = True
            start_launchpad([])
            self.assertEqual(1, gmain.call_count)
            self.assertEqual(0, zmain.call_count)
        gmain.reset_mock()
        zmain.reset_mock()
        with patched_cfg as mock_use_gunicorn:
            mock_use_gunicorn.return_value = False
            start_launchpad([])
            self.assertEqual(0, gmain.call_count)
            self.assertEqual(1, zmain.call_count)

    def test_gunicornify_config(self):
        content = dedent("""
        site-definition zcml/webapp.zcml
        # With some comment
        devmode off
        interrupt-check-interval 200
        <server>
          type HTTP
          address 8085
        </server>
        <server>
          type XXX
          address 123
        </server>
        
        <zodb>
          <mappingstorage/>
        </zodb>
        
        <accesslog>
          <logfile>
            path logs/test-appserver-layer.log
          </logfile>
        </accesslog>
        """)
        config_filename = tempfile.mktemp()
        with open(config_filename, "w") as fd:
            fd.write(content)

        patched_cfg = mock.patch(
            'lp.services.config.LaunchpadConfig.zope_config_file',
            new_callable=mock.PropertyMock)
        with patched_cfg as mock_zope_config_file:
            mock_zope_config_file.return_value = config_filename

            gunicornify_zope_config_file()
            self.assertEqual(2, mock_zope_config_file.call_count)
            new_file = mock_zope_config_file.call_args[0][0]
            self.assertEqual(dedent("""
                site-definition zcml/webapp.zcml
                # With some comment
                devmode off
                
                
                
                <zodb>
                  <mappingstorage/>
                </zodb>


                """), new_file.read())
