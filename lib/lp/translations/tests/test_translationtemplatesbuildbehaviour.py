# Copyright 2010-2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Unit tests for TranslationTemplatesBuildBehaviour."""

import logging
import os
from datetime import datetime, timezone

from testtools.twistedsupport import AsynchronousDeferredRunTest
from twisted.internet import defer
from zope.component import getUtility

from lp.app.interfaces.launchpad import ILaunchpadCelebrities
from lp.buildmaster.enums import BuildStatus
from lp.buildmaster.interfaces.buildfarmjobbehaviour import (
    IBuildFarmJobBehaviour,
)
from lp.buildmaster.tests.mock_workers import WaitingWorker, WorkerTestHelpers
from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.services.config import config
from lp.services.librarian.utils import copy_and_close
from lp.services.webapp import canonical_url
from lp.testing import TestCaseWithFactory
from lp.testing.dbuser import switch_dbuser
from lp.testing.fakemethod import FakeMethod
from lp.testing.layers import LaunchpadZopelessLayer
from lp.translations.enums import RosettaImportStatus
from lp.translations.interfaces.translationimportqueue import (
    ITranslationImportQueue,
)
from lp.translations.interfaces.translations import (
    TranslationsBranchImportMode,
)


class FakeBuildQueue:
    """Pretend `BuildQueue`."""

    def __init__(self, behaviour):
        """Pretend to be a BuildQueue item for the given build behaviour.

        Copies its builder from the behaviour object.
        """
        self.builder = behaviour._builder
        self.specific_build = behaviour.build
        self.date_started = datetime.now(timezone.utc)
        self.destroySelf = FakeMethod()


class MakeBehaviourMixin:
    """Provide common test methods."""

    def makeBehaviour(self, branch=None, use_fake_chroot=True, **kwargs):
        """Create a TranslationTemplatesBuildBehaviour.

        Anything that might communicate with build workers and such
        (which we can't really do here) is mocked up.
        """
        build = self.factory.makeTranslationTemplatesBuild(branch=branch)
        behaviour = IBuildFarmJobBehaviour(build)
        worker = WaitingWorker(**kwargs)
        behaviour.setBuilder(self.factory.makeBuilder(), worker)
        if use_fake_chroot:
            behaviour.distro_arch_series.addOrUpdateChroot(
                self.factory.makeLibraryFileAlias(db_only=True)
            )
        return behaviour

    def makeProductSeriesWithBranchForTranslation(self):
        productseries = self.factory.makeProductSeries()
        branch = self.factory.makeProductBranch(productseries.product)
        productseries.branch = branch
        productseries.translations_autoimport_mode = (
            TranslationsBranchImportMode.IMPORT_TEMPLATES
        )
        return productseries


class TestTranslationTemplatesBuildBehaviour(
    TestCaseWithFactory, MakeBehaviourMixin
):
    """Test `TranslationTemplatesBuildBehaviour`."""

    layer = LaunchpadZopelessLayer
    run_tests_with = AsynchronousDeferredRunTest

    def setUp(self):
        super().setUp()
        self.worker_helper = self.useFixture(WorkerTestHelpers())

    def test_getLogFileName(self):
        # Each job has a unique log file name.
        b1 = self.makeBehaviour()
        b2 = self.makeBehaviour()
        self.assertNotEqual(b1.getLogFileName(), b2.getLogFileName())

    @defer.inlineCallbacks
    def test_composeBuildRequest(self):
        behaviour = self.makeBehaviour()
        switch_dbuser(config.builddmaster.dbuser)
        build_request = yield behaviour.composeBuildRequest(None)
        das = behaviour.distro_arch_series
        self.assertEqual(
            (
                "translation-templates",
                das,
                PackagePublishingPocket.RELEASE,
                {},
                {
                    "arch_tag": das.architecturetag,
                    "archive_private": False,
                    "branch_url": behaviour.build.branch.composePublicURL(),
                    "build_url": canonical_url(behaviour.build),
                    "builder_constraints": [],
                    "fast_cleanup": True,
                    "series": das.distroseries.name,
                },
            ),
            build_request,
        )

    def test_archive(self):
        # TranslationTemplatesBuildBehaviour.archive is the main Ubuntu
        # archive.
        ubuntu = getUtility(ILaunchpadCelebrities).ubuntu
        behaviour = self.makeBehaviour()
        self.assertEqual(ubuntu.main_archive, behaviour.archive)

    def test_distro_arch_series(self):
        # TranslationTemplatesBuildBehaviour.distro_arch_series is the
        # nominated arch-indep architecture for the current Ubuntu series.
        ubuntu = getUtility(ILaunchpadCelebrities).ubuntu
        behaviour = self.makeBehaviour()
        self.assertEqual(
            ubuntu.currentseries.nominatedarchindep,
            behaviour.distro_arch_series,
        )

    def test_readTarball(self):
        behaviour = self.makeBehaviour()
        buildqueue = FakeBuildQueue(behaviour)
        path = behaviour.templates_tarball_path
        # Poke the file we're expecting into the mock worker.
        behaviour._worker.valid_files[path] = ""

        def got_tarball(filename):
            tarball = open(filename)
            try:
                self.assertEqual("This is a %s" % path, tarball.read())
            finally:
                tarball.close()
                os.remove(filename)

        d = behaviour._readTarball(buildqueue, {path: path}, logging)
        return d.addCallback(got_tarball)

    def test_handleStatus_OK(self):
        # Hopefully, a build will succeed and produce a tarball.
        behaviour = self.makeBehaviour(
            filemap={"translation-templates.tar.gz": "foo"}
        )
        behaviour._uploadTarball = FakeMethod()
        queue_item = behaviour.build.queueBuild()
        queue_item.markAsBuilding(self.factory.makeBuilder())
        worker = behaviour._worker

        d = worker.status()

        def got_status(status):
            return behaviour.handleStatus(queue_item, status), worker.call_log

        def build_updated(ignored):
            self.assertEqual(BuildStatus.FULLYBUILT, behaviour.build.status)
            # Log file is stored.
            self.assertIsNotNone(behaviour.build.log)
            self.assertIs(None, behaviour.build.buildqueue_record)
            self.assertEqual(1, behaviour._uploadTarball.call_count)

        d.addCallback(got_status)
        d.addCallback(build_updated)
        return d

    def test_handleStatus_failed(self):
        # Builds may also fail (and produce no tarball).
        behaviour = self.makeBehaviour(state="BuildStatus.PACKAGEFAIL")
        behaviour._uploadTarball = FakeMethod()
        queue_item = behaviour.build.queueBuild()
        queue_item.markAsBuilding(self.factory.makeBuilder())
        worker = behaviour._worker

        d = worker.status()

        def got_status(status):
            del status["filemap"]
            return (behaviour.handleStatus(queue_item, status),)

        def build_updated(ignored):
            self.assertEqual(BuildStatus.FAILEDTOBUILD, behaviour.build.status)
            # Log file is stored.
            self.assertIsNotNone(behaviour.build.log)
            self.assertIs(None, behaviour.build.buildqueue_record)
            self.assertEqual(0, behaviour._uploadTarball.call_count)

        d.addCallback(got_status)
        d.addCallback(build_updated)
        return d

    def test_handleStatus_notarball(self):
        # Even if the build status is "OK," absence of a tarball will
        # not faze the Behaviour class.
        behaviour = self.makeBehaviour()
        behaviour._uploadTarball = FakeMethod()
        queue_item = behaviour.build.queueBuild()
        queue_item.markAsBuilding(self.factory.makeBuilder())
        worker = behaviour._worker

        d = worker.status()

        def got_status(status):
            del status["filemap"]
            return (behaviour.handleStatus(queue_item, status),)

        def build_updated(ignored):
            self.assertEqual(BuildStatus.FULLYBUILT, behaviour.build.status)
            self.assertIs(None, behaviour.build.buildqueue_record)
            self.assertEqual(0, behaviour._uploadTarball.call_count)

        d.addCallback(got_status)
        d.addCallback(build_updated)
        return d

    def test_handleStatus_uploads(self):
        productseries = self.makeProductSeriesWithBranchForTranslation()
        branch = productseries.branch
        behaviour = self.makeBehaviour(
            branch=branch, filemap={"translation-templates.tar.gz": "foo"}
        )
        queue_item = behaviour.build.queueBuild()
        queue_item.markAsBuilding(self.factory.makeBuilder())
        worker = behaviour._worker

        def fake_getFile(sum, path):
            dummy_tar = os.path.join(
                os.path.dirname(__file__), "dummy_templates.tar.gz"
            )
            tar_file = open(dummy_tar, "rb")
            with open(path, "wb") as f:
                copy_and_close(tar_file, f)
            return defer.succeed(None)

        worker.getFile = fake_getFile
        d = worker.status()

        def got_status(status):
            return (behaviour.handleStatus(queue_item, status),)

        def build_updated(ignored):
            self.assertEqual(BuildStatus.FULLYBUILT, behaviour.build.status)
            entries = getUtility(ITranslationImportQueue).getAllEntries(
                target=productseries
            )
            expected_templates = [
                "po/domain.pot",
                "po-other/other.pot",
                "po-thethird/templ3.pot",
            ]
            list1 = sorted(expected_templates)
            list2 = sorted(entry.path for entry in entries)
            self.assertEqual(list1, list2)

        d.addCallback(got_status)
        d.addCallback(build_updated)
        return d


class TestTTBuildBehaviourTranslationsQueue(
    TestCaseWithFactory, MakeBehaviourMixin
):
    """Test uploads to the import queue."""

    layer = LaunchpadZopelessLayer

    def setUp(self):
        super().setUp()

        self.queue = getUtility(ITranslationImportQueue)
        self.dummy_tar = os.path.join(
            os.path.dirname(__file__), "dummy_templates.tar.gz"
        )
        self.productseries = self.makeProductSeriesWithBranchForTranslation()
        self.branch = self.productseries.branch

    def test_uploadTarball(self):
        # Files from the tarball end up in the import queue.
        behaviour = self.makeBehaviour()
        with open(self.dummy_tar, "rb") as f:
            behaviour._uploadTarball(self.branch, f.read(), None)

        entries = self.queue.getAllEntries(target=self.productseries)
        expected_templates = [
            "po/domain.pot",
            "po-other/other.pot",
            "po-thethird/templ3.pot",
        ]

        paths = [entry.path for entry in entries]
        self.assertContentEqual(expected_templates, paths)

    def test_uploadTarball_approved(self):
        # Uploaded template files are automatically approved.
        behaviour = self.makeBehaviour()
        with open(self.dummy_tar, "rb") as f:
            behaviour._uploadTarball(self.branch, f.read(), None)

        entries = self.queue.getAllEntries(target=self.productseries)
        statuses = [entry.status for entry in entries]
        self.assertEqual([RosettaImportStatus.APPROVED] * 3, statuses)

    def test_uploadTarball_importer(self):
        # Files from the tarball are owned by the branch owner.
        behaviour = self.makeBehaviour()
        with open(self.dummy_tar, "rb") as f:
            behaviour._uploadTarball(self.branch, f.read(), None)

        entries = self.queue.getAllEntries(target=self.productseries)
        self.assertEqual(self.branch.owner, entries[0].importer)
