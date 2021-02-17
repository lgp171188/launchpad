# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Mock Build objects for tests soyuz buildd-system."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type

__all__ = [
    'AbortingSlave',
    'BrokenSlave',
    'BuildingSlave',
    'DeadProxy',
    'LostBuildingBrokenSlave',
    'make_publisher',
    'MockBuilder',
    'OkSlave',
    'SlaveTestHelpers',
    'TrivialBehaviour',
    'WaitingSlave',
    ]

import os
import sys

import fixtures
from lpbuildd.tests.harness import BuilddSlaveTestSetup
import six
from six.moves import xmlrpc_client
from testtools.content import attach_file
from twisted.internet import defer
from twisted.web import xmlrpc

from lp.buildmaster.enums import (
    BuilderCleanStatus,
    BuilderResetProtocol,
    )
from lp.buildmaster.interactor import BuilderSlave
from lp.buildmaster.interfaces.builder import CannotFetchFile
from lp.services.config import config
from lp.services.daemons.tachandler import twistd_script
from lp.services.webapp import urlappend
from lp.testing.sampledata import I386_ARCHITECTURE_NAME


def make_publisher():
    """Make a Soyuz test publisher."""
    # Avoid circular imports.
    from lp.soyuz.tests.test_publishing import SoyuzTestPublisher
    return SoyuzTestPublisher()


class MockBuilder:
    """Emulates a IBuilder class."""

    def __init__(self, name='mock-builder', builderok=True, manual=False,
                 processors=None, virtualized=True, vm_host=None,
                 url='http://fake:0000', version=None,
                 clean_status=BuilderCleanStatus.DIRTY,
                 vm_reset_protocol=BuilderResetProtocol.PROTO_1_1,
                 active=True):
        self.currentjob = None
        self.builderok = builderok
        self.manual = manual
        self.url = url
        self.name = name
        self.processors = processors or []
        self.virtualized = virtualized
        self.vm_host = vm_host
        self.vm_reset_protocol = vm_reset_protocol
        self.failnotes = None
        self.version = version
        self.clean_status = clean_status
        self.active = active

    def setCleanStatus(self, clean_status):
        self.clean_status = clean_status

    def failBuilder(self, reason):
        self.builderok = False
        self.failnotes = reason


# XXX: It would be *really* nice to run some set of tests against the real
# BuilderSlave and this one to prevent interface skew.
class OkSlave:
    """An idle mock slave that prints information about itself.

    The architecture tag can be customised during initialization."""

    def __init__(self, arch_tag=I386_ARCHITECTURE_NAME, version=None):
        self.call_log = []
        self.arch_tag = arch_tag
        self.version = version

    @property
    def method_log(self):
        return [(x[0] if isinstance(x, tuple) else x) for x in self.call_log]

    def status(self):
        self.call_log.append('status')
        slave_status = {'builder_status': 'BuilderStatus.IDLE'}
        if self.version is not None:
            slave_status['builder_version'] = self.version
        return defer.succeed(slave_status)

    def ensurepresent(self, sha1, url, user=None, password=None):
        self.call_log.append(('ensurepresent', url, user, password))
        return defer.succeed((True, None))

    def build(self, buildid, buildtype, chroot, filemap, args):
        self.call_log.append(
            ('build', buildid, buildtype, chroot, list(filemap), args))
        return defer.succeed(('BuildStatus.BUILDING', buildid))

    def echo(self, *args):
        self.call_log.append(('echo',) + args)
        return defer.succeed(args)

    def clean(self):
        self.call_log.append('clean')
        return defer.succeed(None)

    def abort(self):
        self.call_log.append('abort')
        return defer.succeed(None)

    def info(self):
        self.call_log.append('info')
        return defer.succeed(('1.0', self.arch_tag, 'binarypackage'))

    def resume(self):
        self.call_log.append('resume')
        return defer.succeed(("", "", 0))

    @defer.inlineCallbacks
    def sendFileToSlave(self, sha1, url, username="", password="",
                        logger=None):
        present, info = yield self.ensurepresent(sha1, url, username, password)
        if not present:
            raise CannotFetchFile(url, info)

    def getURL(self, sha1):
        return urlappend(
            'http://localhost:8221/filecache/', sha1).encode('utf8')

    def getFiles(self, files, logger=None):
        dl = defer.gatherResults([
            self.getFile(builder_file, local_file)
            for builder_file, local_file in files])
        return dl


class BuildingSlave(OkSlave):
    """A mock slave that looks like it's currently building."""

    def __init__(self, build_id='1-1'):
        super(BuildingSlave, self).__init__()
        self.build_id = build_id
        self.status_count = 0

    def status(self):
        self.call_log.append('status')
        buildlog = xmlrpc_client.Binary(
            b"This is a build log: %d" % self.status_count)
        self.status_count += 1
        return defer.succeed({
            'builder_status': 'BuilderStatus.BUILDING',
            'build_id': self.build_id,
            'logtail': buildlog,
            })

    def getFile(self, sum, file_to_write):
        self.call_log.append('getFile')
        if sum == "buildlog":
            if isinstance(file_to_write, six.string_types):
                file_to_write = open(file_to_write, 'wb')
            file_to_write.write("This is a build log")
            file_to_write.close()
        return defer.succeed(None)


class WaitingSlave(OkSlave):
    """A mock slave that looks like it's currently waiting."""

    def __init__(self, state='BuildStatus.OK', dependencies=None,
                 build_id='1-1', filemap=None):
        super(WaitingSlave, self).__init__()
        self.state = state
        self.dependencies = dependencies
        self.build_id = build_id
        if filemap is None:
            self.filemap = {}
        else:
            self.filemap = filemap

        # By default, the slave only has a buildlog, but callsites
        # can update this list as needed.
        self.valid_files = {'buildlog': ''}
        self._got_file_record = []

    def status(self):
        self.call_log.append('status')
        return defer.succeed({
            'builder_status': 'BuilderStatus.WAITING',
            'build_status': self.state,
            'build_id': self.build_id,
            'filemap': self.filemap,
            'dependencies': self.dependencies,
            })

    def getFile(self, hash, file_to_write):
        self.call_log.append('getFile')
        if hash in self.valid_files:
            if isinstance(file_to_write, six.string_types):
                file_to_write = open(file_to_write, 'wb')
            if not self.valid_files[hash]:
                content = b"This is a %s" % hash
            else:
                with open(self.valid_files[hash], 'rb') as source:
                    content = source.read()
            file_to_write.write(content)
            file_to_write.close()
            self._got_file_record.append(hash)
        return defer.succeed(None)


class AbortingSlave(OkSlave):
    """A mock slave that looks like it's in the process of aborting."""

    def status(self):
        self.call_log.append('status')
        return defer.succeed({
            'builder_status': 'BuilderStatus.ABORTING',
            'build_id': '1-1',
            })


class LostBuildingBrokenSlave:
    """A mock slave building bogus Build/BuildQueue IDs that can't be aborted.

    When 'aborted' it raises an xmlrpc_client.Fault(8002, 'Could not abort')
    """

    def __init__(self):
        self.call_log = []

    def status(self):
        self.call_log.append('status')
        return defer.succeed({
            'builder_status': 'BuilderStatus.BUILDING',
            'build_id': '1000-10000',
            })

    def abort(self):
        self.call_log.append('abort')
        return defer.fail(xmlrpc_client.Fault(8002, "Could not abort"))

    def resume(self):
        self.call_log.append('resume')
        return defer.succeed(("", "", 0))


class BrokenSlave:
    """A mock slave that reports that it is broken."""

    def __init__(self):
        self.call_log = []

    def status(self):
        self.call_log.append('status')
        return defer.fail(xmlrpc_client.Fault(8001, "Broken slave"))


class TrivialBehaviour:
    pass


class DeadProxy(xmlrpc.Proxy):
    """An xmlrpc.Proxy that doesn't actually send any messages.

    Used when you want to test timeouts, for example.
    """

    def callRemote(self, *args, **kwargs):
        return defer.Deferred()


class LPBuilddSlaveTestSetup(BuilddSlaveTestSetup):
    """A BuilddSlaveTestSetup that uses the LP virtualenv."""

    def setUp(self):
        super(LPBuilddSlaveTestSetup, self).setUp(
            python_path=sys.executable,
            twistd_script=twistd_script)


class SlaveTestHelpers(fixtures.Fixture):

    @property
    def base_url(self):
        """The URL for the XML-RPC service set up by `BuilddSlaveTestSetup`."""
        return 'http://localhost:%d' % LPBuilddSlaveTestSetup().daemon_port

    def getServerSlave(self):
        """Set up a test build slave server.

        :return: A `BuilddSlaveTestSetup` object.
        """
        tachandler = self.useFixture(LPBuilddSlaveTestSetup())
        attach_file(
            self, tachandler.logfile, name='xmlrpc-log-file', buffer_now=False)
        return tachandler

    def getClientSlave(self, reactor=None, proxy=None,
                       pool=None, process_pool=None):
        """Return a `BuilderSlave` for use in testing.

        Points to a fixed URL that is also used by `BuilddSlaveTestSetup`.
        """
        return BuilderSlave.makeBuilderSlave(
            self.base_url, 'vmhost', config.builddmaster.socket_timeout,
            reactor=reactor, proxy=proxy, pool=pool, process_pool=process_pool)

    def makeCacheFile(self, tachandler, filename, contents=b'something'):
        """Make a cache file available on the remote slave.

        :param tachandler: The TacTestSetup object used to start the remote
            slave.
        :param filename: The name of the file to create in the file cache
            area.
        :param contents: Bytes to write to the file.
        """
        path = os.path.join(tachandler.root, 'filecache', filename)
        with open(path, 'wb') as fd:
            fd.write(contents)
        self.addCleanup(os.unlink, path)

    def triggerGoodBuild(self, slave, build_id=None):
        """Trigger a good build on 'slave'.

        :param slave: A `BuilderSlave` instance to trigger the build on.
        :param build_id: The build identifier. If not specified, defaults to
            an arbitrary string.
        :type build_id: str
        :return: The build id returned by the slave.
        """
        if build_id is None:
            build_id = 'random-build-id'
        tachandler = self.getServerSlave()
        chroot_file = 'fake-chroot'
        dsc_file = 'thing'
        self.makeCacheFile(tachandler, chroot_file)
        self.makeCacheFile(tachandler, dsc_file)
        extra_args = {
            'distribution': 'ubuntu',
            'series': 'precise',
            'suite': 'precise',
            'ogrecomponent': 'main',
            }
        return slave.build(
            build_id, 'binarypackage', chroot_file, {'.dsc': dsc_file},
            extra_args)
