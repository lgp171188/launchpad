# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test rock recipes."""
import json
from datetime import timedelta
from textwrap import dedent

import iso8601
import transaction
from storm.locals import Store
from testtools.matchers import (
    AfterPreprocessing,
    ContainsDict,
    Equals,
    GreaterThan,
    Is,
    LessThan,
    MatchesAll,
    MatchesDict,
    MatchesSetwise,
    MatchesStructure,
)
from testtools.testcase import ExpectedException
from zope.component import getUtility
from zope.security.interfaces import Unauthorized
from zope.security.proxy import removeSecurityProxy

from lp.app.enums import InformationType
from lp.app.interfaces.launchpad import ILaunchpadCelebrities
from lp.buildmaster.enums import (
    BuildBaseImageType,
    BuildQueueStatus,
    BuildStatus,
)
from lp.buildmaster.interfaces.buildqueue import IBuildQueue
from lp.buildmaster.interfaces.processor import (
    IProcessorSet,
    ProcessorNotFound,
)
from lp.buildmaster.model.buildfarmjob import BuildFarmJob
from lp.buildmaster.model.buildqueue import BuildQueue
from lp.code.tests.helpers import GitHostingFixture
from lp.registry.enums import PersonVisibility, TeamMembershipPolicy
from lp.rocks.adapters.buildarch import BadPropertyError, MissingPropertyError
from lp.rocks.interfaces.rockrecipe import (
    ROCK_RECIPE_ALLOW_CREATE,
    ROCK_RECIPE_PRIVATE_FEATURE_FLAG,
    BadRockRecipeSearchContext,
    IRockRecipe,
    IRockRecipeSet,
    IRockRecipeView,
    NoSourceForRockRecipe,
    RockRecipeBuildAlreadyPending,
    RockRecipeBuildDisallowedArchitecture,
    RockRecipeBuildRequestStatus,
    RockRecipeFeatureDisabled,
    RockRecipePrivateFeatureDisabled,
)
from lp.rocks.interfaces.rockrecipebuild import (
    IRockRecipeBuild,
    IRockRecipeBuildSet,
)
from lp.rocks.interfaces.rockrecipejob import IRockRecipeRequestBuildsJobSource
from lp.rocks.model.rockrecipebuild import RockFile
from lp.rocks.model.rockrecipejob import RockRecipeJob
from lp.services.config import config
from lp.services.database.constants import ONE_DAY_AGO, UTC_NOW
from lp.services.database.interfaces import IStore
from lp.services.database.sqlbase import (
    flush_database_caches,
    get_transaction_timestamp,
)
from lp.services.features.testing import FeatureFixture
from lp.services.job.interfaces.job import JobStatus
from lp.services.job.runner import JobRunner
from lp.services.webapp.interfaces import OAuthPermission
from lp.services.webapp.snapshot import notify_modified
from lp.testing import (
    ANONYMOUS,
    StormStatementRecorder,
    TestCaseWithFactory,
    admin_logged_in,
    api_url,
    login,
    logout,
    person_logged_in,
)
from lp.testing.dbuser import dbuser
from lp.testing.layers import (
    DatabaseFunctionalLayer,
    LaunchpadFunctionalLayer,
    LaunchpadZopelessLayer,
)
from lp.testing.matchers import DoesNotSnapshot, HasQueryCount
from lp.testing.pages import webservice_for_person


class TestRockRecipeFeatureFlags(TestCaseWithFactory):

    layer = LaunchpadZopelessLayer

    def test_feature_flag_disabled(self):
        # Without a feature flag, we wil not create any rock recipes.
        self.assertRaises(
            RockRecipeFeatureDisabled, self.factory.makeRockRecipe
        )

    def test_private_feature_flag_disabled(self):
        # Without a private feature flag, we will not create new private
        # rock recipes.
        self.useFixture(FeatureFixture({ROCK_RECIPE_ALLOW_CREATE: "on"}))
        self.assertRaises(
            RockRecipePrivateFeatureDisabled,
            self.factory.makeRockRecipe,
            information_type=InformationType.PROPRIETARY,
        )


class TestRockRecipe(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.useFixture(FeatureFixture({ROCK_RECIPE_ALLOW_CREATE: "on"}))

    def test_implements_interfaces(self):
        # RockRecipe implements IRockRecipe.
        recipe = self.factory.makeRockRecipe()
        with admin_logged_in():
            self.assertProvides(recipe, IRockRecipe)

    def test___repr__(self):
        # RockRecipe objects have an informative __repr__.
        recipe = self.factory.makeRockRecipe()
        self.assertEqual(
            "<RockRecipe ~%s/%s/+rock/%s>"
            % (recipe.owner.name, recipe.project.name, recipe.name),
            repr(recipe),
        )

    def test_avoids_problematic_snapshots(self):
        self.assertThat(
            self.factory.makeRockRecipe(),
            DoesNotSnapshot(
                [
                    "pending_build_requests",
                    "failed_build_requests",
                    "builds",
                    "completed_builds",
                    "pending_builds",
                ],
                IRockRecipeView,
            ),
        )

    def test_initial_date_last_modified(self):
        # The initial value of date_last_modified is date_created.
        recipe = self.factory.makeRockRecipe(date_created=ONE_DAY_AGO)
        self.assertEqual(recipe.date_created, recipe.date_last_modified)

    def test_modifiedevent_sets_date_last_modified(self):
        # When a RockRecipe receives an object modified event, the last
        # modified date is set to UTC_NOW.
        recipe = self.factory.makeRockRecipe(date_created=ONE_DAY_AGO)
        with notify_modified(removeSecurityProxy(recipe), ["name"]):
            pass
        self.assertSqlAttributeEqualsDate(
            recipe, "date_last_modified", UTC_NOW
        )

    def test_requestBuilds(self):
        # requestBuilds schedules a job and returns a corresponding
        # RockRecipeBuildRequest.
        recipe = self.factory.makeRockRecipe()
        now = get_transaction_timestamp(IStore(recipe))
        with person_logged_in(recipe.owner.teamowner):
            request = recipe.requestBuilds(recipe.owner.teamowner)
        self.assertThat(
            request,
            MatchesStructure(
                date_requested=Equals(now),
                date_finished=Is(None),
                recipe=Equals(recipe),
                status=Equals(RockRecipeBuildRequestStatus.PENDING),
                error_message=Is(None),
                channels=Is(None),
                architectures=Is(None),
            ),
        )
        [job] = getUtility(IRockRecipeRequestBuildsJobSource).iterReady()
        self.assertThat(
            job,
            MatchesStructure(
                job_id=Equals(request.id),
                job=MatchesStructure.byEquality(status=JobStatus.WAITING),
                recipe=Equals(recipe),
                requester=Equals(recipe.owner.teamowner),
                channels=Is(None),
                architectures=Is(None),
            ),
        )

    def test_requestBuilds_with_channels(self):
        # If asked to build using particular snap channels, requestBuilds
        # passes those through to the job.
        recipe = self.factory.makeRockRecipe()
        now = get_transaction_timestamp(IStore(recipe))
        with person_logged_in(recipe.owner.teamowner):
            request = recipe.requestBuilds(
                recipe.owner.teamowner, channels={"rockcraft": "edge"}
            )
        self.assertThat(
            request,
            MatchesStructure(
                date_requested=Equals(now),
                date_finished=Is(None),
                recipe=Equals(recipe),
                status=Equals(RockRecipeBuildRequestStatus.PENDING),
                error_message=Is(None),
                channels=MatchesDict({"rockcraft": Equals("edge")}),
                architectures=Is(None),
            ),
        )
        [job] = getUtility(IRockRecipeRequestBuildsJobSource).iterReady()
        self.assertThat(
            job,
            MatchesStructure(
                job_id=Equals(request.id),
                job=MatchesStructure.byEquality(status=JobStatus.WAITING),
                recipe=Equals(recipe),
                requester=Equals(recipe.owner.teamowner),
                channels=Equals({"rockcraft": "edge"}),
                architectures=Is(None),
            ),
        )

    def test_requestBuilds_with_architectures(self):
        # If asked to build for particular architectures, requestBuilds
        # passes those through to the job.
        recipe = self.factory.makeRockRecipe()
        now = get_transaction_timestamp(IStore(recipe))
        with person_logged_in(recipe.owner.teamowner):
            request = recipe.requestBuilds(
                recipe.owner.teamowner, architectures={"amd64", "i386"}
            )
        self.assertThat(
            request,
            MatchesStructure(
                date_requested=Equals(now),
                date_finished=Is(None),
                recipe=Equals(recipe),
                status=Equals(RockRecipeBuildRequestStatus.PENDING),
                error_message=Is(None),
                channels=Is(None),
                architectures=MatchesSetwise(Equals("amd64"), Equals("i386")),
            ),
        )
        [job] = getUtility(IRockRecipeRequestBuildsJobSource).iterReady()
        self.assertThat(
            job,
            MatchesStructure(
                job_id=Equals(request.id),
                job=MatchesStructure.byEquality(status=JobStatus.WAITING),
                recipe=Equals(recipe),
                requester=Equals(recipe.owner.teamowner),
                channels=Is(None),
                architectures=MatchesSetwise(Equals("amd64"), Equals("i386")),
            ),
        )

    def makeRequestBuildsJob(
        self, distro_series_version, arch_tags, git_ref=None
    ):
        recipe = self.factory.makeRockRecipe(git_ref=git_ref)
        distro_series = self.factory.makeDistroSeries(
            distribution=getUtility(ILaunchpadCelebrities).ubuntu,
            version=distro_series_version,
        )
        for arch_tag in arch_tags:
            self.makeBuildableDistroArchSeries(
                distroseries=distro_series, architecturetag=arch_tag
            )
        return getUtility(IRockRecipeRequestBuildsJobSource).create(
            recipe, recipe.owner.teamowner, {"rockcraft": "edge"}
        )

    def assertRequestedBuildsMatch(
        self, builds, job, distro_series_version, arch_tags, channels
    ):
        self.assertThat(
            builds,
            MatchesSetwise(
                *(
                    MatchesStructure(
                        requester=Equals(job.requester),
                        recipe=Equals(job.recipe),
                        distro_arch_series=MatchesStructure(
                            distroseries=MatchesStructure.byEquality(
                                version=distro_series_version
                            ),
                            architecturetag=Equals(arch_tag),
                        ),
                        channels=Equals(channels),
                    )
                    for arch_tag in arch_tags
                )
            ),
        )

    def test_requestBuildsFromJob_rock_base_architectures(self):
        # requestBuildsFromJob intersects the architectures supported by the
        # rock base with any other constraints.
        self.useFixture(
            GitHostingFixture(
                blob=dedent(
                    """\
            name: foo
            base: ubuntu@20.04
            platforms:
                sparc:
                avr:
            """
                )
            )
        )
        job = self.makeRequestBuildsJob("20.04", ["sparc", "i386", "avr"])
        distroseries = getUtility(ILaunchpadCelebrities).ubuntu.getSeries(
            "20.04"
        )
        with admin_logged_in():
            self.factory.makeRockBase(
                distro_series=distroseries,
                build_channels={"rockcraft": "stable/launchpad-buildd"},
                processors=[
                    distroseries[arch_tag].processor
                    for arch_tag in ("sparc", "avr")
                ],
            )
        transaction.commit()
        with person_logged_in(job.requester):
            builds = job.recipe.requestBuildsFromJob(
                job.build_request, channels=removeSecurityProxy(job.channels)
            )
        self.assertRequestedBuildsMatch(
            builds, job, "20.04", ["sparc", "avr"], job.channels
        )

    def test_requestBuildsFromJob_rock_base_build_channels_by_arch(self):
        # If the rock base declares different build channels for specific
        # architectures, then requestBuildsFromJob uses those when
        # requesting builds for those architectures.
        self.useFixture(
            GitHostingFixture(
                blob=dedent(
                    """\
            name: foo
            base: ubuntu@20.04
            platforms:
                avr:
            """
                )
            )
        )
        job = self.makeRequestBuildsJob("20.04", ["avr"])
        distroseries = getUtility(ILaunchpadCelebrities).ubuntu.getSeries(
            "20.04"
        )
        with admin_logged_in():
            self.factory.makeRockBase(
                distro_series=distroseries,
                build_channels={
                    "core20": "stable",
                    "_byarch": {"riscv64": {"core20": "candidate"}},
                },
            )
        transaction.commit()
        with person_logged_in(job.requester):
            builds = job.recipe.requestBuildsFromJob(
                job.build_request, channels=removeSecurityProxy(job.channels)
            )
        self.assertThat(
            builds,
            MatchesSetwise(
                *(
                    MatchesStructure(
                        requester=Equals(job.requester),
                        recipe=Equals(job.recipe),
                        distro_arch_series=MatchesStructure(
                            distroseries=MatchesStructure.byEquality(
                                version="20.04"
                            ),
                            architecturetag=Equals(arch_tag),
                        ),
                        channels=Equals(channels),
                    )
                    for arch_tag, channels in (
                        ("avr", {"rockcraft": "edge", "core20": "stable"}),
                    )
                )
            ),
        )

    def test_requestBuildsFromJob_restricts_explicit_list(self):
        # requestBuildsFromJob limits builds targeted at an explicit list of
        # architectures to those allowed for the recipe.
        self.useFixture(
            GitHostingFixture(
                blob=dedent(
                    """\
            base: ubuntu@20.04
            platforms:
                avr:
            """
                )
            )
        )
        job = self.makeRequestBuildsJob("20.04", ["sparc", "avr", "mips64el"])
        self.assertEqual(
            get_transaction_timestamp(IStore(job.recipe)), job.date_created
        )
        transaction.commit()
        with person_logged_in(job.requester):
            builds = job.recipe.requestBuildsFromJob(
                job.build_request, channels=removeSecurityProxy(job.channels)
            )
        self.assertRequestedBuildsMatch(
            builds, job, "20.04", ["avr"], job.channels
        )

    def test_requestBuildsFromJob_unified_rockcraft_yaml_invalid_short_base(
        self,
    ):
        self.useFixture(
            GitHostingFixture(
                blob=dedent(
                    """\
                    base: ubuntu-24.04
                    platforms:
                        ubuntu-amd64:
                            build-on: [amd64]
                            build-for: [amd64]
                    """
                )
            )
        )
        job = self.makeRequestBuildsJob("24.04", ["amd64", "riscv64", "arm64"])

        self.assertEqual(
            get_transaction_timestamp(IStore(job.recipe)), job.date_created
        )
        transaction.commit()
        with person_logged_in(job.requester):
            with ExpectedException(
                BadPropertyError,
                "Invalid value for base 'ubuntu-24.04'. "
                "Expected value should be like 'ubuntu@24.04'",
            ):
                job.recipe.requestBuildsFromJob(
                    job.build_request,
                    channels=removeSecurityProxy(job.channels),
                )

    def test_requestBuildsFromJob_unified_rockcraft_yaml_base_bare(self):
        self.useFixture(
            GitHostingFixture(
                blob=dedent(
                    """\
                    base: bare
                    build-base: ubuntu@20.04
                    platforms:
                        ubuntu-amd64:
                            build-on: [amd64]
                            build-for: [amd64]
            """
                )
            )
        )
        job = self.makeRequestBuildsJob("20.04", ["amd64", "riscv64", "arm64"])
        self.assertEqual(
            get_transaction_timestamp(IStore(job.recipe)), job.date_created
        )
        transaction.commit()
        with person_logged_in(job.requester):
            builds = job.recipe.requestBuildsFromJob(
                job.build_request, channels=removeSecurityProxy(job.channels)
            )
        self.assertRequestedBuildsMatch(
            builds, job, "20.04", ["amd64"], job.channels
        )

    def test_requestBuildsFromJob_unified_rockcraft_yaml_missing_build_base(
        self,
    ):
        self.useFixture(
            GitHostingFixture(
                blob=dedent(
                    """\
                    base: bare
                    platforms:
                        ubuntu-amd64:
                            build-on: [amd64]
                            build-for: [amd64]
                    """
                )
            )
        )
        job = self.makeRequestBuildsJob("24.04", ["amd64", "riscv64", "arm64"])

        self.assertEqual(
            get_transaction_timestamp(IStore(job.recipe)), job.date_created
        )
        transaction.commit()
        with person_logged_in(job.requester):
            with ExpectedException(
                BadPropertyError,
                "If base is 'bare', then build-base must be specified.",
            ):
                job.recipe.requestBuildsFromJob(
                    job.build_request,
                    channels=removeSecurityProxy(job.channels),
                )

    def test_requestBuildsFromJob_unified_rockcraft_yaml_platforms_missing(
        self,
    ):
        self.useFixture(
            GitHostingFixture(
                blob=dedent(
                    """\
                    base: ubuntu@24.04
                    """
                )
            )
        )
        job = self.makeRequestBuildsJob("24.04", ["amd64", "riscv64", "arm64"])

        self.assertEqual(
            get_transaction_timestamp(IStore(job.recipe)), job.date_created
        )
        transaction.commit()
        with person_logged_in(job.requester):
            with ExpectedException(
                MissingPropertyError, "The 'platforms' property is required"
            ):
                job.recipe.requestBuildsFromJob(
                    job.build_request,
                    channels=removeSecurityProxy(job.channels),
                )

    def test_requestBuildsFromJob_unified_rockcraft_yaml_fully_expanded(self):
        self.useFixture(
            GitHostingFixture(
                blob=dedent(
                    """\
                    base:
                        name: ubuntu
                        channel: 24.04
                    platforms:
                        ubuntu-amd64:
                            build-on: [amd64]
                            build-for: [amd64]
                    """
                )
            )
        )
        job = self.makeRequestBuildsJob("24.04", ["amd64", "riscv64", "arm64"])
        self.assertEqual(
            get_transaction_timestamp(IStore(job.recipe)), job.date_created
        )
        transaction.commit()
        with person_logged_in(job.requester):
            builds = job.recipe.requestBuildsFromJob(
                job.build_request, channels=removeSecurityProxy(job.channels)
            )
        self.assertRequestedBuildsMatch(
            builds, job, "24.04", ["amd64"], job.channels
        )

    def test_requestBuildsFromJob_unified_rockcraft_yaml_multi_platforms(
        self,
    ):
        self.useFixture(
            GitHostingFixture(
                blob=dedent(
                    """\
                    base:
                        name: ubuntu
                        channel: 24.04
                    platforms:
                        ubuntu-amd64:
                            build-on: [amd64]
                            build-for: [amd64]
                        ubuntu-arm64:
                            build-on: [arm64]
                            build-for: [arm64]
                    """
                )
            )
        )
        job = self.makeRequestBuildsJob("24.04", ["amd64", "riscv64", "arm64"])
        self.assertEqual(
            get_transaction_timestamp(IStore(job.recipe)), job.date_created
        )
        transaction.commit()
        with person_logged_in(job.requester):
            builds = job.recipe.requestBuildsFromJob(
                job.build_request, channels=removeSecurityProxy(job.channels)
            )
        self.assertRequestedBuildsMatch(
            builds, job, "24.04", ["amd64", "arm64"], job.channels
        )

    def test_requestBuildsFromJob_unified_rockcraft_yaml_arch_as_str(self):
        self.useFixture(
            GitHostingFixture(
                blob=dedent(
                    """\
                    base:
                        name: ubuntu
                        channel: 24.04
                    platforms:
                        ubuntu-amd64:
                            build-on: amd64
                            build-for: amd64
                    """
                )
            )
        )
        job = self.makeRequestBuildsJob("24.04", ["amd64", "riscv64", "arm64"])
        self.assertEqual(
            get_transaction_timestamp(IStore(job.recipe)), job.date_created
        )
        transaction.commit()
        with person_logged_in(job.requester):
            builds = job.recipe.requestBuildsFromJob(
                job.build_request, channels=removeSecurityProxy(job.channels)
            )
        self.assertRequestedBuildsMatch(
            builds, job, "24.04", ["amd64"], job.channels
        )

    def test_requestBuildsFromJob_unified_rockcraft_yaml_base_short_form(
        self,
    ):
        self.useFixture(
            GitHostingFixture(
                blob=dedent(
                    """\
                    base: ubuntu@24.04
                    platforms:
                        ubuntu-amd64:
                            build-on: [amd64]
                            build-for: [amd64]
                    """
                )
            )
        )
        job = self.makeRequestBuildsJob("24.04", ["amd64", "riscv64", "arm64"])
        self.assertEqual(
            get_transaction_timestamp(IStore(job.recipe)), job.date_created
        )
        transaction.commit()
        with person_logged_in(job.requester):
            builds = job.recipe.requestBuildsFromJob(
                job.build_request, channels=removeSecurityProxy(job.channels)
            )
        self.assertRequestedBuildsMatch(
            builds, job, "24.04", ["amd64"], job.channels
        )

    def test_requestBuildsFromJob_unified_rockcraft_yaml_unknown_arch(self):
        self.useFixture(
            GitHostingFixture(
                blob=dedent(
                    """\
                    base:
                        name: ubuntu
                        channel: 24.04
                    platforms:
                        foobar:
                    """
                )
            )
        )
        job = self.makeRequestBuildsJob("24.04", ["amd64", "riscv64", "arm64"])
        self.assertEqual(
            get_transaction_timestamp(IStore(job.recipe)), job.date_created
        )
        transaction.commit()
        with person_logged_in(job.requester):
            with ExpectedException(
                BadPropertyError,
                "'foobar' is not a supported architecture for "
                "'ubuntu@24.04'",
            ):
                job.recipe.requestBuildsFromJob(
                    job.build_request,
                    channels=removeSecurityProxy(job.channels),
                )

    def test_requestBuildsFromJob_unified_rockcraft_yaml_platforms_short_form(
        self,
    ):
        self.useFixture(
            GitHostingFixture(
                blob=dedent(
                    """\
                    base:
                        name: ubuntu
                        channel: 24.04
                    platforms:
                        amd64:
                    """
                )
            )
        )
        job = self.makeRequestBuildsJob("24.04", ["amd64", "riscv64", "arm64"])
        self.assertEqual(
            get_transaction_timestamp(IStore(job.recipe)), job.date_created
        )
        transaction.commit()
        with person_logged_in(job.requester):
            builds = job.recipe.requestBuildsFromJob(
                job.build_request, channels=removeSecurityProxy(job.channels)
            )
        self.assertRequestedBuildsMatch(
            builds, job, "24.04", ["amd64"], job.channels
        )

    def test_requestBuildsFromJob_unified_rockcraft_yaml_2_platforms_short(
        self,
    ):
        self.useFixture(
            GitHostingFixture(
                blob=dedent(
                    """\
                    base:
                        name: ubuntu
                        channel: 24.04
                    platforms:
                        amd64:
                        arm64:
                    """
                )
            )
        )
        job = self.makeRequestBuildsJob("24.04", ["amd64", "riscv64", "arm64"])
        self.assertEqual(
            get_transaction_timestamp(IStore(job.recipe)), job.date_created
        )
        transaction.commit()
        with person_logged_in(job.requester):
            builds = job.recipe.requestBuildsFromJob(
                job.build_request, channels=removeSecurityProxy(job.channels)
            )
        self.assertRequestedBuildsMatch(
            builds, job, "24.04", ["amd64", "arm64"], job.channels
        )

    def test_requestBuildsFromJob_architectures_parameter(self):
        # If an explicit set of architectures was given as a parameter,
        # requestBuildsFromJob intersects those with any other constraints
        # when requesting builds.
        self.useFixture(
            GitHostingFixture(
                blob=dedent(
                    """\
            base: ubuntu@20.04
            platforms:
                avr:
                riscv64:
            """
                )
            )
        )
        job = self.makeRequestBuildsJob(
            "20.04", ["avr", "mips64el", "riscv64"]
        )
        self.assertEqual(
            get_transaction_timestamp(IStore(job.recipe)), job.date_created
        )
        transaction.commit()
        with person_logged_in(job.requester):
            builds = job.recipe.requestBuildsFromJob(
                job.build_request,
                channels=removeSecurityProxy(job.channels),
                architectures={"avr", "riscv64"},
            )
        self.assertRequestedBuildsMatch(
            builds, job, "20.04", ["avr", "riscv64"], job.channels
        )

    def test_delete_without_builds(self):
        # A rock recipe with no builds can be deleted.
        owner = self.factory.makePerson()
        project = self.factory.makeProduct()
        recipe = self.factory.makeRockRecipe(
            registrant=owner, owner=owner, project=project, name="condemned"
        )
        self.assertTrue(
            getUtility(IRockRecipeSet).exists(owner, project, "condemned")
        )
        with person_logged_in(recipe.owner):
            recipe.destroySelf()
        self.assertFalse(
            getUtility(IRockRecipeSet).exists(owner, project, "condemned")
        )

    def makeBuildableDistroArchSeries(
        self,
        architecturetag=None,
        processor=None,
        supports_virtualized=True,
        supports_nonvirtualized=True,
        **kwargs,
    ):
        if architecturetag is None:
            architecturetag = self.factory.getUniqueUnicode("arch")
        if processor is None:
            try:
                processor = getUtility(IProcessorSet).getByName(
                    architecturetag
                )
            except ProcessorNotFound:
                processor = self.factory.makeProcessor(
                    name=architecturetag,
                    supports_virtualized=supports_virtualized,
                    supports_nonvirtualized=supports_nonvirtualized,
                )
        das = self.factory.makeDistroArchSeries(
            architecturetag=architecturetag, processor=processor, **kwargs
        )
        fake_chroot = self.factory.makeLibraryFileAlias(
            filename="fake_chroot.tar.gz", db_only=True
        )
        das.addOrUpdateChroot(fake_chroot)
        return das

    def test_requestBuild(self):
        # requestBuild creates a new RockRecipeBuild.
        recipe = self.factory.makeRockRecipe()
        das = self.makeBuildableDistroArchSeries()
        build_request = self.factory.makeRockRecipeBuildRequest(recipe=recipe)
        build = recipe.requestBuild(build_request, das)
        self.assertTrue(IRockRecipeBuild.providedBy(build))
        self.assertThat(
            build,
            MatchesStructure(
                requester=Equals(recipe.owner.teamowner),
                distro_arch_series=Equals(das),
                channels=Is(None),
                status=Equals(BuildStatus.NEEDSBUILD),
            ),
        )
        store = Store.of(build)
        store.flush()
        build_queue = store.find(
            BuildQueue,
            BuildQueue._build_farm_job_id
            == removeSecurityProxy(build).build_farm_job_id,
        ).one()
        self.assertProvides(build_queue, IBuildQueue)
        self.assertEqual(recipe.require_virtualized, build_queue.virtualized)
        self.assertEqual(BuildQueueStatus.WAITING, build_queue.status)

    def test_requestBuild_score(self):
        # Build requests have a relatively low queue score (2510).
        recipe = self.factory.makeRockRecipe()
        das = self.makeBuildableDistroArchSeries()
        build_request = self.factory.makeRockRecipeBuildRequest(recipe=recipe)
        build = recipe.requestBuild(build_request, das)
        queue_record = build.buildqueue_record
        queue_record.score()
        self.assertEqual(2510, queue_record.lastscore)

    def test_requestBuild_channels(self):
        # requestBuild can select non-default channels.
        recipe = self.factory.makeRockRecipe()
        das = self.makeBuildableDistroArchSeries()
        build_request = self.factory.makeRockRecipeBuildRequest(recipe=recipe)
        build = recipe.requestBuild(
            build_request, das, channels={"rockcraft": "edge"}
        )
        self.assertEqual({"rockcraft": "edge"}, build.channels)

    def test_requestBuild_rejects_repeats(self):
        # requestBuild refuses if there is already a pending build.
        recipe = self.factory.makeRockRecipe()
        distro_series = self.factory.makeDistroSeries()
        arches = [
            self.makeBuildableDistroArchSeries(distroseries=distro_series)
            for _ in range(2)
        ]
        build_request = self.factory.makeRockRecipeBuildRequest(recipe=recipe)
        old_build = recipe.requestBuild(build_request, arches[0])
        self.assertRaises(
            RockRecipeBuildAlreadyPending,
            recipe.requestBuild,
            build_request,
            arches[0],
        )
        # We can build for a different distroarchseries.
        recipe.requestBuild(build_request, arches[1])
        # channels=None and channels={} are treated as equivalent, but
        # anything else allows a new build.
        self.assertRaises(
            RockRecipeBuildAlreadyPending,
            recipe.requestBuild,
            build_request,
            arches[0],
            channels={},
        )
        recipe.requestBuild(
            build_request, arches[0], channels={"core": "edge"}
        )
        self.assertRaises(
            RockRecipeBuildAlreadyPending,
            recipe.requestBuild,
            build_request,
            arches[0],
            channels={"core": "edge"},
        )
        # Changing the status of the old build allows a new build.
        old_build.updateStatus(BuildStatus.BUILDING)
        old_build.updateStatus(BuildStatus.FULLYBUILT)
        recipe.requestBuild(build_request, arches[0])

    def test_requestBuild_virtualization(self):
        # New builds are virtualized if any of the processor or recipe
        # require it.
        recipe = self.factory.makeRockRecipe()
        distro_series = self.factory.makeDistroSeries()
        dases = {}
        for proc_nonvirt in True, False:
            das = self.makeBuildableDistroArchSeries(
                distroseries=distro_series,
                supports_virtualized=True,
                supports_nonvirtualized=proc_nonvirt,
            )
            dases[proc_nonvirt] = das
        for proc_nonvirt, recipe_virt, build_virt in (
            (True, False, False),
            (True, True, True),
            (False, False, True),
            (False, True, True),
        ):
            das = dases[proc_nonvirt]
            recipe = self.factory.makeRockRecipe(
                require_virtualized=recipe_virt
            )
            build_request = self.factory.makeRockRecipeBuildRequest(
                recipe=recipe
            )
            build = recipe.requestBuild(build_request, das)
            self.assertEqual(build_virt, build.virtualized)

    def test_requestBuild_fetch_service(self):
        # Activate fetch service for a rock recipe.
        recipe = self.factory.makeRockRecipe(use_fetch_service=True)
        self.assertEqual(True, recipe.use_fetch_service)
        distro_series = self.factory.makeDistroSeries()
        das = self.makeBuildableDistroArchSeries(
            distroseries=distro_series,
        )
        build_request = self.factory.makeRockRecipeBuildRequest(recipe=recipe)
        build = recipe.requestBuild(build_request, das)
        self.assertEqual(True, build.recipe.use_fetch_service)

    def test_requestBuild_nonvirtualized(self):
        # A non-virtualized processor can build a rock recipe iff the
        # recipe has require_virtualized set to False.
        recipe = self.factory.makeRockRecipe()
        distro_series = self.factory.makeDistroSeries()
        das = self.makeBuildableDistroArchSeries(
            distroseries=distro_series,
            supports_virtualized=False,
            supports_nonvirtualized=True,
        )
        build_request = self.factory.makeRockRecipeBuildRequest(recipe=recipe)
        self.assertRaises(
            RockRecipeBuildDisallowedArchitecture,
            recipe.requestBuild,
            build_request,
            das,
        )
        with admin_logged_in():
            recipe.require_virtualized = False
        recipe.requestBuild(build_request, das)


class TestRockRecipeDeleteWithBuilds(TestCaseWithFactory):

    layer = LaunchpadFunctionalLayer

    def setUp(self):
        super().setUp()
        self.useFixture(FeatureFixture({ROCK_RECIPE_ALLOW_CREATE: "on"}))

    def test_delete_with_builds(self):
        # A rock recipe with build requests and builds can be deleted.
        # Doing so deletes all its build requests, their builds, and their
        # files.
        owner = self.factory.makePerson()
        project = self.factory.makeProduct()
        distroseries = self.factory.makeDistroSeries()
        processor = self.factory.makeProcessor(supports_virtualized=True)
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
        rockcraft_yaml = (
            dedent(
                """\
            base: %s@%s
            platforms:
                %s:
            """
            )
            % (
                distroseries.distribution.name,
                distroseries.version,
                processor.name,
            )
        )
        self.useFixture(GitHostingFixture(blob=rockcraft_yaml))
        [git_ref] = self.factory.makeGitRefs()
        condemned_recipe = self.factory.makeRockRecipe(
            registrant=owner,
            owner=owner,
            project=project,
            name="condemned",
            git_ref=git_ref,
        )
        other_recipe = self.factory.makeRockRecipe(
            registrant=owner, owner=owner, project=project, git_ref=git_ref
        )
        self.assertTrue(
            getUtility(IRockRecipeSet).exists(owner, project, "condemned")
        )
        with person_logged_in(owner):
            requests = []
            jobs = []
            for recipe in (condemned_recipe, other_recipe):
                requests.append(recipe.requestBuilds(owner))
                jobs.append(removeSecurityProxy(requests[-1])._job)
            with dbuser(config.IRockRecipeRequestBuildsJobSource.dbuser):
                JobRunner(jobs).runAll()
            for job in jobs:
                self.assertEqual(JobStatus.COMPLETED, job.job.status)
            [build] = requests[0].builds
            [other_build] = requests[1].builds
            rock_file = self.factory.makeRockFile(build=build)
            other_rock_file = self.factory.makeRockFile(build=other_build)
        store = Store.of(condemned_recipe)
        store.flush()
        job_ids = [job.job_id for job in jobs]
        build_id = build.id
        build_queue_id = build.buildqueue_record.id
        build_farm_job_id = removeSecurityProxy(build).build_farm_job_id
        rock_file_id = removeSecurityProxy(rock_file).id
        with person_logged_in(condemned_recipe.owner):
            condemned_recipe.destroySelf()
        flush_database_caches()
        # The deleted recipe, its build requests, and its are gone.
        self.assertFalse(
            getUtility(IRockRecipeSet).exists(owner, project, "condemned")
        )
        self.assertIsNone(store.get(RockRecipeJob, job_ids[0]))
        self.assertIsNone(getUtility(IRockRecipeBuildSet).getByID(build_id))
        self.assertIsNone(store.get(BuildQueue, build_queue_id))
        self.assertIsNone(store.get(BuildFarmJob, build_farm_job_id))
        self.assertIsNone(store.get(RockFile, rock_file_id))
        # Unrelated build requests, build jobs and builds are still present.
        self.assertEqual(
            removeSecurityProxy(jobs[1]).context,
            store.get(RockRecipeJob, job_ids[1]),
        )
        self.assertEqual(
            other_build,
            getUtility(IRockRecipeBuildSet).getByID(other_build.id),
        )
        self.assertIsNotNone(other_build.buildqueue_record)
        self.assertIsNotNone(
            store.get(RockFile, removeSecurityProxy(other_rock_file).id)
        )


class TestRockRecipeSet(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.useFixture(FeatureFixture({ROCK_RECIPE_ALLOW_CREATE: "on"}))

    def test_class_implements_interfaces(self):
        # The RockRecipeSet class implements IRockRecipeSet.
        self.assertProvides(getUtility(IRockRecipeSet), IRockRecipeSet)

    def makeRockRecipeComponents(self, git_ref=None):
        """Return a dict of values that can be used to make a rock recipe.

        Suggested use: provide as kwargs to IRockRecipeSet.new.

        :param git_ref: An `IGitRef`, or None.
        """
        registrant = self.factory.makePerson()
        components = {
            "registrant": registrant,
            "owner": self.factory.makeTeam(owner=registrant),
            "project": self.factory.makeProduct(),
            "name": self.factory.getUniqueUnicode("rock-name"),
        }
        if git_ref is None:
            git_ref = self.factory.makeGitRefs()[0]
        components["git_ref"] = git_ref
        return components

    def test_creation_git(self):
        # The metadata entries supplied when a rock recipe is created for a
        # Git branch are present on the new object.
        [ref] = self.factory.makeGitRefs()
        components = self.makeRockRecipeComponents(git_ref=ref)
        recipe = getUtility(IRockRecipeSet).new(**components)
        self.assertEqual(components["registrant"], recipe.registrant)
        self.assertEqual(components["owner"], recipe.owner)
        self.assertEqual(components["project"], recipe.project)
        self.assertEqual(components["name"], recipe.name)
        self.assertEqual(ref.repository, recipe.git_repository)
        self.assertEqual(ref.path, recipe.git_path)
        self.assertEqual(ref, recipe.git_ref)
        self.assertIsNone(recipe.build_path)
        self.assertFalse(recipe.auto_build)
        self.assertIsNone(recipe.auto_build_channels)
        self.assertTrue(recipe.require_virtualized)
        self.assertFalse(recipe.private)
        self.assertFalse(recipe.store_upload)
        self.assertIsNone(recipe.store_name)
        self.assertIsNone(recipe.store_secrets)
        self.assertEqual([], recipe.store_channels)
        self.assertFalse(recipe.use_fetch_service)

    def test_creation_no_source(self):
        # Attempting to create a rock recipe without a Git repository
        # fails.
        registrant = self.factory.makePerson()
        self.assertRaises(
            NoSourceForRockRecipe,
            getUtility(IRockRecipeSet).new,
            registrant,
            registrant,
            self.factory.makeProduct(),
            self.factory.getUniqueUnicode("rock-name"),
        )

    def test_getByName(self):
        owner = self.factory.makePerson()
        project = self.factory.makeProduct()
        project_recipe = self.factory.makeRockRecipe(
            registrant=owner, owner=owner, project=project, name="proj-rock"
        )
        self.factory.makeRockRecipe(
            registrant=owner, owner=owner, name="proj-rock"
        )

        self.assertEqual(
            project_recipe,
            getUtility(IRockRecipeSet).getByName(owner, project, "proj-rock"),
        )

    def test_findByPerson(self):
        # IRockRecipeSet.findByPerson returns all rock recipes with the
        # given owner or based on repositories with the given owner.
        owners = [self.factory.makePerson() for i in range(2)]
        recipes = []
        for owner in owners:
            recipes.append(
                self.factory.makeRockRecipe(registrant=owner, owner=owner)
            )
            [ref] = self.factory.makeGitRefs(owner=owner)
            recipes.append(self.factory.makeRockRecipe(git_ref=ref))
        recipe_set = getUtility(IRockRecipeSet)
        self.assertContentEqual(
            recipes[:2], recipe_set.findByPerson(owners[0])
        )
        self.assertContentEqual(
            recipes[2:], recipe_set.findByPerson(owners[1])
        )

    def test_findByProject(self):
        # IRockRecipeSet.findByProject returns all rock recipes based on
        # repositories for the given project, and rock recipes associated
        # directly with the project.
        projects = [self.factory.makeProduct() for i in range(2)]
        recipes = []
        for project in projects:
            [ref] = self.factory.makeGitRefs(target=project)
            recipes.append(self.factory.makeRockRecipe(git_ref=ref))
            recipes.append(self.factory.makeRockRecipe(project=project))
        [ref] = self.factory.makeGitRefs(target=None)
        recipes.append(self.factory.makeRockRecipe(git_ref=ref))
        recipe_set = getUtility(IRockRecipeSet)
        self.assertContentEqual(
            recipes[:2], recipe_set.findByProject(projects[0])
        )
        self.assertContentEqual(
            recipes[2:4], recipe_set.findByProject(projects[1])
        )

    def test_findByGitRepository(self):
        # IRockRecipeSet.findByGitRepository returns all rock recipes with
        # the given Git repository.
        repositories = [self.factory.makeGitRepository() for i in range(2)]
        recipes = []
        for repository in repositories:
            for _ in range(2):
                [ref] = self.factory.makeGitRefs(repository=repository)
                recipes.append(self.factory.makeRockRecipe(git_ref=ref))
        recipe_set = getUtility(IRockRecipeSet)
        self.assertContentEqual(
            recipes[:2], recipe_set.findByGitRepository(repositories[0])
        )
        self.assertContentEqual(
            recipes[2:], recipe_set.findByGitRepository(repositories[1])
        )

    def test_findByGitRepository_paths(self):
        # IRockRecipeSet.findByGitRepository can restrict by reference
        # paths.
        repositories = [self.factory.makeGitRepository() for i in range(2)]
        recipes = []
        for repository in repositories:
            for _ in range(3):
                [ref] = self.factory.makeGitRefs(repository=repository)
                recipes.append(self.factory.makeRockRecipe(git_ref=ref))
        recipe_set = getUtility(IRockRecipeSet)
        self.assertContentEqual(
            [], recipe_set.findByGitRepository(repositories[0], paths=[])
        )
        self.assertContentEqual(
            [recipes[0]],
            recipe_set.findByGitRepository(
                repositories[0], paths=[recipes[0].git_ref.path]
            ),
        )
        self.assertContentEqual(
            recipes[:2],
            recipe_set.findByGitRepository(
                repositories[0],
                paths=[recipes[0].git_ref.path, recipes[1].git_ref.path],
            ),
        )

    def test_findByOwner(self):
        # IRockRecipeSet.findByOwner returns all rock recipes with the
        # given owner.
        owners = [self.factory.makePerson() for i in range(2)]
        recipes = []
        for owner in owners:
            for _ in range(2):
                recipes.append(
                    self.factory.makeRockRecipe(registrant=owner, owner=owner)
                )
        recipe_set = getUtility(IRockRecipeSet)
        self.assertContentEqual(recipes[:2], recipe_set.findByOwner(owners[0]))
        self.assertContentEqual(recipes[2:], recipe_set.findByOwner(owners[1]))

    def test_findByGitRef(self):
        # IRockRecipeSet.findByGitRef returns all rock recipes with the
        # given Git reference.
        repositories = [self.factory.makeGitRepository() for i in range(2)]
        refs = []
        recipes = []
        for _ in repositories:
            refs.extend(
                self.factory.makeGitRefs(
                    paths=["refs/heads/master", "refs/heads/other"]
                )
            )
            recipes.append(self.factory.makeRockRecipe(git_ref=refs[-2]))
            recipes.append(self.factory.makeRockRecipe(git_ref=refs[-1]))
        recipe_set = getUtility(IRockRecipeSet)
        for ref, recipe in zip(refs, recipes):
            self.assertContentEqual([recipe], recipe_set.findByGitRef(ref))

    def test_findByContext(self):
        # IRockRecipeSet.findByContext returns all rock recipes with the
        # given context.
        person = self.factory.makePerson()
        project = self.factory.makeProduct()
        repository = self.factory.makeGitRepository(
            owner=person, target=project
        )
        refs = self.factory.makeGitRefs(
            repository=repository,
            paths=["refs/heads/master", "refs/heads/other"],
        )
        other_repository = self.factory.makeGitRepository()
        other_refs = self.factory.makeGitRefs(
            repository=other_repository,
            paths=["refs/heads/master", "refs/heads/other"],
        )
        recipes = []
        recipes.append(self.factory.makeRockRecipe(git_ref=refs[0]))
        recipes.append(self.factory.makeRockRecipe(git_ref=refs[1]))
        recipes.append(
            self.factory.makeRockRecipe(
                registrant=person, owner=person, git_ref=other_refs[0]
            )
        )
        recipes.append(
            self.factory.makeRockRecipe(project=project, git_ref=other_refs[1])
        )
        recipe_set = getUtility(IRockRecipeSet)
        self.assertContentEqual(recipes[:3], recipe_set.findByContext(person))
        self.assertContentEqual(
            [recipes[0], recipes[1], recipes[3]],
            recipe_set.findByContext(project),
        )
        self.assertContentEqual(
            recipes[:2], recipe_set.findByContext(repository)
        )
        self.assertContentEqual(
            [recipes[0]], recipe_set.findByContext(refs[0])
        )
        self.assertRaises(
            BadRockRecipeSearchContext,
            recipe_set.findByContext,
            self.factory.makeDistribution(),
        )

    def test_detachFromGitRepository(self):
        # IRockRecipeSet.detachFromGitRepository clears the given Git
        # repository from all rock recipes.
        repositories = [self.factory.makeGitRepository() for i in range(2)]
        recipes = []
        paths = []
        refs = []
        for repository in repositories:
            for _ in range(2):
                [ref] = self.factory.makeGitRefs(repository=repository)
                paths.append(ref.path)
                refs.append(ref)
                recipes.append(
                    self.factory.makeRockRecipe(
                        git_ref=ref, date_created=ONE_DAY_AGO
                    )
                )
        getUtility(IRockRecipeSet).detachFromGitRepository(repositories[0])
        self.assertEqual(
            [None, None, repositories[1], repositories[1]],
            [recipe.git_repository for recipe in recipes],
        )
        self.assertEqual(
            [None, None, paths[2], paths[3]],
            [recipe.git_path for recipe in recipes],
        )
        self.assertEqual(
            [None, None, refs[2], refs[3]],
            [recipe.git_ref for recipe in recipes],
        )
        for recipe in recipes[:2]:
            self.assertSqlAttributeEqualsDate(
                recipe, "date_last_modified", UTC_NOW
            )

    def test_admins_can_update_admin_only_fields(self):
        # The admin fields can be updated by an admin

        [ref] = self.factory.makeGitRefs()
        rock = self.factory.makeRockRecipe(git_ref=ref, use_fetch_service=True)

        admin_fields = [
            "require_virtualized",
            "use_fetch_service",
        ]

        for field_name in admin_fields:
            # exception isn't raised when an admin does the same
            with admin_logged_in():
                setattr(rock, field_name, True)

    def test_non_admins_cannot_update_admin_only_fields(self):
        # The admin fields cannot be updated by a non admin

        [ref] = self.factory.makeGitRefs()
        rock = self.factory.makeRockRecipe(git_ref=ref, use_fetch_service=True)
        person = self.factory.makePerson()
        admin_fields = [
            "require_virtualized",
            "use_fetch_service",
        ]

        for field_name in admin_fields:
            # exception is raised when a non admin updates the fields
            with person_logged_in(person):
                self.assertRaises(
                    Unauthorized,
                    setattr,
                    rock,
                    field_name,
                    True,
                )


class TestRockRecipeWebservice(TestCaseWithFactory):

    layer = LaunchpadFunctionalLayer

    def setUp(self):
        super().setUp()
        self.useFixture(
            FeatureFixture(
                {
                    ROCK_RECIPE_ALLOW_CREATE: "on",
                    ROCK_RECIPE_PRIVATE_FEATURE_FLAG: "on",
                }
            )
        )
        self.person = self.factory.makePerson(displayname="Test Person")
        self.webservice = webservice_for_person(
            self.person, permission=OAuthPermission.WRITE_PUBLIC
        )
        self.webservice.default_api_version = "devel"
        login(ANONYMOUS)

    def getURL(self, obj):
        return self.webservice.getAbsoluteUrl(api_url(obj))

    def makeRockRecipe(
        self,
        owner=None,
        project=None,
        name=None,
        git_ref=None,
        private=False,
        webservice=None,
        **kwargs,
    ):
        if owner is None:
            owner = self.person
        if project is None:
            project = self.factory.makeProduct(owner=owner)
        if name is None:
            name = self.factory.getUniqueUnicode()
        if git_ref is None:
            [git_ref] = self.factory.makeGitRefs()
        if webservice is None:
            webservice = self.webservice
        transaction.commit()
        owner_url = api_url(owner)
        project_url = api_url(project)
        git_ref_url = api_url(git_ref)
        logout()
        information_type = (
            InformationType.PROPRIETARY if private else InformationType.PUBLIC
        )
        response = webservice.named_post(
            "/+rock-recipes",
            "new",
            owner=owner_url,
            project=project_url,
            name=name,
            git_ref=git_ref_url,
            information_type=information_type.title,
            **kwargs,
        )
        self.assertEqual(201, response.status)
        return webservice.get(response.getHeader("Location")).jsonBody()

    def getCollectionLinks(self, entry, member):
        """Return a list of self_link attributes of entries in a collection."""
        collection = self.webservice.get(
            entry["%s_collection_link" % member]
        ).jsonBody()
        return [entry["self_link"] for entry in collection["entries"]]

    def test_new_git(self):
        # Rock recipe creation based on a Git branch works.
        team = self.factory.makeTeam(
            owner=self.person,
            membership_policy=TeamMembershipPolicy.RESTRICTED,
        )
        project = self.factory.makeProduct(owner=team)
        [ref] = self.factory.makeGitRefs()
        recipe = self.makeRockRecipe(
            owner=team, project=project, name="test-rock", git_ref=ref
        )
        with person_logged_in(self.person):
            self.assertThat(
                recipe,
                ContainsDict(
                    {
                        "registrant_link": Equals(self.getURL(self.person)),
                        "owner_link": Equals(self.getURL(team)),
                        "project_link": Equals(self.getURL(project)),
                        "name": Equals("test-rock"),
                        "git_ref_link": Equals(self.getURL(ref)),
                        "build_path": Is(None),
                        "require_virtualized": Is(True),
                    }
                ),
            )

    def test_new_store_options(self):
        # The store-related options in RockRecipe.new work.
        store_name = self.factory.getUniqueUnicode()
        recipe = self.makeRockRecipe(
            store_upload=True, store_name=store_name, store_channels=["edge"]
        )
        with person_logged_in(self.person):
            self.assertThat(
                recipe,
                ContainsDict(
                    {
                        "store_upload": Is(True),
                        "store_name": Equals(store_name),
                        "store_channels": Equals(["edge"]),
                    }
                ),
            )

    def test_duplicate(self):
        # An attempt to create a duplicate rock recipe fails.
        team = self.factory.makeTeam(
            owner=self.person,
            membership_policy=TeamMembershipPolicy.RESTRICTED,
        )
        project = self.factory.makeProduct(owner=team)
        name = self.factory.getUniqueUnicode()
        [git_ref] = self.factory.makeGitRefs()
        owner_url = api_url(team)
        project_url = api_url(project)
        git_ref_url = api_url(git_ref)
        self.makeRockRecipe(
            owner=team, project=project, name=name, git_ref=git_ref
        )
        response = self.webservice.named_post(
            "/+rock-recipes",
            "new",
            owner=owner_url,
            project=project_url,
            name=name,
            git_ref=git_ref_url,
        )
        self.assertThat(
            response,
            MatchesStructure.byEquality(
                status=400,
                body=(
                    b"There is already a rock recipe with the same project, "
                    b"owner, and name."
                ),
            ),
        )

    def test_not_owner(self):
        # If the registrant is not the owner or a member of the owner team,
        # rock recipe creation fails.
        other_person = self.factory.makePerson(displayname="Other Person")
        other_team = self.factory.makeTeam(
            owner=other_person, displayname="Other Team"
        )
        project = self.factory.makeProduct(owner=self.person)
        [git_ref] = self.factory.makeGitRefs()
        transaction.commit()
        other_person_url = api_url(other_person)
        other_team_url = api_url(other_team)
        project_url = api_url(project)
        git_ref_url = api_url(git_ref)
        logout()
        response = self.webservice.named_post(
            "/+rock-recipes",
            "new",
            owner=other_person_url,
            project=project_url,
            name="test-rock",
            git_ref=git_ref_url,
        )
        self.assertThat(
            response,
            MatchesStructure.byEquality(
                status=401,
                body=(
                    b"Test Person cannot create rock recipes owned by "
                    b"Other Person."
                ),
            ),
        )
        response = self.webservice.named_post(
            "/+rock-recipes",
            "new",
            owner=other_team_url,
            project=project_url,
            name="test-rock",
            git_ref=git_ref_url,
        )
        self.assertThat(
            response,
            MatchesStructure.byEquality(
                status=401, body=b"Test Person is not a member of Other Team."
            ),
        )

    def test_cannot_set_private_components_of_public_recipe(self):
        # If a rock recipe is public, then trying to change its owner or
        # git_ref components to be private fails.
        recipe = self.factory.makeRockRecipe(
            registrant=self.person,
            owner=self.person,
            git_ref=self.factory.makeGitRefs()[0],
        )
        private_team = self.factory.makeTeam(
            owner=self.person, visibility=PersonVisibility.PRIVATE
        )
        [private_ref] = self.factory.makeGitRefs(
            owner=self.person, information_type=InformationType.PRIVATESECURITY
        )
        recipe_url = api_url(recipe)
        with person_logged_in(self.person):
            private_team_url = api_url(private_team)
            private_ref_url = api_url(private_ref)
        logout()
        private_webservice = webservice_for_person(
            self.person, permission=OAuthPermission.WRITE_PRIVATE
        )
        private_webservice.default_api_version = "devel"
        response = private_webservice.patch(
            recipe_url,
            "application/json",
            json.dumps({"owner_link": private_team_url}),
        )
        self.assertThat(
            response,
            MatchesStructure.byEquality(
                status=400,
                body=b"A public rock recipe cannot have a private owner.",
            ),
        )
        response = private_webservice.patch(
            recipe_url,
            "application/json",
            json.dumps({"git_ref_link": private_ref_url}),
        )
        self.assertThat(
            response,
            MatchesStructure.byEquality(
                status=400,
                body=b"A public rock recipe cannot have a private repository.",
            ),
        )

    def test_is_stale(self):
        # is_stale is exported and is read-only.
        recipe = self.makeRockRecipe()
        self.assertTrue(recipe["is_stale"])
        response = self.webservice.patch(
            recipe["self_link"],
            "application/json",
            json.dumps({"is_stale": False}),
        )
        self.assertEqual(400, response.status)

    def test_getByName(self):
        # lp.rock_recipes.getByName returns a matching RockRecipe.
        project = self.factory.makeProduct(owner=self.person)
        name = self.factory.getUniqueUnicode()
        recipe = self.makeRockRecipe(project=project, name=name)
        with person_logged_in(self.person):
            owner_url = api_url(self.person)
            project_url = api_url(project)
        response = self.webservice.named_get(
            "/+rock-recipes",
            "getByName",
            owner=owner_url,
            project=project_url,
            name=name,
        )
        self.assertEqual(200, response.status)
        self.assertEqual(recipe, response.jsonBody())

    def test_getByName_missing(self):
        # lp.rock_recipes.getByName returns 404 for a non-existent
        # RockRecipe.
        project = self.factory.makeProduct(owner=self.person)
        logout()
        with person_logged_in(self.person):
            owner_url = api_url(self.person)
            project_url = api_url(project)
        response = self.webservice.named_get(
            "/+rock-recipes",
            "getByName",
            owner=owner_url,
            project=project_url,
            name="nonexistent",
        )
        self.assertThat(
            response,
            MatchesStructure.byEquality(
                status=404,
                body=(
                    b"No such rock recipe with this owner and project: "
                    b"'nonexistent'."
                ),
            ),
        )

    def makeBuildableDistroArchSeries(
        self,
        distroseries=None,
        architecturetag=None,
        processor=None,
        supports_virtualized=True,
        supports_nonvirtualized=True,
        **kwargs,
    ):
        if architecturetag is None:
            architecturetag = self.factory.getUniqueUnicode("arch")
        if processor is None:
            try:
                processor = getUtility(IProcessorSet).getByName(
                    architecturetag
                )
            except ProcessorNotFound:
                processor = self.factory.makeProcessor(
                    name=architecturetag,
                    supports_virtualized=supports_virtualized,
                    supports_nonvirtualized=supports_nonvirtualized,
                )
        das = self.factory.makeDistroArchSeries(
            distroseries=distroseries,
            architecturetag=architecturetag,
            processor=processor,
            **kwargs,
        )
        # Add both a chroot and a LXD image to test that
        # getAllowedArchitectures doesn't get confused by multiple
        # PocketChroot rows for a single DistroArchSeries.
        fake_chroot = self.factory.makeLibraryFileAlias(
            filename="fake_chroot.tar.gz", db_only=True
        )
        das.addOrUpdateChroot(fake_chroot)
        fake_lxd = self.factory.makeLibraryFileAlias(
            filename="fake_lxd.tar.gz", db_only=True
        )
        das.addOrUpdateChroot(fake_lxd, image_type=BuildBaseImageType.LXD)
        return das

    def test_requestBuilds(self):
        # Requests for builds for all relevant architectures can be
        # performed over the webservice, and the returned entry indicates
        # the status of the asynchronous job.
        distroseries = self.factory.makeDistroSeries(
            distribution=getUtility(ILaunchpadCelebrities).ubuntu,
            registrant=self.person,
        )
        processors = [
            self.factory.makeProcessor(supports_virtualized=True)
            for _ in range(3)
        ]
        for processor in processors:
            self.makeBuildableDistroArchSeries(
                distroseries=distroseries,
                architecturetag=processor.name,
                processor=processor,
                owner=self.person,
            )
        [git_ref] = self.factory.makeGitRefs()
        recipe = self.makeRockRecipe(git_ref=git_ref)
        now = get_transaction_timestamp(IStore(distroseries))
        response = self.webservice.named_post(
            recipe["self_link"],
            "requestBuilds",
            channels={"rockcraft": "edge"},
        )
        self.assertEqual(201, response.status)
        build_request_url = response.getHeader("Location")
        build_request = self.webservice.get(build_request_url).jsonBody()
        self.assertThat(
            build_request,
            ContainsDict(
                {
                    "date_requested": AfterPreprocessing(
                        iso8601.parse_date, GreaterThan(now)
                    ),
                    "date_finished": Is(None),
                    "recipe_link": Equals(recipe["self_link"]),
                    "status": Equals("Pending"),
                    "error_message": Is(None),
                    "builds_collection_link": Equals(
                        build_request_url + "/builds"
                    ),
                }
            ),
        )
        self.assertEqual([], self.getCollectionLinks(build_request, "builds"))
        with person_logged_in(self.person):
            rockcraft_yaml = (
                "base: ubuntu@%s\nplatforms:\n" % distroseries.version
            )
            for processor in processors:
                rockcraft_yaml += "    %s:\n" % processor.name
            self.useFixture(GitHostingFixture(blob=rockcraft_yaml))
            [job] = getUtility(IRockRecipeRequestBuildsJobSource).iterReady()
            with dbuser(config.IRockRecipeRequestBuildsJobSource.dbuser):
                JobRunner([job]).runAll()
        date_requested = iso8601.parse_date(build_request["date_requested"])
        now = get_transaction_timestamp(IStore(distroseries))
        build_request = self.webservice.get(
            build_request["self_link"]
        ).jsonBody()
        self.assertThat(
            build_request,
            ContainsDict(
                {
                    "date_requested": AfterPreprocessing(
                        iso8601.parse_date, Equals(date_requested)
                    ),
                    "date_finished": AfterPreprocessing(
                        iso8601.parse_date,
                        MatchesAll(GreaterThan(date_requested), LessThan(now)),
                    ),
                    "recipe_link": Equals(recipe["self_link"]),
                    "status": Equals("Completed"),
                    "error_message": Is(None),
                    "builds_collection_link": Equals(
                        build_request_url + "/builds"
                    ),
                }
            ),
        )
        builds = self.webservice.get(
            build_request["builds_collection_link"]
        ).jsonBody()["entries"]
        with person_logged_in(self.person):
            self.assertThat(
                builds,
                MatchesSetwise(
                    *(
                        ContainsDict(
                            {
                                "recipe_link": Equals(recipe["self_link"]),
                                "archive_link": Equals(
                                    self.getURL(distroseries.main_archive)
                                ),
                                "arch_tag": Equals(processor.name),
                                "channels": Equals({"rockcraft": "edge"}),
                            }
                        )
                        for processor in processors
                    )
                ),
            )

    def test_requestBuilds_failure(self):
        # If the asynchronous build request job fails, this is reflected in
        # the build request entry.
        [git_ref] = self.factory.makeGitRefs()
        recipe = self.makeRockRecipe(git_ref=git_ref)
        now = get_transaction_timestamp(IStore(git_ref))
        response = self.webservice.named_post(
            recipe["self_link"], "requestBuilds"
        )
        self.assertEqual(201, response.status)
        build_request_url = response.getHeader("Location")
        build_request = self.webservice.get(build_request_url).jsonBody()
        self.assertThat(
            build_request,
            ContainsDict(
                {
                    "date_requested": AfterPreprocessing(
                        iso8601.parse_date, GreaterThan(now)
                    ),
                    "date_finished": Is(None),
                    "recipe_link": Equals(recipe["self_link"]),
                    "status": Equals("Pending"),
                    "error_message": Is(None),
                    "builds_collection_link": Equals(
                        build_request_url + "/builds"
                    ),
                }
            ),
        )
        self.assertEqual([], self.getCollectionLinks(build_request, "builds"))
        with person_logged_in(self.person):
            self.useFixture(GitHostingFixture()).getBlob.failure = Exception(
                "Something went wrong"
            )
            [job] = getUtility(IRockRecipeRequestBuildsJobSource).iterReady()
            with dbuser(config.IRockRecipeRequestBuildsJobSource.dbuser):
                JobRunner([job]).runAll()
        date_requested = iso8601.parse_date(build_request["date_requested"])
        now = get_transaction_timestamp(IStore(git_ref))
        build_request = self.webservice.get(
            build_request["self_link"]
        ).jsonBody()
        self.assertThat(
            build_request,
            ContainsDict(
                {
                    "date_requested": AfterPreprocessing(
                        iso8601.parse_date, Equals(date_requested)
                    ),
                    "date_finished": AfterPreprocessing(
                        iso8601.parse_date,
                        MatchesAll(GreaterThan(date_requested), LessThan(now)),
                    ),
                    "recipe_link": Equals(recipe["self_link"]),
                    "status": Equals("Failed"),
                    "error_message": Equals("Something went wrong"),
                    "builds_collection_link": Equals(
                        build_request_url + "/builds"
                    ),
                }
            ),
        )
        self.assertEqual([], self.getCollectionLinks(build_request, "builds"))

    def test_requestBuilds_not_owner(self):
        # If the requester is not the owner or a member of the owner team,
        # build requests are rejected.
        other_team = self.factory.makeTeam(
            displayname="Other Team",
            membership_policy=TeamMembershipPolicy.RESTRICTED,
        )
        other_webservice = webservice_for_person(
            other_team.teamowner, permission=OAuthPermission.WRITE_PUBLIC
        )
        other_webservice.default_api_version = "devel"
        login(ANONYMOUS)
        recipe = self.makeRockRecipe(
            owner=other_team, webservice=other_webservice
        )
        response = self.webservice.named_post(
            recipe["self_link"], "requestBuilds"
        )
        self.assertThat(
            response,
            MatchesStructure.byEquality(
                status=401,
                body=(
                    b"Test Person cannot create rock recipe builds owned by "
                    b"Other Team."
                ),
            ),
        )

    def test_getBuilds(self):
        # The builds, completed_builds, and pending_builds properties are as
        # expected.
        project = self.factory.makeProduct(owner=self.person)
        distroseries = self.factory.makeDistroSeries(
            distribution=getUtility(ILaunchpadCelebrities).ubuntu,
            registrant=self.person,
        )
        processors = [
            self.factory.makeProcessor(supports_virtualized=True)
            for _ in range(4)
        ]
        for processor in processors:
            self.makeBuildableDistroArchSeries(
                distroseries=distroseries,
                architecturetag=processor.name,
                processor=processor,
                owner=self.person,
            )
        recipe = self.makeRockRecipe(project=project)
        response = self.webservice.named_post(
            recipe["self_link"], "requestBuilds"
        )
        self.assertEqual(201, response.status)
        with person_logged_in(self.person):
            rockcraft_yaml = (
                "base: ubuntu@%s\nplatforms:\n" % distroseries.version
            )
            for processor in processors:
                rockcraft_yaml += "    %s:\n" % processor.name
            self.useFixture(GitHostingFixture(blob=rockcraft_yaml))
            [job] = getUtility(IRockRecipeRequestBuildsJobSource).iterReady()
            with dbuser(config.IRockRecipeRequestBuildsJobSource.dbuser):
                JobRunner([job]).runAll()
        builds = self.getCollectionLinks(recipe, "builds")
        self.assertEqual(len(processors), len(builds))
        self.assertEqual(
            [], self.getCollectionLinks(recipe, "completed_builds")
        )
        self.assertEqual(
            builds, self.getCollectionLinks(recipe, "pending_builds")
        )

        with person_logged_in(self.person):
            db_recipe = getUtility(IRockRecipeSet).getByName(
                self.person, project, recipe["name"]
            )
            db_builds = list(db_recipe.builds)
            db_builds[0].updateStatus(
                BuildStatus.BUILDING, date_started=db_recipe.date_created
            )
            db_builds[0].updateStatus(
                BuildStatus.FULLYBUILT,
                date_finished=db_recipe.date_created + timedelta(minutes=10),
            )
        # Builds that have not yet been started are listed last.  This does
        # mean that pending builds that have never been started are sorted
        # to the end, but means that builds that were cancelled before
        # starting don't pollute the start of the collection forever.
        self.assertEqual(builds, self.getCollectionLinks(recipe, "builds"))
        self.assertEqual(
            builds[:1], self.getCollectionLinks(recipe, "completed_builds")
        )
        self.assertEqual(
            builds[1:], self.getCollectionLinks(recipe, "pending_builds")
        )

        with person_logged_in(self.person):
            db_builds[1].updateStatus(
                BuildStatus.BUILDING, date_started=db_recipe.date_created
            )
            db_builds[1].updateStatus(
                BuildStatus.FULLYBUILT,
                date_finished=db_recipe.date_created + timedelta(minutes=20),
            )
        self.assertEqual(
            [builds[1], builds[0], builds[2], builds[3]],
            self.getCollectionLinks(recipe, "builds"),
        )
        self.assertEqual(
            [builds[1], builds[0]],
            self.getCollectionLinks(recipe, "completed_builds"),
        )
        self.assertEqual(
            builds[2:], self.getCollectionLinks(recipe, "pending_builds")
        )

    def test_query_count(self):
        # RockRecipe has a reasonable query count.
        recipe = self.factory.makeRockRecipe(
            registrant=self.person, owner=self.person
        )
        url = api_url(recipe)
        logout()
        store = Store.of(recipe)
        store.flush()
        store.invalidate()
        with StormStatementRecorder() as recorder:
            self.webservice.get(url)
        self.assertThat(recorder, HasQueryCount(Equals(19)))
