# Copyright 2011-2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import transaction
from zope.component import getUtility

from lp.buildmaster.enums import BuildStatus
from lp.registry.interfaces.person import IPersonSet
from lp.soyuz.enums import ArchivePurpose, PackagePublishingStatus
from lp.soyuz.interfaces.component import IComponentSet
from lp.soyuz.tests.test_publishing import SoyuzTestPublisher
from lp.testing import TestCaseWithFactory, person_logged_in
from lp.testing.layers import LaunchpadFunctionalLayer
from lp.testing.sampledata import ADMIN_EMAIL


class TestBuildDepWait(TestCaseWithFactory):
    layer = LaunchpadFunctionalLayer

    def setUp(self):
        super().setUp()
        self.admin = getUtility(IPersonSet).getByEmail(ADMIN_EMAIL)
        # Create everything we need to create builds, such as a
        # DistroArchSeries and a builder.
        self.processor = self.factory.makeProcessor(supports_virtualized=True)
        self.distroseries = self.factory.makeDistroSeries()
        self.das = self.factory.makeDistroArchSeries(
            distroseries=self.distroseries, processor=self.processor
        )
        self.archive = self.factory.makeArchive(
            distribution=self.distroseries.distribution,
            purpose=ArchivePurpose.PRIMARY,
        )
        with person_logged_in(self.admin):
            self.publisher = SoyuzTestPublisher()
            self.publisher.prepareBreezyAutotest()
            self.distroseries.nominatedarchindep = self.das
            self.publisher.addFakeChroots(distroseries=self.distroseries)
            self.builder = self.factory.makeBuilder(
                processors=[self.processor]
            )

    def test_update_dependancies(self):
        # Calling .updateDependencies() on a build will remove those which
        # are reachable.
        spph = self.publisher.getPubSource(
            sourcename=self.factory.getUniqueString(),
            version="%s.1" % self.factory.getUniqueInteger(),
            distroseries=self.distroseries,
            archive=self.archive,
        )
        [build] = spph.createMissingBuilds()
        spn = self.factory.getUniqueUnicode()
        version = "%s.1" % self.factory.getUniqueInteger()
        with person_logged_in(self.admin):
            build.updateStatus(
                BuildStatus.MANUALDEPWAIT, worker_status={"dependencies": spn}
            )
            [bpph] = self.publisher.getPubBinaries(
                binaryname=spn,
                distroseries=self.distroseries,
                version=version,
                builder=self.builder,
                archive=self.archive,
                status=PackagePublishingStatus.PUBLISHED,
            )
            # Commit to make sure stuff hits the database.
            transaction.commit()
        build.updateDependencies()
        self.assertEqual("", build.dependencies)

    def test_update_dependancies_respects_component(self):
        # Since main can only utilise packages that are published in main,
        # dependencies are not satisfied if they are not in main.
        spph = self.publisher.getPubSource(
            sourcename=self.factory.getUniqueString(),
            version="%s.1" % self.factory.getUniqueInteger(),
            distroseries=self.distroseries,
            archive=self.archive,
        )
        [build] = spph.createMissingBuilds()
        spn = self.factory.getUniqueUnicode()
        version = "%s.1" % self.factory.getUniqueInteger()
        with person_logged_in(self.admin):
            build.updateStatus(
                BuildStatus.MANUALDEPWAIT, worker_status={"dependencies": spn}
            )
            [bpph] = self.publisher.getPubBinaries(
                binaryname=spn,
                distroseries=self.distroseries,
                version=version,
                builder=self.builder,
                archive=self.archive,
                status=PackagePublishingStatus.PUBLISHED,
                component="universe",
            )
            # Commit to make sure stuff hits the database.
            transaction.commit()
        build.updateDependencies()
        # Since the dependency is in universe, we still can't see it.
        self.assertEqual(spn, build.dependencies)
        with person_logged_in(self.admin):
            bpph.component = getUtility(IComponentSet)["main"]
            transaction.commit()
        # Now that we have moved it main, we can see it.
        build.updateDependencies()
        self.assertEqual("", build.dependencies)
