# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test rock recipes."""

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
from lp.rocks.interfaces.rockrecipe import (
    ROCK_RECIPE_ALLOW_CREATE,
    IRockRecipe,
    IRockRecipeSet,
    NoSourceForRockRecipe,
    RockRecipeBuildAlreadyPending,
    RockRecipeBuildDisallowedArchitecture,
    RockRecipeBuildRequestStatus,
    RockRecipeFeatureDisabled,
    RockRecipePrivateFeatureDisabled,
)
from lp.rocks.interfaces.rockrecipebuild import IRockRecipeBuild
from lp.rocks.interfaces.rockrecipejob import IRockRecipeRequestBuildsJobSource
from lp.services.database.constants import ONE_DAY_AGO, UTC_NOW
from lp.services.database.interfaces import IStore
from lp.services.database.sqlbase import get_transaction_timestamp
from lp.services.features.testing import FeatureFixture
from lp.services.job.interfaces.job import JobStatus
from lp.services.webapp.snapshot import notify_modified
from lp.testing import TestCaseWithFactory, admin_logged_in, person_logged_in
from lp.testing.layers import DatabaseFunctionalLayer, LaunchpadZopelessLayer


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

    def test_requestBuildsFromJob_restricts_explicit_list(self):
        # requestBuildsFromJob limits builds targeted at an explicit list of
        # architectures to those allowed for the recipe.
        self.useFixture(
            GitHostingFixture(
                blob=dedent(
                    """\
            bases:
              - build-on:
                  - name: ubuntu
                    channel: "20.04"
                    architectures: [sparc]
              - build-on:
                  - name: ubuntu
                    channel: "20.04"
                    architectures: [i386]
              - build-on:
                  - name: ubuntu
                    channel: "20.04"
                    architectures: [avr]
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
        # self.useFixture(GitHostingFixture(blob="name: foo\n"))
        self.useFixture(
            GitHostingFixture(
                blob=dedent(
                    """\
            bases:
              - build-on:
                  - name: ubuntu
                    channel: "20.04"
                    architectures: [sparc]
              - build-on:
                  - name: ubuntu
                    channel: "20.04"
                    architectures: [i386]
              - build-on:
                  - name: ubuntu
                    channel: "20.04"
                    architectures: [avr]
              - build-on:
                  - name: ubuntu
                    channel: "20.04"
                    architectures: [riscv64]
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
        self.assertIsNotNone(
            getUtility(IRockRecipeSet).getByName(owner, project, "condemned")
        )
        with person_logged_in(recipe.owner):
            recipe.destroySelf()
        self.assertIsNone(
            getUtility(IRockRecipeSet).getByName(owner, project, "condemned")
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
