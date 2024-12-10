# Copyright 2009-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Mock Build objects for tests soyuz buildd-system."""

__all__ = [
    "AbortingWorker",
    "BrokenWorker",
    "BuildingWorker",
    "DeadProxy",
    "LostBuildingBrokenWorker",
    "make_publisher",
    "MockBuilder",
    "OkWorker",
    "TrivialBehaviour",
    "WaitingWorker",
    "WorkerTestHelpers",
]

import os
import shlex
import sys
import xmlrpc.client
from collections import OrderedDict
from importlib import resources
from textwrap import dedent

import fixtures
from testtools.content import attach_file
from twisted.internet import defer
from twisted.web.xmlrpc import Proxy
from txfixtures.tachandler import TacTestFixture

from lp.buildmaster.enums import BuilderCleanStatus, BuilderResetProtocol
from lp.buildmaster.interactor import BuilderWorker
from lp.buildmaster.interfaces.builder import CannotFetchFile
from lp.buildmaster.model.builder import region_re
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

    def __init__(
        self,
        name="mock-builder",
        builderok=True,
        manual=False,
        processors=None,
        virtualized=True,
        vm_host=None,
        url="http://fake:0000",
        version=None,
        clean_status=BuilderCleanStatus.DIRTY,
        vm_reset_protocol=BuilderResetProtocol.PROTO_1_1,
        open_resources=None,
        restricted_resources=None,
        active=True,
    ):
        self.currentjob = None
        self.builderok = builderok
        self.manual = manual
        self.url = url
        self.name = name
        self.processors = processors or []
        self.virtualized = virtualized
        self.vm_host = vm_host
        self.vm_reset_protocol = vm_reset_protocol
        self.open_resources = open_resources
        self.restricted_resources = restricted_resources
        self.failnotes = None
        self.version = version
        self.clean_status = clean_status
        self.active = active
        self.failure_count = 0

    def setCleanStatus(self, clean_status):
        self.clean_status = clean_status

    def failBuilder(self, reason):
        self.builderok = False
        self.failnotes = reason

    @property
    def region(self):
        region_match = region_re.match(self.name)
        return region_match.group(1) if region_match is not None else ""


# XXX: It would be *really* nice to run some set of tests against the real
# BuilderWorker and this one to prevent interface skew.
class OkWorker:
    """An idle mock worker that prints information about itself.

    The architecture tag can be customised during initialization."""

    def __init__(self, arch_tag=I386_ARCHITECTURE_NAME, version=None):
        self.call_log = []
        self.arch_tag = arch_tag
        self.version = version

    @property
    def method_log(self):
        return [(x[0] if isinstance(x, tuple) else x) for x in self.call_log]

    def status(self):
        self.call_log.append("status")
        worker_status = {"builder_status": "BuilderStatus.IDLE"}
        if self.version is not None:
            worker_status["builder_version"] = self.version
        return defer.succeed(worker_status)

    def ensurepresent(self, sha1, url, user=None, password=None):
        self.call_log.append(("ensurepresent", url, user, password))
        return defer.succeed((True, None))

    def build(self, buildid, buildtype, chroot, filemap, args):
        self.call_log.append(
            ("build", buildid, buildtype, chroot, list(filemap), args)
        )
        return defer.succeed(("BuildStatus.BUILDING", buildid))

    def echo(self, *args):
        self.call_log.append(("echo",) + args)
        return defer.succeed(args)

    def clean(self):
        self.call_log.append("clean")
        return defer.succeed(None)

    def abort(self):
        self.call_log.append("abort")
        return defer.succeed(None)

    def info(self):
        self.call_log.append("info")
        return defer.succeed(("1.0", self.arch_tag, "binarypackage"))

    def proxy_info(self):
        self.call_log.append("proxy_info")
        return defer.succeed(
            {
                "revocation_endpoint": (
                    "http://fetch-service.test:9999/session/"
                    "9138904ce3be9ffd4d0/token"
                ),
                "use_fetch_service": False,
            }
        )

    def resume(self):
        self.call_log.append("resume")
        return defer.succeed(("", "", 0))

    @defer.inlineCallbacks
    def sendFileToWorker(
        self, sha1, url, username="", password="", logger=None
    ):
        present, info = yield self.ensurepresent(sha1, url, username, password)
        if not present:
            raise CannotFetchFile(url, info)

    def getURL(self, sha1):
        return urlappend("http://localhost:8221/filecache/", sha1).encode(
            "utf8"
        )

    def getFiles(self, files, logger=None):
        dl = defer.gatherResults(
            [
                self.getFile(builder_file, local_file)
                for builder_file, local_file in files
            ]
        )
        return dl


class BuildingWorker(OkWorker):
    """A mock worker that looks like it's currently building."""

    def __init__(self, build_id="1-1"):
        super().__init__()
        self.build_id = build_id
        self.status_count = 0

    def status(self):
        self.call_log.append("status")
        buildlog = xmlrpc.client.Binary(
            b"This is a build log: %d" % self.status_count
        )
        self.status_count += 1
        return defer.succeed(
            {
                "builder_status": "BuilderStatus.BUILDING",
                "build_id": self.build_id,
                "logtail": buildlog,
            }
        )

    def getFile(self, sum, file_to_write):
        self.call_log.append("getFile")
        if sum == "buildlog":
            if isinstance(file_to_write, str):
                file_to_write = open(file_to_write, "wb")
            file_to_write.write(b"This is a build log")
            file_to_write.close()
        return defer.succeed(None)


class WaitingWorker(OkWorker):
    """A mock worker that looks like it's currently waiting."""

    def __init__(
        self,
        state="BuildStatus.OK",
        dependencies=None,
        build_id="1-1",
        filemap=None,
    ):
        super().__init__()
        self.state = state
        self.dependencies = dependencies
        self.build_id = build_id
        if filemap is None:
            self.filemap = {}
        else:
            self.filemap = filemap

        # By default, the worker only has a buildlog, but callsites
        # can update this list as needed.
        self.valid_files = {"buildlog": ""}
        self._got_file_record = []

    def status(self):
        self.call_log.append("status")
        return defer.succeed(
            {
                "builder_status": "BuilderStatus.WAITING",
                "build_status": self.state,
                "build_id": self.build_id,
                "filemap": self.filemap,
                "dependencies": self.dependencies,
            }
        )

    def getFile(self, hash, file_to_write):
        self.call_log.append("getFile")
        if hash in self.valid_files:
            if isinstance(file_to_write, str):
                file_to_write = open(file_to_write, "wb")
            if not self.valid_files[hash]:
                content = ("This is a %s" % hash).encode("ASCII")
            else:
                with open(self.valid_files[hash], "rb") as source:
                    content = source.read()
            file_to_write.write(content)
            file_to_write.close()
            self._got_file_record.append(hash)
        return defer.succeed(None)


class AbortingWorker(OkWorker):
    """A mock worker that looks like it's in the process of aborting."""

    def status(self):
        self.call_log.append("status")
        return defer.succeed(
            {
                "builder_status": "BuilderStatus.ABORTING",
                "build_id": "1-1",
            }
        )


class LostBuildingBrokenWorker:
    """A mock worker building bogus Build/BuildQueue IDs that can't be aborted.

    When 'aborted' it raises an xmlrpc.client.Fault(8002, 'Could not abort')
    """

    def __init__(self):
        self.call_log = []

    def status(self):
        self.call_log.append("status")
        return defer.succeed(
            {
                "builder_status": "BuilderStatus.BUILDING",
                "build_id": "1000-10000",
            }
        )

    def abort(self):
        self.call_log.append("abort")
        return defer.fail(xmlrpc.client.Fault(8002, "Could not abort"))

    def resume(self):
        self.call_log.append("resume")
        return defer.succeed(("", "", 0))


class BrokenWorker:
    """A mock worker that reports that it is broken."""

    def __init__(self):
        self.call_log = []

    def status(self):
        self.call_log.append("status")
        return defer.fail(xmlrpc.client.Fault(8001, "Broken worker"))


class TrivialBehaviour:
    pass


class DeadProxy(Proxy):
    """An xmlrpc.Proxy that doesn't actually send any messages.

    Used when you want to test timeouts, for example.
    """

    def callRemote(self, *args, **kwargs):
        return defer.Deferred()


# XXX cjwatson 2022-11-30:
# https://git.launchpad.net/launchpad-buildd/commit?id=a42da402b9 made the
# harness less stateful in a way that's useful for some of our tests, but
# unfortunately it was after launchpad-buildd began to require Python >= 3.6
# which we can't yet do in Launchpad itself.  Copy launchpad-buildd's code
# for now, but once Launchpad is running on Python >= 3.6 we should go back
# to subclassing it.  (For similar reasons, we're currently stuck with some
# non-inclusive terminology here until we can upgrade the version of
# launchpad-buildd in our virtualenv.)
class LPBuilddTestSetup(TacTestFixture):
    """A BuilddTestSetup that uses the LP virtualenv."""

    _root = None

    def setUp(self):
        super().setUp(python_path=sys.executable, twistd_script=twistd_script)

    def setUpRoot(self):
        filecache = os.path.join(self.root, "filecache")
        os.mkdir(filecache)
        self.useFixture(fixtures.EnvironmentVariable("HOME", self.root))
        test_conffile = os.path.join(self.root, "buildd.conf")
        with open(test_conffile, "w") as f:
            f.write(
                dedent(
                    """\
                    [builder]
                    architecturetag = i386
                    filecache = {filecache}
                    bindhost = localhost
                    bindport = {self.daemon_port}
                    sharepath = {self.root}
                    """.format(
                        filecache=filecache, self=self
                    )
                )
            )
        self.useFixture(
            fixtures.EnvironmentVariable("BUILDD_SLAVE_CONFIG", test_conffile)
        )

    @property
    def root(self):
        if self._root is None:
            self._root = self.useFixture(fixtures.TempDir()).path
        return self._root

    @property
    def tacfile(self):
        # importlib.resources.path makes no guarantees about whether the
        # path is still valid after exiting the context manager (it might be
        # a temporary file), but in practice this works fine in Launchpad's
        # virtualenv setup.
        with resources.path("lpbuildd", "buildd-slave.tac") as tacpath:
            pass
        return tacpath.as_posix()

    @property
    def pidfile(self):
        return os.path.join(self.root, "buildd.pid")

    @property
    def logfile(self):
        return "/var/tmp/buildd.log"

    @property
    def daemon_port(self):
        return 8321


class WorkerTestHelpers(fixtures.Fixture):
    @property
    def base_url(self):
        """The URL for the XML-RPC service set up by `BuilddTestSetup`."""
        return "http://localhost:%d" % LPBuilddTestSetup().daemon_port

    def getServerWorker(self):
        """Set up a test build worker server.

        :return: A `BuilddTestSetup` object.
        """
        tachandler = self.useFixture(LPBuilddTestSetup())
        attach_file(
            self, tachandler.logfile, name="xmlrpc-log-file", buffer_now=False
        )
        return tachandler

    def getClientWorker(
        self, reactor=None, proxy=None, pool=None, process_pool=None
    ):
        """Return a `BuilderWorker` for use in testing.

        Points to a fixed URL that is also used by `BuilddTestSetup`.
        """
        return BuilderWorker.makeBuilderWorker(
            self.base_url,
            "vmhost",
            config.builddmaster.socket_timeout,
            reactor=reactor,
            proxy=proxy,
            pool=pool,
            process_pool=process_pool,
        )

    def makeCacheFile(self, tachandler, filename, contents=b"something"):
        """Make a cache file available on the remote worker.

        :param tachandler: The TacTestSetup object used to start the remote
            worker.
        :param filename: The name of the file to create in the file cache
            area.
        :param contents: Bytes to write to the file.
        """
        path = os.path.join(tachandler.root, "filecache", filename)
        with open(path, "wb") as fd:
            fd.write(contents)
        self.addCleanup(os.unlink, path)

    def configureWaitingBuilder(self, tachandler):
        """Set up a builder to wait forever until told to stop."""
        fifo = os.path.join(tachandler.root, "builder-prep.fifo")
        os.mkfifo(fifo)
        builder_prep = os.path.join(tachandler.root, "bin", "builder-prep")
        os.makedirs(os.path.dirname(builder_prep), exist_ok=True)
        with open(builder_prep, "w") as f:
            f.write("#! /bin/sh\nread x <%s\nexit 1\n" % shlex.quote(fifo))
            os.fchmod(f.fileno(), 0o755)
        # This is run on cleanup, and we don't want it to fail.
        in_target = os.path.join(tachandler.root, "bin", "in-target")
        os.symlink("/bin/true", in_target)
        self.addCleanup(self.continueBuild, tachandler)

    def continueBuild(self, tachandler):
        """Continue a build set up to wait via `configureWaitingBuilder`."""
        flag = os.path.join(tachandler.root, "builder-prep.continued")
        if not os.path.exists(flag):
            fifo = os.path.join(tachandler.root, "builder-prep.fifo")
            with open(fifo, "w") as f:
                f.write("\n")
            with open(flag, "w"):
                pass

    def triggerGoodBuild(self, worker, build_id=None):
        """Trigger a good build on 'worker'.

        :param worker: A `BuilderWorker` instance to trigger the build on.
        :param build_id: The build identifier. If not specified, defaults to
            an arbitrary string.
        :type build_id: str
        :return: The build id returned by the worker.
        """
        if build_id is None:
            build_id = "random-build-id"
        tachandler = self.getServerWorker()
        chroot_file = "fake-chroot"
        dsc_file = "thing"
        self.makeCacheFile(tachandler, chroot_file)
        self.makeCacheFile(tachandler, dsc_file)
        self.configureWaitingBuilder(tachandler)
        extra_args = {
            "distribution": "ubuntu",
            "series": "precise",
            "suite": "precise",
            "ogrecomponent": "main",
        }
        return worker.build(
            build_id,
            "binarypackage",
            chroot_file,
            # Although a single-element dict obviously has stable ordering,
            # we use an OrderedDict anyway to test that BuilderWorker
            # serializes it correctly over XML-RPC.
            OrderedDict([(".dsc", dsc_file)]),
            extra_args,
        )
