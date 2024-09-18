# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for rock recipe jobs."""

from textwrap import dedent

import six
from testtools.matchers import (
    AfterPreprocessing,
    ContainsDict,
    Equals,
    GreaterThan,
    Is,
    LessThan,
    MatchesAll,
    MatchesSetwise,
    MatchesStructure,
)
from zope.component import getUtility

from lp.app.interfaces.launchpad import ILaunchpadCelebrities
from lp.code.tests.helpers import GitHostingFixture
from lp.rocks.interfaces.rockrecipe import (
    ROCK_RECIPE_ALLOW_CREATE,
    CannotParseRockcraftYaml,
)
from lp.rocks.interfaces.rockrecipejob import (
    IRockRecipeJob,
    IRockRecipeRequestBuildsJob,
)
from lp.rocks.model.rockrecipejob import (
    RockRecipeJob,
    RockRecipeJobType,
    RockRecipeRequestBuildsJob,
)
from lp.services.config import config
from lp.services.database.interfaces import IStore
from lp.services.database.sqlbase import get_transaction_timestamp
from lp.services.features.testing import FeatureFixture
from lp.services.job.interfaces.job import JobStatus
from lp.services.job.runner import JobRunner
from lp.services.mail.sendmail import format_address_for_person
from lp.testing import TestCaseWithFactory
from lp.testing.dbuser import dbuser
from lp.testing.layers import ZopelessDatabaseLayer


class TestRockRecipeJob(TestCaseWithFactory):

    layer = ZopelessDatabaseLayer

    def setUp(self):
        super().setUp()
        self.useFixture(FeatureFixture({ROCK_RECIPE_ALLOW_CREATE: "on"}))

    def test_provides_interface(self):
        # `RockRecipeJob` objects provide `IRockRecipeJob`.
        recipe = self.factory.makeRockRecipe()
        self.assertProvides(
            RockRecipeJob(recipe, RockRecipeJobType.REQUEST_BUILDS, {}),
            IRockRecipeJob,
        )


class TestRockRecipeRequestBuildsJob(TestCaseWithFactory):

    layer = ZopelessDatabaseLayer

    def setUp(self):
        super().setUp()
        self.useFixture(FeatureFixture({ROCK_RECIPE_ALLOW_CREATE: "on"}))

    def test_provides_interface(self):
        # `RockRecipeRequestBuildsJob` objects provide
        # `IRockRecipeRequestBuildsJob`."""
        recipe = self.factory.makeRockRecipe()
        job = RockRecipeRequestBuildsJob.create(recipe, recipe.registrant)
        self.assertProvides(job, IRockRecipeRequestBuildsJob)

    def test___repr__(self):
        # `RockRecipeRequestBuildsJob` objects have an informative __repr__.
        recipe = self.factory.makeRockRecipe()
        job = RockRecipeRequestBuildsJob.create(recipe, recipe.registrant)
        self.assertEqual(
            "<RockRecipeRequestBuildsJob for ~%s/%s/+rock/%s>"
            % (recipe.owner.name, recipe.project.name, recipe.name),
            repr(job),
        )

    def makeSeriesAndProcessors(self, distro_series_version, arch_tags):
        distroseries = self.factory.makeDistroSeries(
            distribution=getUtility(ILaunchpadCelebrities).ubuntu,
            version=distro_series_version,
        )
        processors = [
            self.factory.makeProcessor(
                name=arch_tag, supports_virtualized=True
            )
            for arch_tag in arch_tags
        ]
        for processor in processors:
            das = self.factory.makeDistroArchSeries(
                distroseries=distroseries,
                architecturetag=processor.name,
                processor=processor,
            )
            das.addOrUpdateChroot(
                self.factory.makeLibraryFileAlias(
                    filename="fake_chroot.tar.gz", db_only=True
                )
            )
        return distroseries, processors

    def test_run(self):
        # The job requests builds and records the result.
        distroseries, _ = self.makeSeriesAndProcessors(
            "20.04", ["avr2001", "sparc64", "x32"]
        )
        [git_ref] = self.factory.makeGitRefs()
        recipe = self.factory.makeRockRecipe(git_ref=git_ref)
        expected_date_created = get_transaction_timestamp(IStore(recipe))
        job = RockRecipeRequestBuildsJob.create(
            recipe, recipe.registrant, channels={"core": "stable"}
        )
        rockcraft_yaml = dedent(
            """\
            bases:
              - build-on:
                  - name: ubuntu
                    channel: "20.04"
                    architectures: [avr2001]
              - build-on:
                  - name: ubuntu
                    channel: "20.04"
                    architectures: [x32]
            """
        )
        self.useFixture(GitHostingFixture(blob=rockcraft_yaml))
        with dbuser(config.IRockRecipeRequestBuildsJobSource.dbuser):
            JobRunner([job]).runAll()
        now = get_transaction_timestamp(IStore(recipe))
        self.assertEmailQueueLength(0)
        self.assertThat(
            job,
            MatchesStructure(
                job=MatchesStructure.byEquality(status=JobStatus.COMPLETED),
                date_created=Equals(expected_date_created),
                date_finished=MatchesAll(
                    GreaterThan(expected_date_created), LessThan(now)
                ),
                error_message=Is(None),
                builds=AfterPreprocessing(
                    set,
                    MatchesSetwise(
                        *[
                            MatchesStructure(
                                build_request=MatchesStructure.byEquality(
                                    id=job.job.id
                                ),
                                requester=Equals(recipe.registrant),
                                recipe=Equals(recipe),
                                distro_arch_series=Equals(distroseries[arch]),
                                channels=Equals({"core": "stable"}),
                            )
                            for arch in ("avr2001", "x32")
                        ]
                    ),
                ),
            ),
        )

    def test_run_with_architectures(self):
        # If the user explicitly requested architectures, the job passes
        # those through when requesting builds, intersecting them with other
        # constraints.
        distroseries, _ = self.makeSeriesAndProcessors(
            "20.04", ["avr2001", "sparc64", "x32"]
        )
        [git_ref] = self.factory.makeGitRefs()
        recipe = self.factory.makeRockRecipe(git_ref=git_ref)
        expected_date_created = get_transaction_timestamp(IStore(recipe))
        job = RockRecipeRequestBuildsJob.create(
            recipe,
            recipe.registrant,
            channels={"core": "stable"},
            architectures=["sparc64", "x32"],
        )
        rockcraft_yaml = dedent(
            """\
            bases:
              - build-on:
                  - name: ubuntu
                    channel: "20.04"
                    architectures: [avr2001]
              - build-on:
                  - name: ubuntu
                    channel: "20.04"
                    architectures: [x32]
            """
        )
        self.useFixture(GitHostingFixture(blob=rockcraft_yaml))
        with dbuser(config.IRockRecipeRequestBuildsJobSource.dbuser):
            JobRunner([job]).runAll()
        now = get_transaction_timestamp(IStore(recipe))
        self.assertEmailQueueLength(0)
        self.assertThat(
            job,
            MatchesStructure(
                job=MatchesStructure.byEquality(status=JobStatus.COMPLETED),
                date_created=Equals(expected_date_created),
                date_finished=MatchesAll(
                    GreaterThan(expected_date_created), LessThan(now)
                ),
                error_message=Is(None),
                builds=AfterPreprocessing(
                    set,
                    MatchesSetwise(
                        MatchesStructure(
                            build_request=MatchesStructure.byEquality(
                                id=job.job.id
                            ),
                            requester=Equals(recipe.registrant),
                            recipe=Equals(recipe),
                            distro_arch_series=Equals(distroseries["x32"]),
                            channels=Equals({"core": "stable"}),
                        )
                    ),
                ),
            ),
        )

    def test_run_failed(self):
        # A failed run sets the job status to FAILED and records the error
        # message.
        [git_ref] = self.factory.makeGitRefs()
        recipe = self.factory.makeRockRecipe(git_ref=git_ref)
        expected_date_created = get_transaction_timestamp(IStore(recipe))
        job = RockRecipeRequestBuildsJob.create(
            recipe, recipe.registrant, channels={"core": "stable"}
        )
        self.useFixture(GitHostingFixture()).getBlob.failure = (
            CannotParseRockcraftYaml("Nonsense on stilts")
        )
        with dbuser(config.IRockRecipeRequestBuildsJobSource.dbuser):
            JobRunner([job]).runAll()
        now = get_transaction_timestamp(IStore(recipe))
        [notification] = self.assertEmailQueueLength(1)
        self.assertThat(
            dict(notification),
            ContainsDict(
                {
                    "From": Equals(config.canonical.noreply_from_address),
                    "To": Equals(format_address_for_person(recipe.registrant)),
                    "Subject": Equals(
                        "Launchpad error while requesting builds of %s"
                        % recipe.name
                    ),
                }
            ),
        )
        self.assertEqual(
            "Launchpad encountered an error during the following operation: "
            "requesting builds of %s.  Nonsense on stilts" % recipe.name,
            six.ensure_text(notification.get_payload(decode=True)),
        )
        self.assertThat(
            job,
            MatchesStructure(
                job=MatchesStructure.byEquality(status=JobStatus.FAILED),
                date_created=Equals(expected_date_created),
                date_finished=MatchesAll(
                    GreaterThan(expected_date_created), LessThan(now)
                ),
                error_message=Equals("Nonsense on stilts"),
                builds=AfterPreprocessing(set, MatchesSetwise()),
            ),
        )
