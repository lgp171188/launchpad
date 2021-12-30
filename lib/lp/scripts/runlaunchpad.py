# Copyright 2009-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = ['start_launchpad']

from contextlib import ExitStack
import os
import signal
import subprocess
import sys

import fixtures
from lazr.config import as_host_port
from rabbitfixture.server import RabbitServerResources
from talisker import run_gunicorn
from testtools.testresult.real import _details_to_str

from lp.services.config import config
from lp.services.daemons import tachandler
from lp.services.osutils import ensure_directory_exists
from lp.services.pidfile import (
    make_pidfile,
    pidfile_path,
    )
from lp.services.rabbit.server import RabbitServer
from lp.services.sitesearch import bingtestservice


def make_abspath(path):
    return os.path.abspath(os.path.join(config.root, *path.split('/')))


class Service(fixtures.Fixture):

    @property
    def should_launch(self):
        """Return true if this service should be launched by default."""
        return False

    def launch(self):
        """Run the service in a thread or external process.

        May block long enough to kick it off, but must return control to
        the caller without waiting for it to shutdown.
        """
        raise NotImplementedError

    def _setUp(self):
        self.launch()


class TacFile(Service):

    def __init__(self, name, tac_filename, section_name, pre_launch=None):
        """Create a TacFile object.

        :param name: A short name for the service. Used to name the pid file.
        :param tac_filename: The location of the TAC file, relative to this
            script.
        :param section_name: The config section name that provides the
            launch, logfile and spew options.
        :param pre_launch: A callable that is called before the launch
            process.
        """
        super().__init__()
        self.name = name
        self.tac_filename = tac_filename
        self.section_name = section_name
        if pre_launch is None:
            self.pre_launch = lambda: None
        else:
            self.pre_launch = pre_launch

    @property
    def should_launch(self):
        return (self.section_name is not None
                and config[self.section_name].launch)

    @property
    def logfile(self):
        """Return the log file to use.

        Default to the value of the configuration key logfile.
        """
        return config[self.section_name].logfile

    def launch(self):
        self.pre_launch()

        pidfile = pidfile_path(self.name)
        logfile = config[self.section_name].logfile
        tacfile = make_abspath(self.tac_filename)

        args = [
            tachandler.twistd_script,
            "--no_save",
            "--nodaemon",
            "--python", tacfile,
            "--pidfile", pidfile,
            "--prefix", self.name.capitalize(),
            "--logfile", logfile,
            ]

        if config[self.section_name].spew:
            args.append("--spew")

        # Note that startup tracebacks and evil programmers using 'print' will
        # cause output to our stdout. However, we don't want to have twisted
        # log to stdout and redirect it ourselves because we then lose the
        # ability to cycle the log files by sending a signal to the twisted
        # process.
        process = subprocess.Popen(args, stdin=subprocess.PIPE)
        self.addCleanup(stop_process, process)
        process.stdin.close()


class CodebrowseService(Service):

    @property
    def should_launch(self):
        return False

    def launch(self):
        process = subprocess.Popen(
            ['make', 'run_codebrowse'],
            stdin=subprocess.PIPE)
        self.addCleanup(stop_process, process)
        process.stdin.close()


class BingWebService(Service):

    @property
    def should_launch(self):
        return config.bing_test_service.launch

    def launch(self):
        self.addCleanup(stop_process, bingtestservice.start_as_process())


class MemcachedService(Service):
    """A local memcached service for developer environments."""

    @property
    def should_launch(self):
        return config.memcached.launch

    def launch(self):
        cmd = [
            'memcached',
            '-m', str(config.memcached.memory_size),
            '-l', str(config.memcached.address),
            '-p', str(config.memcached.port),
            '-U', str(config.memcached.port),
            ]
        if config.memcached.verbose:
            cmd.append('-vv')
        else:
            cmd.append('-v')
        process = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        self.addCleanup(stop_process, process)
        process.stdin.close()


class RabbitService(Service):
    """A RabbitMQ service."""

    @property
    def should_launch(self):
        return config.rabbitmq.launch

    def launch(self):
        hostname, port = as_host_port(config.rabbitmq.host, None, None)
        self.server = RabbitServer(
            RabbitServerResources(hostname=hostname, port=port))
        self.useFixture(self.server)


def stop_process(process):
    """kill process and BLOCK until process dies.

    :param process: An instance of subprocess.Popen.
    """
    if process.poll() is None:
        os.kill(process.pid, signal.SIGTERM)
        process.wait()


def prepare_for_librarian():
    if not os.path.isdir(config.librarian_server.root):
        os.makedirs(config.librarian_server.root, 0o700)


SERVICES = {
    'librarian': TacFile('librarian', 'daemons/librarian.tac',
                         'librarian_server', prepare_for_librarian),
    'sftp': TacFile('sftp', 'daemons/sftp.tac', 'codehosting'),
    'bing-webservice': BingWebService(),
    'codebrowse': CodebrowseService(),
    'memcached': MemcachedService(),
    'rabbitmq': RabbitService(),
    }


def get_services_to_run(requested_services):
    """Return a list of services (TacFiles) given a list of service names.

    If no names are given, then the list of services to run comes from the
    launchpad configuration.

    If names are given, then only run the services matching those names.
    """
    if len(requested_services) == 0:
        return [svc for svc in SERVICES.values() if svc.should_launch]
    return [SERVICES[name] for name in requested_services]


def split_out_runlaunchpad_arguments(args):
    """Split the given command-line arguments into services to start and Zope
    arguments.

    The runlaunchpad script can take an optional '-r services,...' argument.
    If this argument is present, then the value is returned as the first
    element of the return tuple. The rest of the arguments are returned as the
    second element of the return tuple.

    Returns a tuple of the form ([service_name, ...], remaining_argv).
    """
    if len(args) > 1 and args[0] == '-r':
        return args[1].split(','), args[2:]
    return [], args


def process_config_arguments(args):
    """Process the arguments related to the config.

    -i  Will set the instance name aka LPCONFIG env.
    """
    if '-i' in args:
        index = args.index('-i')
        config.setInstance(args[index + 1])
        del args[index:index + 2]
    return args


def start_testapp(argv=list(sys.argv)):
    from lp.services.config.fixture import ConfigUseFixture
    from lp.testing.layers import (
        BaseLayer,
        DatabaseLayer,
        LibrarianLayer,
        RabbitMQLayer,
        )
    from lp.testing.pgsql import (
        installFakeConnect,
        uninstallFakeConnect,
        )
    assert config.instance_name.startswith('testrunner-appserver'), (
        '%r does not start with "testrunner-appserver"' %
        config.instance_name)
    interactive_tests = 'INTERACTIVE_TESTS' in os.environ
    teardowns = []

    def setup():
        # This code needs to be run after other zcml setup happens in
        # runlaunchpad, so it is passed in as a callable.  We set up layers
        # here because we need to control fixtures within this process, and
        # because we want interactive tests to be as similar as possible to
        # tests run in the testrunner.
        # Note that this changes the config instance-name, with the result
        # that the configuration of utilities may become invalidated.
        # XXX Robert Collins, bug=883980: In short, we should derive the
        # other services from the test runner, rather than duplicating
        # the work of test setup within the slave appserver. That will
        # permit reuse of the librarian, DB, rabbit etc, and
        # correspondingly easier assertions and inspection of interactions
        # with other services. That would mean we do not need to set up rabbit
        # or the librarian here: the test runner would control and take care
        # of that.
        BaseLayer.setUp()
        teardowns.append(BaseLayer.tearDown)
        RabbitMQLayer.setUp()
        teardowns.append(RabbitMQLayer.tearDown)
        # We set up the database here even for the test suite because we want
        # to be able to control the database here in the subprocess.  It is
        # possible to do that when setting the database up in the parent
        # process, but it is messier.  This is simple.
        installFakeConnect()
        teardowns.append(uninstallFakeConnect)
        DatabaseLayer.setUp()
        teardowns.append(DatabaseLayer.tearDown)
        # The Librarian needs access to the database, so setting it up here
        # where we are setting up the database makes the most sense.
        LibrarianLayer.setUp()
        teardowns.append(LibrarianLayer.tearDown)
        # Switch to the appserver config.
        fixture = ConfigUseFixture(BaseLayer.appserver_config_name)
        fixture.setUp()
        teardowns.append(fixture.cleanUp)
        if interactive_tests:
            root_url = config.appserver_root_url()
            print('*' * 70)
            print('In a few seconds, go to ' + root_url + '/+yuitest')
            print('*' * 70)
    try:
        start_launchpad(argv, setup)
    finally:
        teardowns.reverse()
        for teardown in teardowns:
            try:
                teardown()
            except NotImplementedError:
                # We are in a separate process anyway.  Bah.
                pass


def gunicorn_main():
    orig_argv = sys.argv
    try:
        sys.argv = [
            os.path.join(config.root, "bin", "talisker.gunicorn"),
            "lp.startwsgi",
            "-c", os.path.join(config.config_dir, "gunicorn.conf.py")
        ]
        run_gunicorn()
        return
    finally:
        sys.argv = orig_argv


def start_launchpad(argv=list(sys.argv), setup=None):
    # We really want to replace this with a generic startup harness.
    # However, this should last us until this is developed
    services, argv = split_out_runlaunchpad_arguments(argv[1:])
    argv = process_config_arguments(argv)
    services = get_services_to_run(services)
    # Create the ZCML override file based on the instance.
    config.generate_overrides()
    # Many things rely on a directory called 'logs' existing in the current
    # working directory.
    ensure_directory_exists('logs')
    if setup is not None:
        # This is the setup from start_testapp, above.
        setup()
    try:
        with ExitStack() as stack:
            for service in services:
                stack.enter_context(service)
            # Store our process id somewhere
            make_pidfile('launchpad')
            if config.launchpad.launch:
                gunicorn_main()
            else:
                # We just need the foreground process to sit around forever
                # waiting for the signal to shut everything down.  Normally,
                # Zope itself would be this master process, but we're not
                # starting that up, so we need to do something else.
                try:
                    signal.pause()
                except KeyboardInterrupt:
                    pass
    except Exception as e:
        print("stopping services on exception %r" % e, file=sys.stderr)
        for service in services:
            print(service, "fixture details:", file=sys.stderr)
            # There may be no details on some services if they haven't been
            # initialized yet.
            if getattr(service, '_details', None) is None:
                print("(not ready yet?)", file=sys.stderr)
                continue
            details_str = _details_to_str(service.getDetails())
            if details_str:
                print(details_str, file=sys.stderr)
            else:
                print("(no details present)", file=sys.stderr)
        raise


def start_librarian():
    """Start the Librarian in the background."""
    # Create the ZCML override file based on the instance.
    config.generate_overrides()
    # Create the Librarian storage directory if it doesn't already exist.
    prepare_for_librarian()
    pidfile = pidfile_path('librarian')
    cmd = [
        tachandler.twistd_script,
        "--python", 'daemons/librarian.tac',
        "--pidfile", pidfile,
        "--prefix", 'Librarian',
        "--logfile", config.librarian_server.logfile,
        ]
    return subprocess.call(cmd)
