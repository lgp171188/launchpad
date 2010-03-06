# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Buildd cronscript classes """

__metaclass__ = type

__all__ = [
    'QueueBuilder',
    'RetryDepwait',
    'SlaveScanner',
    ]

from zope.component import getUtility

from canonical.config import config
from lp.archivepublisher.debversion import Version
from lp.archivepublisher.utils import process_in_batches
from lp.buildmaster.master import BuilddMaster
from lp.soyuz.interfaces.build import BuildStatus, IBuildSet
from lp.soyuz.interfaces.buildqueue import IBuildQueueSet
from lp.buildmaster.interfaces.builder import IBuilderSet
from lp.buildmaster.pas import BuildDaemonPackagesArchSpecific
from canonical.launchpad.interfaces.launchpad import NotFoundError
from lp.services.scripts.base import (
    LaunchpadCronScript, LaunchpadScriptFailure)
from lp.registry.interfaces.distribution import IDistributionSet
from lp.registry.interfaces.series import SeriesStatus

# XXX cprov 2009-04-16: This function should live in
# lp.registry.interfaces.distroseries. It cannot be done right now
# because we haven't decided if archivepublisher.debversion will be
# released as FOSS yet.
def distroseries_sort_key(series):
    """Sort `DistroSeries` by version.

    See `lp.archivepublisher.debversion.Version` for more
    information.
    """
    return Version(series.version)


class QueueBuilder(LaunchpadCronScript):

    def add_my_options(self):
        self.parser.add_option(
            "-n", "--dry-run", action="store_true",
            dest="dryrun", metavar="DRY_RUN", default=False,
            help="Whether to treat this as a dry-run or not.")

        self.parser.add_option(
            "--score-only", action="store_true",
            dest="score_only", default=False,
            help="Skip build creation, only score existing builds.")

        self.parser.add_option(
            "-d", "--distribution", default="ubuntu",
            help="Context distribution.")

        self.parser.add_option(
            '-s', '--suite', metavar='SUITE', dest='suite',
            action='append', type='string', default=[],
            help='The suite to process')

    def main(self):
        """Use BuildMaster for processing the build queue.

        Callers my define a specific set of distroseries to be processed
        and also decide whether or not the queue-rebuild (expensive
        procedure) should be executed.

        Deals with the current transaction according to the dry-run option.
        """
        if self.args:
            raise LaunchpadScriptFailure("Unhandled arguments %r" % self.args)

        # In order to avoid the partial commits inside BuilddMaster
        # to happen we pass a FakeZtm instance if dry-run mode is selected.
        class _FakeZTM:
            """A fake transaction manager."""
            def commit(self):
                pass

        if self.options.dryrun:
            self.logger.info("Dry run: changes will not be committed.")
            self.txn = _FakeZTM()

        sorted_distroseries = self.calculateDistroseries()
        buildMaster = BuilddMaster(self.logger, self.txn)
        archserieses = []
        # Initialize BuilddMaster with the relevant architectures.
        # it's needed even for 'score-only' mode.
        for series in sorted_distroseries:
            for archseries in series.architectures:
                if archseries.getChroot():
                    archserieses.append(archseries)
                buildMaster.addDistroArchSeries(archseries)

        if not self.options.score_only:
            # For each distroseries we care about, scan for
            # sourcepackagereleases with no build associated
            # with the distroarchseries we're interested in.
            self.logger.info("Rebuilding build queue.")
            for distroseries in sorted_distroseries:
                self.createMissingBuilds(distroseries)

        # Ensure all NEEDSBUILD builds have a buildqueue entry
        # and re-score them.
        buildMaster.addMissingBuildQueueEntries()
        self.scoreCandidates(archserieses)

        self.txn.commit()

    def createMissingBuilds(self, distroseries):
        """Ensure that each published package is completly built."""
        self.logger.info("Processing %s" % distroseries.name)
        # Do not create builds for distroseries with no nominatedarchindep
        # they can't build architecture independent packages properly.
        if not distroseries.nominatedarchindep:
            self.logger.debug(
                "No nominatedarchindep for %s, skipping" % distroseries.name)
            return

        # Listify the architectures to avoid hitting this MultipleJoin
        # multiple times.
        distroseries_architectures = list(distroseries.architectures)
        if not distroseries_architectures:
            self.logger.debug(
                "No architectures defined for %s, skipping"
                % distroseries.name)
            return

        architectures_available = list(distroseries.enabled_architectures)
        if not architectures_available:
            self.logger.debug(
                "Chroots missing for %s, skipping" % distroseries.name)
            return

        self.logger.info(
            "Supported architectures: %s" %
            " ".join(arch_series.architecturetag
                     for arch_series in architectures_available))

        pas_verify = BuildDaemonPackagesArchSpecific(
            config.builddmaster.root, distroseries)

        sources_published = distroseries.getSourcesPublishedForAllArchives()
        self.logger.info(
            "Found %d source(s) published." % sources_published.count())

        def process_source(pubrec):
            builds = pubrec.createMissingBuilds(
                architectures_available=architectures_available,
                pas_verify=pas_verify, logger=self.logger)
            if len(builds) > 0:
                self.txn.commit()

        process_in_batches(
            sources_published, process_source, self.logger,
            minimum_chunk_size=1000)

    def scoreCandidates(self, archseries):
        """Iterate over the pending buildqueue entries and re-score them."""
        if not archseries:
            self.logger.info("No architecture found to rescore.")
            return

        # Get the current build job candidates.
        bqset = getUtility(IBuildQueueSet)
        candidates = bqset.calculateCandidates(archseries)

        self.logger.info("Found %d build in NEEDSBUILD state. Rescoring"
                         % candidates.count())

        for job in candidates:
            uptodate_build = getUtility(IBuildSet).getByQueueEntry(job)
            if uptodate_build.buildstate != BuildStatus.NEEDSBUILD:
                continue
            job.score()

    def calculateDistroseries(self):
        """Return an ordered list of distroseries for the given arguments."""
        distribution = getUtility(IDistributionSet).getByName(
            self.options.distribution)
        if distribution is None:
            raise LaunchpadScriptFailure(
                "Could not find distribution: %s" % self.options.distribution)

        if len(self.options.suite) == 0:
            return sorted(distribution.series, key=distroseries_sort_key)

        distroseries_set = set()
        for suite in self.options.suite:
            try:
                distroseries, pocket = distribution.getDistroSeriesAndPocket(
                    suite)
            except NotFoundError, err:
                raise LaunchpadScriptFailure("Could not find suite %s" % err)
            distroseries_set.add(distroseries)

        return sorted(distroseries_set, key=distroseries_sort_key)


class RetryDepwait(LaunchpadCronScript):

    def add_my_options(self):
        self.parser.add_option(
            "-d", "--distribution", default="ubuntu",
            help="Context distribution.")

        self.parser.add_option(
            "-n", "--dry-run",
            dest="dryrun", action="store_true", default=False,
            help="Whether or not to commit the transaction.")

    def main(self):
        """Retry all builds that do not fit in MANUALDEPWAIT.

        Iterate over all supported series in the given distribution and
        their architectures with existent chroots and update all builds
        found in MANUALDEPWAIT status.
        """
        if self.args:
            raise LaunchpadScriptFailure("Unhandled arguments %r" % self.args)

        distribution_set = getUtility(IDistributionSet)
        try:
            distribution = distribution_set[self.options.distribution]
        except NotFoundError:
            raise LaunchpadScriptFailure(
                "Could not find distribution: %s" % self.options.distribution)

        # Iterate over all supported distroarchseries with available chroot.
        build_set = getUtility(IBuildSet)
        for distroseries in distribution:
            if distroseries.status == SeriesStatus.OBSOLETE:
                self.logger.debug(
                    "Skipping obsolete distroseries: %s" % distroseries.title)
                continue
            for distroarchseries in distroseries.architectures:
                self.logger.info("Processing %s" % distroarchseries.title)
                if not distroarchseries.getChroot:
                    self.logger.debug("Chroot not found")
                    continue
                build_set.retryDepWaiting(distroarchseries)

        # XXX cprov 20071122:  LaunchpadScript should provide some
        # infrastructure for dry-run operations and not simply rely
        # on the transaction being discarded by the garbage-collector.
        # See further information in bug #165200.
        if not self.options.dryrun:
            self.logger.info('Commiting the transaction.')
            self.txn.commit()


class SlaveScanner(LaunchpadCronScript):

    def main(self):
        if self.args:
            raise LaunchpadScriptFailure(
                "Unhandled arguments %s" % repr(self.args))

        builder_set = getUtility(IBuilderSet)
        buildMaster = builder_set.pollBuilders(self.logger, self.txn)

        self.logger.info("Dispatching Jobs.")

        for builder in builder_set:
            self.logger.info("Processing: %s" % builder.name)
            # XXX cprov 2007-11-09: we don't support manual dispatching
            # yet. Once we support it this clause should be removed.
            if builder.manual:
                self.logger.warn('builder is in manual state. Ignored.')
                continue
            if not builder.is_available:
                self.logger.warn('builder is not available. Ignored.')
                continue

            candidate = builder.findAndStartJob()
            if candidate is None:
                continue
            self.txn.commit()

        self.logger.info("Slave Scan Process Finished.")
