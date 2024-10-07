# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test craft recipes."""

from textwrap import dedent

import transaction
from storm.locals import Store
from testtools.matchers import (
    Equals,
    Is,
    MatchesDict,
    MatchesSetwise,
    MatchesStructure,
)
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.app.enums import InformationType
from lp.app.interfaces.launchpad import ILaunchpadCelebrities
from lp.buildmaster.enums import BuildQueueStatus, BuildStatus
from lp.buildmaster.interfaces.buildqueue import IBuildQueue
from lp.buildmaster.interfaces.processor import (
    IProcessorSet,
    ProcessorNotFound,
)
from lp.buildmaster.model.buildqueue import BuildQueue
from lp.code.tests.helpers import GitHostingFixture
from lp.crafts.interfaces.craftrecipe import (
    CRAFT_RECIPE_ALLOW_CREATE,
    CraftRecipeBuildAlreadyPending,
    CraftRecipeBuildDisallowedArchitecture,
    CraftRecipeBuildRequestStatus,
    CraftRecipeFeatureDisabled,
    CraftRecipePrivateFeatureDisabled,
    ICraftRecipe,
    ICraftRecipeSet,
    NoSourceForCraftRecipe,
)
from lp.crafts.interfaces.craftrecipebuild import ICraftRecipeBuild
from lp.crafts.interfaces.craftrecipejob import (
    ICraftRecipeRequestBuildsJobSource,
)
from lp.services.database.constants import ONE_DAY_AGO, UTC_NOW
from lp.services.database.interfaces import IStore
from lp.services.database.sqlbase import get_transaction_timestamp
from lp.services.features.testing import FeatureFixture
from lp.services.job.interfaces.job import JobStatus
from lp.services.webapp.snapshot import notify_modified
from lp.testing import TestCaseWithFactory, admin_logged_in, person_logged_in
from lp.testing.layers import DatabaseFunctionalLayer, LaunchpadZopelessLayer


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
        self.assertIsNotNone(
            getUtility(ICraftRecipeSet).getByName(owner, project, "condemned")
        )
        with person_logged_in(recipe.owner):
            recipe.destroySelf()
        self.assertIsNone(
            getUtility(ICraftRecipeSet).getByName(owner, project, "condemned")
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
                sparc:
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
            builds, job, "20.04", ["sparc", "avr"], job.channels
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
                sparc:
                i386:
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
