# Copyright 2015-2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `OCIRecipeBuildBehavior`."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type

from datetime import datetime
import json
import os
import shutil
import tempfile
from textwrap import dedent
import time
import uuid

import fixtures
from six.moves.urllib_parse import urlsplit
from testtools import ExpectedException
from testtools.matchers import (
    AfterPreprocessing,
    Equals,
    HasLength,
    Is,
    MatchesDict,
    MatchesStructure,
    )
from twisted.internet import (
    defer,
    endpoints,
    reactor,
    )
from twisted.python.compat import nativeString
from twisted.trial.unittest import TestCase as TrialTestCase
from twisted.web import (
    resource,
    server,
    xmlrpc,
    )
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.buildmaster.enums import BuildStatus
from lp.buildmaster.interactor import BuilderInteractor
from lp.buildmaster.interfaces.builder import BuildDaemonError
from lp.buildmaster.interfaces.buildfarmjobbehaviour import (
    IBuildFarmJobBehaviour,
    )
from lp.buildmaster.interfaces.processor import IProcessorSet
from lp.buildmaster.tests.mock_slaves import (
    MockBuilder,
    OkSlave,
    SlaveTestHelpers,
    WaitingSlave,
    )
from lp.buildmaster.tests.test_buildfarmjobbehaviour import (
    TestGetUploadMethodsMixin,
    )
from lp.oci.model.ocirecipebuildbehaviour import OCIRecipeBuildBehaviour
from lp.registry.interfaces.series import SeriesStatus
from lp.services.config import config
from lp.soyuz.adapters.archivedependencies import (
    get_sources_list_for_building,
    )
from lp.soyuz.interfaces.component import IComponentSet
from lp.testing import TestCaseWithFactory
from lp.testing.dbuser import dbuser
from lp.testing.factory import LaunchpadObjectFactory
from lp.testing.fakemethod import FakeMethod
from lp.testing.layers import LaunchpadZopelessLayer
from lp.testing.mail_helpers import pop_notifications


class ProxyAuthAPITokensResource(resource.Resource):
    """A test tokens resource for the proxy authentication API."""

    isLeaf = True

    def __init__(self):
        resource.Resource.__init__(self)
        self.requests = []

    def render_POST(self, request):
        content = request.content.read()
        self.requests.append({
            "method": request.method,
            "uri": request.uri,
            "headers": dict(request.requestHeaders.getAllRawHeaders()),
            "content": content,
            })
        username = json.loads(content)["username"]
        return json.dumps({
            "username": username,
            "secret": uuid.uuid4().hex,
            "timestamp": datetime.utcnow().isoformat(),
            })


class InProcessProxyAuthAPIFixture(fixtures.Fixture):
    """A fixture that pretends to be the proxy authentication API.

    Users of this fixture must call the `start` method, which returns a
    `Deferred`, and arrange for that to get back to the reactor.  This is
    necessary because the basic fixture API does not allow `setUp` to return
    anything.  For example:

        class TestSomething(TestCase):

            run_tests_with = AsynchronousDeferredRunTest.make_factory(
                timeout=10)

            @defer.inlineCallbacks
            def setUp(self):
                super(TestSomething, self).setUp()
                yield self.useFixture(InProcessProxyAuthAPIFixture()).start()
    """

    @defer.inlineCallbacks
    def start(self):
        root = resource.Resource()
        self.tokens = ProxyAuthAPITokensResource()
        root.putChild("tokens", self.tokens)
        endpoint = endpoints.serverFromString(reactor, nativeString("tcp:0"))
        site = server.Site(self.tokens)
        self.addCleanup(site.stopFactory)
        port = yield endpoint.listen(site)
        self.addCleanup(port.stopListening)
        config.push("in-process-proxy-auth-api-fixture", dedent("""
            [oci]
            builder_proxy_auth_api_admin_secret: admin-secret
            builder_proxy_auth_api_endpoint: http://%s:%s/tokens
            """) %
            (port.getHost().host, port.getHost().port))
        self.addCleanup(config.pop, "in-process-proxy-auth-api-fixture")


class MakeOCIBuildMixin:

    def makeBuild(self):
        build = self.factory.makeOCIRecipeBuild()
        distro_series = self.factory.makeDistroSeries(
            distribution=build.recipe.oci_project.distribution,
            status=SeriesStatus.CURRENT)
        build.queueBuild()
        return build

    def makeUnmodifiableBuild(self):
        build = self.factory.makeOCIRecipeBuild()
        build.distro_arch_series = 'failed'
        build.queueBuild()
        return build


class TestOCIBuildBehaviour(TestCaseWithFactory):

    layer = LaunchpadZopelessLayer

    @defer.inlineCallbacks
    def setUp(self):
        super(TestOCIBuildBehaviour, self).setUp()
        build_username = 'OCIBUILD-1'
        self.token = {'secret': uuid.uuid4().get_hex(),
                    'username': build_username,
                    'timestamp': datetime.utcnow().isoformat()}
        self.proxy_url = ("http://{username}:{password}"
                        "@{host}:{port}".format(
                            username=self.token['username'],
                            password=self.token['secret'],
                            host=config.oci.builder_proxy_host,
                            port=config.oci.builder_proxy_port))
        self.proxy_api = self.useFixture(InProcessProxyAuthAPIFixture())
        yield self.proxy_api.start()
        self.now = time.time()
        self.useFixture(fixtures.MockPatch(
            "time.time", return_value=self.now))

    def makeJob(self, archive=None, **kwargs):
        """Create a sample `IOCIRecipeBuildBehaviour`."""
        if archive is None:
            distribution = self.factory.makeDistribution(name="distro")
        else:
            distribution = archive.distribution
        distroseries = self.factory.makeDistroSeries(
            distribution=distribution, name="unstable",
            status=SeriesStatus.CURRENT)
        processor = getUtility(IProcessorSet).getByName("386")
        distroarchseries = self.factory.makeDistroArchSeries(
            distroseries=distroseries, architecturetag="i386",
            processor=processor)
        distroseries.nominatedarchindep = distroarchseries
        oci_project = self.factory.makeOCIProject(pillar=distribution)
        recipe = self.factory.makeOCIRecipe(
            name="test-oci-recipe", oci_project=oci_project, **kwargs)
        build = self.factory.makeOCIRecipeBuild(
            distro_arch_series=distroarchseries,
            recipe=recipe)

        job = IBuildFarmJobBehaviour(build)
        builder = MockBuilder()
        builder.processor = job.build.processor
        slave = self.useFixture(SlaveTestHelpers()).getClientSlave()
        job.setBuilder(builder, slave)
        self.addCleanup(slave.pool.closeCachedConnections)

        # Taken from test_archivedependencies.py
        for component_name in ["main", "universe"]:
            component = getUtility(IComponentSet)[component_name]
            self.factory.makeComponentSelection(distroseries, component)

        return job

    def getProxyURLMatcher(self, job):
        return AfterPreprocessing(urlsplit, MatchesStructure(
            scheme=Equals("http"),
            username=Equals("{}-{}".format(
                job.build.build_cookie, int(self.now))),
            password=HasLength(32),
            hostname=Equals(config.snappy.builder_proxy_host),
            port=Equals(config.snappy.builder_proxy_port),
            path=Equals("")))

    def getRevocationEndpointMatcher(self, job):
        return Equals("{}/{}-{}".format(
            config.oci.builder_proxy_auth_api_endpoint,
            job.build.build_cookie, int(self.now)))

    def test_provides_interface(self):
        # OCIRecipeBuildBehaviour provides IBuildFarmJobBehaviour.
        job = OCIRecipeBuildBehaviour(None)
        self.assertProvides(job, IBuildFarmJobBehaviour)

    def test_adapts_IOCIRecipeBuild(self):
        # IBuildFarmJobBehaviour adapts an IOCIRecipeBuild.
        build = self.factory.makeOCIRecipeBuild()
        job = IBuildFarmJobBehaviour(build)
        self.assertProvides(job, IBuildFarmJobBehaviour)

    @defer.inlineCallbacks
    def test_extraBuildArgs_git(self):
        # extraBuildArgs returns appropriate arguments if asked to build a
        # job for a Git branch.
        [ref] = self.factory.makeGitRefs()
        job = self.makeJob(git_ref=ref)
        expected_archives, expected_trusted_keys = (
            yield get_sources_list_for_building(
                job.build, job.build.distro_arch_series, None))
        for archive_line in expected_archives:
            self.assertIn('universe', archive_line)
        with dbuser(config.builddmaster.dbuser):
            args = yield job.extraBuildArgs()
        self.assertThat(args, MatchesDict({
            "archive_private": Is(False),
            "archives": Equals(expected_archives),
            "arch_tag": Equals("i386"),
            "build_file": Equals(job.build.recipe.build_file),
            # "build_url": Equals(canonical_url(job.build)),
            "fast_cleanup": Is(True),
            "git_repository": Equals(ref.repository.git_https_url),
            "git_path": Equals(ref.name),
            "name": Equals("test-oci-recipe"),
            "proxy_url": self.getProxyURLMatcher(job),
            "revocation_endpoint": self.getRevocationEndpointMatcher(job),
            "series": Equals("unstable"),
            "trusted_keys": Equals(expected_trusted_keys),
            }))


class TestHandleStatusForOCIRecipeBuild(MakeOCIBuildMixin, TrialTestCase,
                                        fixtures.TestWithFixtures):
    # This is mostly copied from TestHandleStatusMixin, however
    # we can't use all of those tests, due to the way OCIRecipeBuildBehaviour
    # parses the file contents, rather than just retrieving all that are
    # available. There's also some differences in the filemap handling, as
    # we need a much more complex filemap here.

    layer = LaunchpadZopelessLayer

    def pushConfig(self, section, **kwargs):
        """Push some key-value pairs into a section of the config.

        The config values will be restored during test tearDown.
        """
        # Taken from lp/testing.py as we're using TrialTestCase,
        # not lp.testing.TestCase, as we need to handle the deferred
        # correctly.
        name = self.factory.getUniqueString()
        body = '\n'.join("%s: %s" % (k, v) for k, v in kwargs.iteritems())
        config.push(name, "\n[%s]\n%s\n" % (section, body))
        self.addCleanup(config.pop, name)

    def _createTestFile(self, name, content, hash):
        path = os.path.join(self.test_files_dir, name)
        with open(path, 'wb') as fp:
            fp.write(content)
        self.slave.valid_files[hash] = path

    def setUp(self):
        super(TestHandleStatusForOCIRecipeBuild, self).setUp()
        self.factory = LaunchpadObjectFactory()
        self.build = self.makeBuild()
        # For the moment, we require a builder for the build so that
        # handleStatus_OK can get a reference to the slave.
        self.builder = self.factory.makeBuilder()
        self.build.buildqueue_record.markAsBuilding(self.builder)
        self.slave = WaitingSlave('BuildStatus.OK')
        self.slave.valid_files['test_file_hash'] = ''
        self.interactor = BuilderInteractor()
        self.behaviour = self.interactor.getBuildBehaviour(
            self.build.buildqueue_record, self.builder, self.slave)

        # We overwrite the buildmaster root to use a temp directory.
        tempdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tempdir)
        self.upload_root = tempdir
        self.pushConfig('builddmaster', root=self.upload_root)

        # We stub out our build's getUploaderCommand() method so
        # we can check whether it was called as well as
        # verifySuccessfulUpload().
        removeSecurityProxy(self.build).verifySuccessfulUpload = FakeMethod(
            result=True)

        digests = {
            "diff_id_1": {
                "digest": "digest_1",
                "source": "test/base_1",
                "layer_id": "layer_1"
            },
            "diff_id_2": {
                "digest": "digest_2",
                "source": "",
                "layer_id": "layer_2"
            }
        }

        self.test_files_dir = tempfile.mkdtemp()
        self._createTestFile('buildlog', '', 'buildlog')
        self._createTestFile(
            'manifest.json',
            '[{"Config": "config_file_1.json", '
            '"Layers": ["layer_1/layer.tar", "layer_2/layer.tar"]}]',
            'manifest_hash')
        self._createTestFile(
            'digests.json',
            json.dumps(digests),
            'digests_hash')
        self._createTestFile(
            'config_file_1.json',
            '{"rootfs": {"diff_ids": ["diff_id_1", "diff_id_2"]}}',
            'config_1_hash')
        self._createTestFile(
            'layer_2.tar.gz',
            '',
            'layer_2_hash'
        )

        self.filemap = {
            'manifest.json': 'manifest_hash',
            'digests.json': 'digests_hash',
            'config_file_1.json': 'config_1_hash',
            'layer_1.tar.gz': 'layer_1_hash',
            'layer_2.tar.gz': 'layer_2_hash'
        }
        self.factory.makeOCIFile(
            build=self.build, layer_file_digest=u'digest_1',
            content="retrieved from librarian")

    def assertResultCount(self, count, result):
        self.assertEqual(
            1, len(os.listdir(os.path.join(self.upload_root, result))))

    @defer.inlineCallbacks
    def test_handleStatus_OK_normal_image(self):
        with dbuser(config.builddmaster.dbuser):
            yield self.behaviour.handleStatus(
                self.build.buildqueue_record, 'OK',
                {'filemap': self.filemap})
        self.assertEqual(
            ['buildlog', 'manifest_hash', 'digests_hash', 'config_1_hash',
             'layer_2_hash'],
            self.slave._got_file_record)
        # This hash should not appear as it is already in the librarian
        self.assertNotIn('layer_1_hash', self.slave._got_file_record)
        self.assertEqual(BuildStatus.UPLOADING, self.build.status)
        self.assertResultCount(1, "incoming")

        # layer_1 should have been retrieved from the librarian
        layer_1_path = os.path.join(
            self.upload_root,
            "incoming",
            self.behaviour.getUploadDirLeaf(self.build.build_cookie),
            str(self.build.archive.id),
            self.build.distribution.name,
            "layer_1.tar.gz"
        )
        with open(layer_1_path, 'rb') as layer_1_fp:
            contents = layer_1_fp.read()
            self.assertEqual(contents, b'retrieved from librarian')

    @defer.inlineCallbacks
    def test_handleStatus_OK_absolute_filepath(self):

        self._createTestFile(
            'manifest.json',
            '[{"Config": "/notvalid/config_file_1.json", '
            '"Layers": ["layer_1/layer.tar", "layer_2/layer.tar"]}]',
            'manifest_hash')

        self.filemap['/notvalid/config_file_1.json'] = 'config_1_hash'

        # A filemap that tries to write to files outside of the upload
        # directory will not be collected.
        with ExpectedException(
                BuildDaemonError,
                "Build returned a file named "
                "'/notvalid/config_file_1.json'."):
            with dbuser(config.builddmaster.dbuser):
                yield self.behaviour.handleStatus(
                    self.build.buildqueue_record, 'OK',
                    {'filemap': self.filemap})

    @defer.inlineCallbacks
    def test_handleStatus_OK_relative_filepath(self):

        self._createTestFile(
            'manifest.json',
            '[{"Config": "../config_file_1.json", '
            '"Layers": ["layer_1/layer.tar", "layer_2/layer.tar"]}]',
            'manifest_hash')

        self.filemap['../config_file_1.json'] = 'config_1_hash'
        # A filemap that tries to write to files outside of
        # the upload directory will not be collected.
        with ExpectedException(
                BuildDaemonError,
                "Build returned a file named '../config_file_1.json'."):
            with dbuser(config.builddmaster.dbuser):
                yield self.behaviour.handleStatus(
                    self.build.buildqueue_record, 'OK',
                    {'filemap': self.filemap})

    @defer.inlineCallbacks
    def test_handleStatus_OK_sets_build_log(self):
        # The build log is set during handleStatus.
        self.assertEqual(None, self.build.log)
        with dbuser(config.builddmaster.dbuser):
            yield self.behaviour.handleStatus(
                self.build.buildqueue_record, 'OK',
                {'filemap': self.filemap})
        self.assertNotEqual(None, self.build.log)

    @defer.inlineCallbacks
    def test_handleStatus_ABORTED_cancels_cancelling(self):
        with dbuser(config.builddmaster.dbuser):
            self.build.updateStatus(BuildStatus.CANCELLING)
            yield self.behaviour.handleStatus(
                self.build.buildqueue_record, "ABORTED", {})
        self.assertEqual(0, len(pop_notifications()), "Notifications received")
        self.assertEqual(BuildStatus.CANCELLED, self.build.status)

    @defer.inlineCallbacks
    def test_handleStatus_ABORTED_illegal_when_building(self):
        self.builder.vm_host = "fake_vm_host"
        self.behaviour = self.interactor.getBuildBehaviour(
            self.build.buildqueue_record, self.builder, self.slave)
        with dbuser(config.builddmaster.dbuser):
            self.build.updateStatus(BuildStatus.BUILDING)
            with ExpectedException(
                    BuildDaemonError,
                    "Build returned unexpected status: u'ABORTED'"):
                yield self.behaviour.handleStatus(
                    self.build.buildqueue_record, "ABORTED", {})

    @defer.inlineCallbacks
    def test_handleStatus_ABORTED_cancelling_sets_build_log(self):
        # If a build is intentionally cancelled, the build log is set.
        self.assertEqual(None, self.build.log)
        with dbuser(config.builddmaster.dbuser):
            self.build.updateStatus(BuildStatus.CANCELLING)
            yield self.behaviour.handleStatus(
                self.build.buildqueue_record, "ABORTED", {})
        self.assertNotEqual(None, self.build.log)

    @defer.inlineCallbacks
    def test_date_finished_set(self):
        # The date finished is updated during handleStatus_OK.
        self.assertEqual(None, self.build.date_finished)
        with dbuser(config.builddmaster.dbuser):
            yield self.behaviour.handleStatus(
                self.build.buildqueue_record, 'OK',
                {'filemap': self.filemap})
        self.assertNotEqual(None, self.build.date_finished)

    @defer.inlineCallbacks
    def test_givenback_collection(self):
        with ExpectedException(
                BuildDaemonError,
                "Build returned unexpected status: u'GIVENBACK'"):
            with dbuser(config.builddmaster.dbuser):
                yield self.behaviour.handleStatus(
                    self.build.buildqueue_record, "GIVENBACK", {})

    @defer.inlineCallbacks
    def test_builderfail_collection(self):
        with ExpectedException(
                BuildDaemonError,
                "Build returned unexpected status: u'BUILDERFAIL'"):
            with dbuser(config.builddmaster.dbuser):
                yield self.behaviour.handleStatus(
                    self.build.buildqueue_record, "BUILDERFAIL", {})

    @defer.inlineCallbacks
    def test_invalid_status_collection(self):
        with ExpectedException(
                BuildDaemonError,
                "Build returned unexpected status: u'BORKED'"):
            with dbuser(config.builddmaster.dbuser):
                yield self.behaviour.handleStatus(
                    self.build.buildqueue_record, "BORKED", {})


class TestGetUploadMethodsForOCIRecipeBuild(
    MakeOCIBuildMixin, TestGetUploadMethodsMixin, TrialTestCase):
    """IPackageBuild.getUpload-related methods work with OCI recipe builds."""

    def setUp(self):
        super(TestGetUploadMethodsForOCIRecipeBuild, self).__init__(self)
        self.factory = LaunchpadObjectFactory()
