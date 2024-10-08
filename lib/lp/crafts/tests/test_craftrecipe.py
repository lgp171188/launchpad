# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test craft recipes."""

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
from lp.crafts.interfaces.craftrecipe import (
    CRAFT_RECIPE_ALLOW_CREATE,
    CRAFT_RECIPE_PRIVATE_FEATURE_FLAG,
    BadCraftRecipeSearchContext,
    CraftRecipeBuildAlreadyPending,
    CraftRecipeBuildDisallowedArchitecture,
    CraftRecipeBuildRequestStatus,
    CraftRecipeFeatureDisabled,
    CraftRecipePrivateFeatureDisabled,
    ICraftRecipe,
    ICraftRecipeSet,
    ICraftRecipeView,
    NoSourceForCraftRecipe,
)
from lp.crafts.interfaces.craftrecipebuild import (
    ICraftRecipeBuild,
    ICraftRecipeBuildSet,
)
from lp.crafts.interfaces.craftrecipejob import (
    ICraftRecipeRequestBuildsJobSource,
)
from lp.crafts.model.craftrecipebuild import CraftFile
from lp.crafts.model.craftrecipejob import CraftRecipeJob
from lp.registry.enums import PersonVisibility, TeamMembershipPolicy
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


class TestCraftRecipeFeatureFlags(TestCaseWithFactory):

    layer = LaunchpadZopelessLayer

    def test_feature_flag_disabled(self):
        # Without a feature flag, we will not create any craft recipes.
        self.assertRaises(
            CraftRecipeFeatureDisabled, self.factory.makeCraftRecipe
        )

    def test_private_feature_flag_disabled(self):
        # Without a private feature flag, we will not create new private
        # craft recipes.
        self.useFixture(FeatureFixture({CRAFT_RECIPE_ALLOW_CREATE: "on"}))
        self.assertRaises(
            CraftRecipePrivateFeatureDisabled,
            self.factory.makeCraftRecipe,
            information_type=InformationType.PROPRIETARY,
        )


class TestCraftRecipe(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.useFixture(FeatureFixture({CRAFT_RECIPE_ALLOW_CREATE: "on"}))

    def test_implements_interfaces(self):
        # CraftRecipe implements ICraftRecipe.
        recipe = self.factory.makeCraftRecipe()
        with admin_logged_in():
            self.assertProvides(recipe, ICraftRecipe)

    def test___repr__(self):
        # CraftRecipe objects have an informative __repr__.
        recipe = self.factory.makeCraftRecipe()
        self.assertEqual(
            "<CraftRecipe ~%s/%s/+craft/%s>"
            % (recipe.owner.name, recipe.project.name, recipe.name),
            repr(recipe),
        )

    def test_avoids_problematic_snapshots(self):
        self.assertThat(
            self.factory.makeCraftRecipe(),
            DoesNotSnapshot(
                [
                    "pending_build_requests",
                    "failed_build_requests",
                    "builds",
                    "completed_builds",
                    "pending_builds",
                ],
                ICraftRecipeView,
            ),
        )

    def test_initial_date_last_modified(self):
        # The initial value of date_last_modified is date_created.
        recipe = self.factory.makeCraftRecipe(date_created=ONE_DAY_AGO)
        self.assertEqual(recipe.date_created, recipe.date_last_modified)

    def test_modifiedevent_sets_date_last_modified(self):
        # When a CraftRecipe receives an object modified event, the last
        # modified date is set to UTC_NOW.
        recipe = self.factory.makeCraftRecipe(date_created=ONE_DAY_AGO)
        with notify_modified(removeSecurityProxy(recipe), ["name"]):
            pass
        self.assertSqlAttributeEqualsDate(
            recipe, "date_last_modified", UTC_NOW
        )

    def test_delete_without_builds(self):
        # A craft recipe with no builds can be deleted.
        owner = self.factory.makePerson()
        project = self.factory.makeProduct()
        recipe = self.factory.makeCraftRecipe(
            registrant=owner, owner=owner, project=project, name="condemned"
        )
        self.assertTrue(
            getUtility(ICraftRecipeSet).exists(owner, project, "condemned")
        )
        with person_logged_in(recipe.owner):
            recipe.destroySelf()
        self.assertFalse(
            getUtility(ICraftRecipeSet).exists(owner, project, "condemned")
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
        # requestBuild creates a new CraftRecipeBuild.
        recipe = self.factory.makeCraftRecipe()
        das = self.makeBuildableDistroArchSeries()
        build_request = self.factory.makeCraftRecipeBuildRequest(recipe=recipe)
        build = recipe.requestBuild(build_request, das)
        self.assertTrue(ICraftRecipeBuild.providedBy(build))
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
        recipe = self.factory.makeCraftRecipe()
        das = self.makeBuildableDistroArchSeries()
        build_request = self.factory.makeCraftRecipeBuildRequest(recipe=recipe)
        build = recipe.requestBuild(build_request, das)
        queue_record = build.buildqueue_record
        queue_record.score()
        self.assertEqual(2510, queue_record.lastscore)

    def test_requestBuild_channels(self):
        # requestBuild can select non-default channels.
        recipe = self.factory.makeCraftRecipe()
        das = self.makeBuildableDistroArchSeries()
        build_request = self.factory.makeCraftRecipeBuildRequest(recipe=recipe)
        build = recipe.requestBuild(
            build_request, das, channels={"sourcecraft": "edge"}
        )
        self.assertEqual({"sourcecraft": "edge"}, build.channels)

    def test_requestBuild_rejects_repeats(self):
        # requestBuild refuses if there is already a pending build.
        recipe = self.factory.makeCraftRecipe()
        distro_series = self.factory.makeDistroSeries()
        arches = [
            self.makeBuildableDistroArchSeries(distroseries=distro_series)
            for _ in range(2)
        ]
        build_request = self.factory.makeCraftRecipeBuildRequest(recipe=recipe)
        old_build = recipe.requestBuild(build_request, arches[0])
        self.assertRaises(
            CraftRecipeBuildAlreadyPending,
            recipe.requestBuild,
            build_request,
            arches[0],
        )
        # We can build for a different distroarchseries.
        recipe.requestBuild(build_request, arches[1])
        # channels=None and channels={} are treated as equivalent, but
        # anything else allows a new build.
        self.assertRaises(
            CraftRecipeBuildAlreadyPending,
            recipe.requestBuild,
            build_request,
            arches[0],
            channels={},
        )
        recipe.requestBuild(
            build_request, arches[0], channels={"core": "edge"}
        )
        self.assertRaises(
            CraftRecipeBuildAlreadyPending,
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
        recipe = self.factory.makeCraftRecipe()
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
            recipe = self.factory.makeCraftRecipe(
                require_virtualized=recipe_virt
            )
            build_request = self.factory.makeCraftRecipeBuildRequest(
                recipe=recipe
            )
            build = recipe.requestBuild(build_request, das)
            self.assertEqual(build_virt, build.virtualized)

    def test_requestBuild_nonvirtualized(self):
        # A non-virtualized processor can build a craft recipe iff the
        # recipe has require_virtualized set to False.
        recipe = self.factory.makeCraftRecipe()
        distro_series = self.factory.makeDistroSeries()
        das = self.makeBuildableDistroArchSeries(
            distroseries=distro_series,
            supports_virtualized=False,
            supports_nonvirtualized=True,
        )
        build_request = self.factory.makeCraftRecipeBuildRequest(recipe=recipe)
        self.assertRaises(
            CraftRecipeBuildDisallowedArchitecture,
            recipe.requestBuild,
            build_request,
            das,
        )
        with admin_logged_in():
            recipe.require_virtualized = False
        recipe.requestBuild(build_request, das)

    def test_requestBuilds(self):
        # requestBuilds schedules a job and returns a corresponding
        # CraftRecipeBuildRequest.
        recipe = self.factory.makeCraftRecipe()
        now = get_transaction_timestamp(IStore(recipe))
        with person_logged_in(recipe.owner.teamowner):
            request = recipe.requestBuilds(recipe.owner.teamowner)
        self.assertThat(
            request,
            MatchesStructure(
                date_requested=Equals(now),
                date_finished=Is(None),
                recipe=Equals(recipe),
                status=Equals(CraftRecipeBuildRequestStatus.PENDING),
                error_message=Is(None),
                channels=Is(None),
                architectures=Is(None),
            ),
        )
        [job] = getUtility(ICraftRecipeRequestBuildsJobSource).iterReady()
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
        recipe = self.factory.makeCraftRecipe()
        now = get_transaction_timestamp(IStore(recipe))
        with person_logged_in(recipe.owner.teamowner):
            request = recipe.requestBuilds(
                recipe.owner.teamowner, channels={"sourcecraft": "edge"}
            )
        self.assertThat(
            request,
            MatchesStructure(
                date_requested=Equals(now),
                date_finished=Is(None),
                recipe=Equals(recipe),
                status=Equals(CraftRecipeBuildRequestStatus.PENDING),
                error_message=Is(None),
                channels=MatchesDict({"sourcecraft": Equals("edge")}),
                architectures=Is(None),
            ),
        )
        [job] = getUtility(ICraftRecipeRequestBuildsJobSource).iterReady()
        self.assertThat(
            job,
            MatchesStructure(
                job_id=Equals(request.id),
                job=MatchesStructure.byEquality(status=JobStatus.WAITING),
                recipe=Equals(recipe),
                requester=Equals(recipe.owner.teamowner),
                channels=Equals({"sourcecraft": "edge"}),
                architectures=Is(None),
            ),
        )

    def test_requestBuilds_with_architectures(self):
        # If asked to build for particular architectures, requestBuilds
        # passes those through to the job.
        recipe = self.factory.makeCraftRecipe()
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
                status=Equals(CraftRecipeBuildRequestStatus.PENDING),
                error_message=Is(None),
                channels=Is(None),
                architectures=MatchesSetwise(Equals("amd64"), Equals("i386")),
            ),
        )
        [job] = getUtility(ICraftRecipeRequestBuildsJobSource).iterReady()
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
        recipe = self.factory.makeCraftRecipe(git_ref=git_ref)
        distro_series = self.factory.makeDistroSeries(
            distribution=getUtility(ILaunchpadCelebrities).ubuntu,
            version=distro_series_version,
        )
        for arch_tag in arch_tags:
            self.makeBuildableDistroArchSeries(
                distroseries=distro_series, architecturetag=arch_tag
            )
        return getUtility(ICraftRecipeRequestBuildsJobSource).create(
            recipe, recipe.owner.teamowner, {"sourcecraft": "edge"}
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

    def test_requestBuildsFromJob_restricts_explicit_list(self):
        # requestBuildsFromJob limits builds targeted at an explicit list of
        # architectures to those allowed for the recipe.
        self.useFixture(
            GitHostingFixture(
                blob=dedent(
                    """\
            base: ubuntu@20.04
            platforms:
                amd64:
                armhf:
            """
                )
            )
        )
        job = self.makeRequestBuildsJob(
            "20.04", ["amd64", "armhf", "mips64el"]
        )
        self.assertEqual(
            get_transaction_timestamp(IStore(job.recipe)), job.date_created
        )
        transaction.commit()
        with person_logged_in(job.requester):
            builds = job.recipe.requestBuildsFromJob(
                job.build_request, channels=removeSecurityProxy(job.channels)
            )
        self.assertRequestedBuildsMatch(
            builds, job, "20.04", ["amd64", "armhf"], job.channels
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
                armhf:
                riscv64:
            """
                )
            )
        )
        job = self.makeRequestBuildsJob(
            "20.04", ["armhf", "mips64el", "riscv64"]
        )
        self.assertEqual(
            get_transaction_timestamp(IStore(job.recipe)), job.date_created
        )
        transaction.commit()
        with person_logged_in(job.requester):
            builds = job.recipe.requestBuildsFromJob(
                job.build_request,
                channels=removeSecurityProxy(job.channels),
                architectures={"armhf", "riscv64"},
            )
        self.assertRequestedBuildsMatch(
            builds, job, "20.04", ["armhf", "riscv64"], job.channels
        )

    def test_requestBuild_fetch_service(self):
        # Activate fetch service for a craft recipe.
        recipe = self.factory.makeCraftRecipe(use_fetch_service=True)
        self.assertEqual(True, recipe.use_fetch_service)
        distro_series = self.factory.makeDistroSeries()
        das = self.makeBuildableDistroArchSeries(
            distroseries=distro_series,
        )
        build_request = self.factory.makeCraftRecipeBuildRequest(recipe=recipe)
        build = recipe.requestBuild(build_request, das)
        self.assertEqual(True, build.recipe.use_fetch_service)


class TestCraftRecipeSet(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.useFixture(FeatureFixture({CRAFT_RECIPE_ALLOW_CREATE: "on"}))

    def test_class_implements_interfaces(self):
        # The CraftRecipeSet class implements ICraftRecipeSet.
        self.assertProvides(getUtility(ICraftRecipeSet), ICraftRecipeSet)

    def makeCraftRecipeComponents(self, git_ref=None):
        """Return a dict of values that can be used to make a craft recipe.

        Suggested use: provide as kwargs to ICraftRecipeSet.new.

        :param git_ref: An `IGitRef`, or None.
        """
        registrant = self.factory.makePerson()
        components = {
            "registrant": registrant,
            "owner": self.factory.makeTeam(owner=registrant),
            "project": self.factory.makeProduct(),
            "name": self.factory.getUniqueUnicode("craft-name"),
        }
        if git_ref is None:
            git_ref = self.factory.makeGitRefs()[0]
        components["git_ref"] = git_ref
        return components

    def test_creation_git(self):
        # The metadata entries supplied when a craft recipe is created for a
        # Git branch are present on the new object.
        [ref] = self.factory.makeGitRefs()
        components = self.makeCraftRecipeComponents(git_ref=ref)
        recipe = getUtility(ICraftRecipeSet).new(**components)
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

    def test_creation_git_url(self):
        # A craft recipe can be backed directly by a URL for an external Git
        # repository, rather than a Git repository hosted in Launchpad.
        ref = self.factory.makeGitRefRemote()
        components = self.makeCraftRecipeComponents(git_ref=ref)
        craft_recipe = getUtility(ICraftRecipeSet).new(**components)
        self.assertIsNone(craft_recipe.git_repository)
        self.assertEqual(ref.repository_url, craft_recipe.git_repository_url)
        self.assertEqual(ref.path, craft_recipe.git_path)
        self.assertEqual(ref, craft_recipe.git_ref)

    def test_creation_no_source(self):
        # Attempting to create a craft recipe without a Git repository
        # fails.
        registrant = self.factory.makePerson()
        self.assertRaises(
            NoSourceForCraftRecipe,
            getUtility(ICraftRecipeSet).new,
            registrant,
            registrant,
            self.factory.makeProduct(),
            self.factory.getUniqueUnicode("craft-name"),
        )

    def test_getByName(self):
        owner = self.factory.makePerson()
        project = self.factory.makeProduct()
        project_recipe = self.factory.makeCraftRecipe(
            registrant=owner, owner=owner, project=project, name="proj-craft"
        )
        self.factory.makeCraftRecipe(
            registrant=owner, owner=owner, name="proj-craft"
        )

        self.assertEqual(
            project_recipe,
            getUtility(ICraftRecipeSet).getByName(
                owner, project, "proj-craft"
            ),
        )

    def test_findByGitRepository(self):
        # ICraftRecipeSet.findByGitRepository returns all craft recipes with
        # the given Git repository.
        repositories = [self.factory.makeGitRepository() for i in range(2)]
        recipes = []
        for repository in repositories:
            for _ in range(2):
                [ref] = self.factory.makeGitRefs(repository=repository)
                recipes.append(self.factory.makeCraftRecipe(git_ref=ref))
        recipe_set = getUtility(ICraftRecipeSet)
        self.assertContentEqual(
            recipes[:2], recipe_set.findByGitRepository(repositories[0])
        )
        self.assertContentEqual(
            recipes[2:], recipe_set.findByGitRepository(repositories[1])
        )

    def test_findByGitRepository_paths(self):
        # ICraftRecipeSet.findByGitRepository can restrict by reference
        # paths.
        repositories = [self.factory.makeGitRepository() for i in range(2)]
        recipes = []
        for repository in repositories:
            for _ in range(3):
                [ref] = self.factory.makeGitRefs(repository=repository)
                recipes.append(self.factory.makeCraftRecipe(git_ref=ref))
        recipe_set = getUtility(ICraftRecipeSet)
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
        # ICraftRecipeSet.findByOwner returns all craft recipes with the
        # given owner.
        owners = [self.factory.makePerson() for i in range(2)]
        recipes = []
        for owner in owners:
            for _ in range(2):
                recipes.append(
                    self.factory.makeCraftRecipe(registrant=owner, owner=owner)
                )
        recipe_set = getUtility(ICraftRecipeSet)
        self.assertContentEqual(recipes[:2], recipe_set.findByOwner(owners[0]))
        self.assertContentEqual(recipes[2:], recipe_set.findByOwner(owners[1]))

    def test_detachFromGitRepository(self):
        # ICraftRecipeSet.detachFromGitRepository clears the given Git
        # repository from all craft recipes.
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
                    self.factory.makeCraftRecipe(
                        git_ref=ref, date_created=ONE_DAY_AGO
                    )
                )
        getUtility(ICraftRecipeSet).detachFromGitRepository(repositories[0])
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

    def test_findByPerson(self):
        # ICraftRecipeSet.findByPerson returns all craft recipes with the
        # given owner or based on repositories with the given owner.
        owners = [self.factory.makePerson() for i in range(2)]
        recipes = []
        for owner in owners:
            recipes.append(
                self.factory.makeCraftRecipe(registrant=owner, owner=owner)
            )
            [ref] = self.factory.makeGitRefs(owner=owner)
            recipes.append(self.factory.makeCraftRecipe(git_ref=ref))
        recipe_set = getUtility(ICraftRecipeSet)
        self.assertContentEqual(
            recipes[:2], recipe_set.findByPerson(owners[0])
        )
        self.assertContentEqual(
            recipes[2:], recipe_set.findByPerson(owners[1])
        )

    def test_findByProject(self):
        # ICraftRecipeSet.findByProject returns all craft recipes based on
        # repositories for the given project, and craft recipes associated
        # directly with the project.
        projects = [self.factory.makeProduct() for i in range(2)]
        recipes = []
        for project in projects:
            [ref] = self.factory.makeGitRefs(target=project)
            recipes.append(self.factory.makeCraftRecipe(git_ref=ref))
            recipes.append(self.factory.makeCraftRecipe(project=project))
        [ref] = self.factory.makeGitRefs(target=None)
        recipes.append(self.factory.makeCraftRecipe(git_ref=ref))
        recipe_set = getUtility(ICraftRecipeSet)
        self.assertContentEqual(
            recipes[:2], recipe_set.findByProject(projects[0])
        )
        self.assertContentEqual(
            recipes[2:4], recipe_set.findByProject(projects[1])
        )

    def test_findByGitRef(self):
        # ICraftRecipeSet.findByGitRef returns all craft recipes with the
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
            recipes.append(self.factory.makeCraftRecipe(git_ref=refs[-2]))
            recipes.append(self.factory.makeCraftRecipe(git_ref=refs[-1]))
        recipe_set = getUtility(ICraftRecipeSet)
        for ref, recipe in zip(refs, recipes):
            self.assertContentEqual([recipe], recipe_set.findByGitRef(ref))

    def test_findByContext(self):
        # ICraftRecipeSet.findByContext returns all craft recipes with the
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
        recipes.append(self.factory.makeCraftRecipe(git_ref=refs[0]))
        recipes.append(self.factory.makeCraftRecipe(git_ref=refs[1]))
        recipes.append(
            self.factory.makeCraftRecipe(
                registrant=person, owner=person, git_ref=other_refs[0]
            )
        )
        recipes.append(
            self.factory.makeCraftRecipe(
                project=project, git_ref=other_refs[1]
            )
        )
        recipe_set = getUtility(ICraftRecipeSet)
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
            BadCraftRecipeSearchContext,
            recipe_set.findByContext,
            self.factory.makeDistribution(),
        )

    def test_admins_can_update_admin_only_fields(self):
        # The admin fields can be updated by an admin
        [ref] = self.factory.makeGitRefs()
        craft = self.factory.makeCraftRecipe(
            git_ref=ref, use_fetch_service=True
        )

        admin_fields = [
            "require_virtualized",
            "use_fetch_service",
        ]

        for field_name in admin_fields:
            # exception isn't raised when an admin does the same
            with admin_logged_in():
                setattr(craft, field_name, True)

    def test_non_admins_cannot_update_admin_only_fields(self):
        # The admin fields cannot be updated by a non admin
        [ref] = self.factory.makeGitRefs()
        craft = self.factory.makeCraftRecipe(
            git_ref=ref, use_fetch_service=True
        )
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
                    craft,
                    field_name,
                    True,
                )


class TestCraftRecipeDeleteWithBuilds(TestCaseWithFactory):

    layer = LaunchpadFunctionalLayer

    def setUp(self):
        super().setUp()
        self.useFixture(FeatureFixture({CRAFT_RECIPE_ALLOW_CREATE: "on"}))

    def test_delete_with_builds(self):
        # A craft recipe with build requests and builds can be deleted.
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
        sourcecraft_yaml = (
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
        self.useFixture(GitHostingFixture(blob=sourcecraft_yaml))
        [git_ref] = self.factory.makeGitRefs()
        condemned_recipe = self.factory.makeCraftRecipe(
            registrant=owner,
            owner=owner,
            project=project,
            name="condemned",
            git_ref=git_ref,
        )
        other_recipe = self.factory.makeCraftRecipe(
            registrant=owner, owner=owner, project=project, git_ref=git_ref
        )
        self.assertTrue(
            getUtility(ICraftRecipeSet).exists(owner, project, "condemned")
        )
        with person_logged_in(owner):
            requests = []
            jobs = []
            for recipe in (condemned_recipe, other_recipe):
                requests.append(recipe.requestBuilds(owner))
                jobs.append(removeSecurityProxy(requests[-1])._job)
            with dbuser(config.ICraftRecipeRequestBuildsJobSource.dbuser):
                JobRunner(jobs).runAll()
            for job in jobs:
                self.assertEqual(JobStatus.COMPLETED, job.job.status)
            [build] = requests[0].builds
            [other_build] = requests[1].builds
            craft_file = self.factory.makeCraftFile(build=build)
            other_craft_file = self.factory.makeCraftFile(build=other_build)
        store = Store.of(condemned_recipe)
        store.flush()
        job_ids = [job.job_id for job in jobs]
        build_id = build.id
        build_queue_id = build.buildqueue_record.id
        build_farm_job_id = removeSecurityProxy(build).build_farm_job_id
        craft_file_id = removeSecurityProxy(craft_file).id
        with person_logged_in(condemned_recipe.owner):
            condemned_recipe.destroySelf()
        flush_database_caches()
        # The deleted recipe, its build requests, and its are gone.
        self.assertFalse(
            getUtility(ICraftRecipeSet).exists(owner, project, "condemned")
        )
        self.assertIsNone(store.get(CraftRecipeJob, job_ids[0]))
        self.assertIsNone(getUtility(ICraftRecipeBuildSet).getByID(build_id))
        self.assertIsNone(store.get(BuildQueue, build_queue_id))
        self.assertIsNone(store.get(BuildFarmJob, build_farm_job_id))
        self.assertIsNone(store.get(CraftFile, craft_file_id))
        # Unrelated build requests, build jobs and builds are still present.
        self.assertEqual(
            removeSecurityProxy(jobs[1]).context,
            store.get(CraftRecipeJob, job_ids[1]),
        )
        self.assertEqual(
            other_build,
            getUtility(ICraftRecipeBuildSet).getByID(other_build.id),
        )
        self.assertIsNotNone(other_build.buildqueue_record)
        self.assertIsNotNone(
            store.get(CraftFile, removeSecurityProxy(other_craft_file).id)
        )


class TestCraftRecipeWebservice(TestCaseWithFactory):

    layer = LaunchpadFunctionalLayer

    def setUp(self):
        super().setUp()
        self.useFixture(
            FeatureFixture(
                {
                    CRAFT_RECIPE_ALLOW_CREATE: "on",
                    CRAFT_RECIPE_PRIVATE_FEATURE_FLAG: "on",
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

    def makeCraftRecipe(
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
            "/+craft-recipes",
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
        # Craft recipe creation based on a Git branch works.
        team = self.factory.makeTeam(
            owner=self.person,
            membership_policy=TeamMembershipPolicy.RESTRICTED,
        )
        project = self.factory.makeProduct(owner=team)
        [ref] = self.factory.makeGitRefs()
        recipe = self.makeCraftRecipe(
            owner=team, project=project, name="test-craft", git_ref=ref
        )
        with person_logged_in(self.person):
            self.assertThat(
                recipe,
                ContainsDict(
                    {
                        "registrant_link": Equals(self.getURL(self.person)),
                        "owner_link": Equals(self.getURL(team)),
                        "project_link": Equals(self.getURL(project)),
                        "name": Equals("test-craft"),
                        "git_ref_link": Equals(self.getURL(ref)),
                        "build_path": Is(None),
                        "require_virtualized": Is(True),
                    }
                ),
            )

    def test_new_store_options(self):
        # The store-related options in CraftRecipe.new work.
        store_name = self.factory.getUniqueUnicode()
        recipe = self.makeCraftRecipe(
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
        # An attempt to create a duplicate craft recipe fails.
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
        self.makeCraftRecipe(
            owner=team, project=project, name=name, git_ref=git_ref
        )
        response = self.webservice.named_post(
            "/+craft-recipes",
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
                    b"There is already a craft recipe with the same project, "
                    b"owner, and name."
                ),
            ),
        )

    def test_not_owner(self):
        # If the registrant is not the owner or a member of the owner team,
        # craft recipe creation fails.
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
            "/+craft-recipes",
            "new",
            owner=other_person_url,
            project=project_url,
            name="test-craft",
            git_ref=git_ref_url,
        )
        self.assertThat(
            response,
            MatchesStructure.byEquality(
                status=401,
                body=(
                    b"Test Person cannot create craft recipes owned by "
                    b"Other Person."
                ),
            ),
        )
        response = self.webservice.named_post(
            "/+craft-recipes",
            "new",
            owner=other_team_url,
            project=project_url,
            name="test-craft",
            git_ref=git_ref_url,
        )
        self.assertThat(
            response,
            MatchesStructure.byEquality(
                status=401, body=b"Test Person is not a member of Other Team."
            ),
        )

    def test_cannot_set_private_components_of_public_recipe(self):
        # If a craft recipe is public, then trying to change its owner or
        # git_ref components to be private fails.
        recipe = self.factory.makeCraftRecipe(
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
                body=b"A public craft recipe cannot have a private owner.",
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
                body=b"A public craft recipe cannot have a private "
                b"repository.",
            ),
        )

    def test_is_stale(self):
        # is_stale is exported and is read-only.
        recipe = self.makeCraftRecipe()
        self.assertTrue(recipe["is_stale"])
        response = self.webservice.patch(
            recipe["self_link"],
            "application/json",
            json.dumps({"is_stale": False}),
        )
        self.assertEqual(400, response.status)

    def test_getByName(self):
        # lp.craft_recipes.getByName returns a matching CraftRecipe.
        project = self.factory.makeProduct(owner=self.person)
        name = self.factory.getUniqueUnicode()
        recipe = self.makeCraftRecipe(project=project, name=name)
        with person_logged_in(self.person):
            owner_url = api_url(self.person)
            project_url = api_url(project)
        response = self.webservice.named_get(
            "/+craft-recipes",
            "getByName",
            owner=owner_url,
            project=project_url,
            name=name,
        )
        self.assertEqual(200, response.status)
        self.assertEqual(recipe, response.jsonBody())

    def test_getByName_missing(self):
        # lp.craft_recipes.getByName returns 404 for a non-existent
        # CraftRecipe.
        project = self.factory.makeProduct(owner=self.person)
        logout()
        with person_logged_in(self.person):
            owner_url = api_url(self.person)
            project_url = api_url(project)
        response = self.webservice.named_get(
            "/+craft-recipes",
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
                    b"No such craft recipe with this owner and project: "
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
        recipe = self.makeCraftRecipe(git_ref=git_ref)
        now = get_transaction_timestamp(IStore(distroseries))
        response = self.webservice.named_post(
            recipe["self_link"],
            "requestBuilds",
            channels={"sourcecraft": "edge"},
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
            sourcecraft_yaml = f"""
                name: ruff
                license: MIT
                version: 0.4.9
                summary: An extremely fast Python linter, written in Rust.
                description: Ruff aims to be orders of magnitude faster...
                base: ubuntu@{distroseries.version}
                platforms:
                """
            for processor in processors:
                sourcecraft_yaml += f"""
                    {processor.name}:
                        build-on: [{processor.name}]
                        build-for: {processor.name}
                    """
            self.useFixture(GitHostingFixture(blob=sourcecraft_yaml))
            [job] = getUtility(ICraftRecipeRequestBuildsJobSource).iterReady()
            with dbuser(config.ICraftRecipeRequestBuildsJobSource.dbuser):
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
                                "channels": Equals({"sourcecraft": "edge"}),
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
        recipe = self.makeCraftRecipe(git_ref=git_ref)
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
            [job] = getUtility(ICraftRecipeRequestBuildsJobSource).iterReady()
            with dbuser(config.ICraftRecipeRequestBuildsJobSource.dbuser):
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
        recipe = self.makeCraftRecipe(
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
                    b"Test Person cannot create craft recipe builds owned by "
                    b"Other Team."
                ),
            ),
        )

    def test_requestBuilds_with_architectures(self):
        # when a subset of architectures are requested, we only build them
        # not all listed in the sourcecraft.yaml file
        distroseries = self.factory.makeDistroSeries(
            distribution=getUtility(ILaunchpadCelebrities).ubuntu,
            registrant=self.person,
        )
        amd640 = self.factory.makeProcessor(
            name="amd640", supports_virtualized=True
        )
        risc500 = self.factory.makeProcessor(
            name="risc500", supports_virtualized=True
        )
        s400x = self.factory.makeProcessor(
            name="s400x", supports_virtualized=True
        )
        processors = [amd640, risc500, s400x]
        for processor in processors:
            self.makeBuildableDistroArchSeries(
                distroseries=distroseries,
                architecturetag=processor.name,
                processor=processor,
                owner=self.person,
            )
        [git_ref] = self.factory.makeGitRefs()
        recipe = self.makeCraftRecipe(git_ref=git_ref)
        now = get_transaction_timestamp(IStore(distroseries))
        requested_architectures = [amd640, risc500]
        response = self.webservice.named_post(
            recipe["self_link"],
            "requestBuilds",
            channels={"sourcecraft": "edge"},
            architectures=[api_url(arch) for arch in requested_architectures],
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
            sourcecraft_yaml = f"""
                name: ruff
                license: MIT
                version: 0.4.9
                summary: An extremely fast Python linter, written in Rust.
                description: Ruff aims to be orders of magnitude faster...
                base: ubuntu@{distroseries.version}
                platforms:
                """
            for processor in processors:
                sourcecraft_yaml += f"""
                    {processor.name}:
                        build-on: [{processor.name}]
                        build-for: {processor.name}
                    """
            self.useFixture(GitHostingFixture(blob=sourcecraft_yaml))
            [job] = getUtility(ICraftRecipeRequestBuildsJobSource).iterReady()
            with dbuser(config.ICraftRecipeRequestBuildsJobSource.dbuser):
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
                                "channels": Equals({"sourcecraft": "edge"}),
                            }
                        )
                        for processor in requested_architectures
                    )
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
        recipe = self.makeCraftRecipe(project=project)
        response = self.webservice.named_post(
            recipe["self_link"], "requestBuilds"
        )
        self.assertEqual(201, response.status)
        with person_logged_in(self.person):
            sourcecraft_yaml = f"""
                name: ruff
                license: MIT
                version: 0.4.9
                summary: An extremely fast Python linter, written in Rust.
                description: Ruff aims to be orders of magnitude faster...
                base: ubuntu@{distroseries.version}
                platforms:
                """
            for processor in processors:
                sourcecraft_yaml += f"""
                    {processor.name}:
                        build-on: [{processor.name}]
                        build-for: {processor.name}
                    """
            self.useFixture(GitHostingFixture(blob=sourcecraft_yaml))
            [job] = getUtility(ICraftRecipeRequestBuildsJobSource).iterReady()
            with dbuser(config.ICraftRecipeRequestBuildsJobSource.dbuser):
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
            db_recipe = getUtility(ICraftRecipeSet).getByName(
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
        # CraftRecipe has a reasonable query count.
        recipe = self.factory.makeCraftRecipe(
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
