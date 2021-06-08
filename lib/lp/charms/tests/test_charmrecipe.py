# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test charm recipes."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type

from textwrap import dedent

from storm.locals import Store
from testtools.matchers import (
    Equals,
    Is,
    MatchesDict,
    MatchesSetwise,
    MatchesStructure,
    )
import transaction
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.app.enums import InformationType
from lp.app.interfaces.launchpad import ILaunchpadCelebrities
from lp.buildmaster.enums import (
    BuildQueueStatus,
    BuildStatus,
    )
from lp.buildmaster.interfaces.buildqueue import IBuildQueue
from lp.buildmaster.interfaces.processor import (
    IProcessorSet,
    ProcessorNotFound,
    )
from lp.buildmaster.model.buildqueue import BuildQueue
from lp.charms.interfaces.charmrecipe import (
    BadCharmRecipeSearchContext,
    CHARM_RECIPE_ALLOW_CREATE,
    CHARM_RECIPE_BUILD_DISTRIBUTION,
    CharmRecipeBuildAlreadyPending,
    CharmRecipeBuildDisallowedArchitecture,
    CharmRecipeBuildRequestStatus,
    CharmRecipeFeatureDisabled,
    CharmRecipePrivateFeatureDisabled,
    ICharmRecipe,
    ICharmRecipeSet,
    NoSourceForCharmRecipe,
    )
from lp.charms.interfaces.charmrecipebuild import ICharmRecipeBuild
from lp.charms.interfaces.charmrecipejob import (
    ICharmRecipeRequestBuildsJobSource,
    )
from lp.code.tests.helpers import GitHostingFixture
from lp.registry.interfaces.series import SeriesStatus
from lp.services.database.constants import (
    ONE_DAY_AGO,
    UTC_NOW,
    )
from lp.services.database.interfaces import IStore
from lp.services.database.sqlbase import get_transaction_timestamp
from lp.services.features.testing import FeatureFixture
from lp.services.job.interfaces.job import JobStatus
from lp.services.webapp.snapshot import notify_modified
from lp.testing import (
    admin_logged_in,
    person_logged_in,
    TestCaseWithFactory,
    )
from lp.testing.layers import (
    DatabaseFunctionalLayer,
    LaunchpadZopelessLayer,
    )


class TestCharmRecipeFeatureFlags(TestCaseWithFactory):

    layer = LaunchpadZopelessLayer

    def test_feature_flag_disabled(self):
        # Without a feature flag, we wil not create any charm recipes.
        self.assertRaises(
            CharmRecipeFeatureDisabled, self.factory.makeCharmRecipe)

    def test_private_feature_flag_disabled(self):
        # Without a private feature flag, we wil not create new private
        # charm recipes.
        self.useFixture(FeatureFixture({CHARM_RECIPE_ALLOW_CREATE: "on"}))
        self.assertRaises(
            CharmRecipePrivateFeatureDisabled, self.factory.makeCharmRecipe,
            information_type=InformationType.PROPRIETARY)


class TestCharmRecipe(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestCharmRecipe, self).setUp()
        self.useFixture(FeatureFixture({CHARM_RECIPE_ALLOW_CREATE: "on"}))

    def test_implements_interfaces(self):
        # CharmRecipe implements ICharmRecipe.
        recipe = self.factory.makeCharmRecipe()
        with admin_logged_in():
            self.assertProvides(recipe, ICharmRecipe)

    def test___repr__(self):
        # CharmRecipe objects have an informative __repr__.
        recipe = self.factory.makeCharmRecipe()
        self.assertEqual(
            "<CharmRecipe ~%s/%s/+charm/%s>" % (
                recipe.owner.name, recipe.project.name, recipe.name),
            repr(recipe))

    def test_initial_date_last_modified(self):
        # The initial value of date_last_modified is date_created.
        recipe = self.factory.makeCharmRecipe(date_created=ONE_DAY_AGO)
        self.assertEqual(recipe.date_created, recipe.date_last_modified)

    def test_modifiedevent_sets_date_last_modified(self):
        # When a CharmRecipe receives an object modified event, the last
        # modified date is set to UTC_NOW.
        recipe = self.factory.makeCharmRecipe(date_created=ONE_DAY_AGO)
        with notify_modified(removeSecurityProxy(recipe), ["name"]):
            pass
        self.assertSqlAttributeEqualsDate(
            recipe, "date_last_modified", UTC_NOW)

    def test__default_distribution_default(self):
        # If the CHARM_RECIPE_BUILD_DISTRIBUTION feature rule is not set, we
        # default to Ubuntu.
        recipe = self.factory.makeCharmRecipe()
        self.assertEqual(
            "ubuntu", removeSecurityProxy(recipe)._default_distribution.name)

    def test__default_distribution_feature_rule(self):
        # If the CHARM_RECIPE_BUILD_DISTRIBUTION feature rule is set, we
        # default to the distribution with the given name.
        distro_name = "mydistro"
        distribution = self.factory.makeDistribution(name=distro_name)
        recipe = self.factory.makeCharmRecipe()
        with FeatureFixture({CHARM_RECIPE_BUILD_DISTRIBUTION: distro_name}):
            self.assertEqual(
                distribution,
                removeSecurityProxy(recipe)._default_distribution)

    def test__default_distribution_feature_rule_nonexistent(self):
        # If we mistakenly set the rule to a non-existent distribution,
        # things break explicitly.
        recipe = self.factory.makeCharmRecipe()
        with FeatureFixture({CHARM_RECIPE_BUILD_DISTRIBUTION: "nonexistent"}):
            expected_msg = (
                "'nonexistent' is not a valid value for feature rule '%s'" %
                CHARM_RECIPE_BUILD_DISTRIBUTION)
            self.assertRaisesWithContent(
                ValueError, expected_msg,
                getattr, removeSecurityProxy(recipe), "_default_distribution")

    def test__default_distro_series_feature_rule(self):
        # If the appropriate per-distribution feature rule is set, we
        # default to the named distro series.
        distro_name = "mydistro"
        distribution = self.factory.makeDistribution(name=distro_name)
        distro_series_name = "myseries"
        distro_series = self.factory.makeDistroSeries(
            distribution=distribution, name=distro_series_name)
        self.factory.makeDistroSeries(distribution=distribution)
        recipe = self.factory.makeCharmRecipe()
        with FeatureFixture({
                CHARM_RECIPE_BUILD_DISTRIBUTION: distro_name,
                "charm.default_build_series.%s" % distro_name: (
                    distro_series_name),
                }):
            self.assertEqual(
                distro_series,
                removeSecurityProxy(recipe)._default_distro_series)

    def test__default_distro_series_no_feature_rule(self):
        # If the appropriate per-distribution feature rule is not set, we
        # default to the distribution's current series.
        distro_name = "mydistro"
        distribution = self.factory.makeDistribution(name=distro_name)
        self.factory.makeDistroSeries(
            distribution=distribution, status=SeriesStatus.SUPPORTED)
        current_series = self.factory.makeDistroSeries(
            distribution=distribution, status=SeriesStatus.DEVELOPMENT)
        recipe = self.factory.makeCharmRecipe()
        with FeatureFixture({CHARM_RECIPE_BUILD_DISTRIBUTION: distro_name}):
            self.assertEqual(
                current_series,
                removeSecurityProxy(recipe)._default_distro_series)

    def makeBuildableDistroArchSeries(self, architecturetag=None,
                                      processor=None,
                                      supports_virtualized=True,
                                      supports_nonvirtualized=True, **kwargs):
        if architecturetag is None:
            architecturetag = self.factory.getUniqueUnicode("arch")
        if processor is None:
            try:
                processor = getUtility(IProcessorSet).getByName(
                    architecturetag)
            except ProcessorNotFound:
                processor = self.factory.makeProcessor(
                    name=architecturetag,
                    supports_virtualized=supports_virtualized,
                    supports_nonvirtualized=supports_nonvirtualized)
        das = self.factory.makeDistroArchSeries(
            architecturetag=architecturetag, processor=processor, **kwargs)
        fake_chroot = self.factory.makeLibraryFileAlias(
            filename="fake_chroot.tar.gz", db_only=True)
        das.addOrUpdateChroot(fake_chroot)
        return das

    def test_requestBuild(self):
        # requestBuild creates a new CharmRecipeBuild.
        recipe = self.factory.makeCharmRecipe()
        das = self.makeBuildableDistroArchSeries()
        build_request = self.factory.makeCharmRecipeBuildRequest(recipe=recipe)
        build = recipe.requestBuild(build_request, das)
        self.assertTrue(ICharmRecipeBuild.providedBy(build))
        self.assertThat(build, MatchesStructure(
            requester=Equals(recipe.owner.teamowner),
            distro_arch_series=Equals(das),
            channels=Is(None),
            status=Equals(BuildStatus.NEEDSBUILD),
            ))
        store = Store.of(build)
        store.flush()
        build_queue = store.find(
            BuildQueue,
            BuildQueue._build_farm_job_id ==
                removeSecurityProxy(build).build_farm_job_id).one()
        self.assertProvides(build_queue, IBuildQueue)
        self.assertEqual(recipe.require_virtualized, build_queue.virtualized)
        self.assertEqual(BuildQueueStatus.WAITING, build_queue.status)

    def test_requestBuild_score(self):
        # Build requests have a relatively low queue score (2510).
        recipe = self.factory.makeCharmRecipe()
        das = self.makeBuildableDistroArchSeries()
        build_request = self.factory.makeCharmRecipeBuildRequest(recipe=recipe)
        build = recipe.requestBuild(build_request, das)
        queue_record = build.buildqueue_record
        queue_record.score()
        self.assertEqual(2510, queue_record.lastscore)

    def test_requestBuild_channels(self):
        # requestBuild can select non-default channels.
        recipe = self.factory.makeCharmRecipe()
        das = self.makeBuildableDistroArchSeries()
        build_request = self.factory.makeCharmRecipeBuildRequest(recipe=recipe)
        build = recipe.requestBuild(
            build_request, das, channels={"charmcraft": "edge"})
        self.assertEqual({"charmcraft": "edge"}, build.channels)

    def test_requestBuild_rejects_repeats(self):
        # requestBuild refuses if there is already a pending build.
        recipe = self.factory.makeCharmRecipe()
        distro_series = self.factory.makeDistroSeries()
        arches = [
            self.makeBuildableDistroArchSeries(distroseries=distro_series)
            for _ in range(2)]
        build_request = self.factory.makeCharmRecipeBuildRequest(recipe=recipe)
        old_build = recipe.requestBuild(build_request, arches[0])
        self.assertRaises(
            CharmRecipeBuildAlreadyPending, recipe.requestBuild,
            build_request, arches[0])
        # We can build for a different distroarchseries.
        recipe.requestBuild(build_request, arches[1])
        # channels=None and channels={} are treated as equivalent, but
        # anything else allows a new build.
        self.assertRaises(
            CharmRecipeBuildAlreadyPending, recipe.requestBuild,
            build_request, arches[0], channels={})
        recipe.requestBuild(
            build_request, arches[0], channels={"core": "edge"})
        self.assertRaises(
            CharmRecipeBuildAlreadyPending, recipe.requestBuild,
            build_request, arches[0], channels={"core": "edge"})
        # Changing the status of the old build allows a new build.
        old_build.updateStatus(BuildStatus.BUILDING)
        old_build.updateStatus(BuildStatus.FULLYBUILT)
        recipe.requestBuild(build_request, arches[0])

    def test_requestBuild_virtualization(self):
        # New builds are virtualized if any of the processor or recipe
        # require it.
        recipe = self.factory.makeCharmRecipe()
        distro_series = self.factory.makeDistroSeries()
        dases = {}
        for proc_nonvirt in True, False:
            das = self.makeBuildableDistroArchSeries(
                distroseries=distro_series, supports_virtualized=True,
                supports_nonvirtualized=proc_nonvirt)
            dases[proc_nonvirt] = das
        for proc_nonvirt, recipe_virt, build_virt in (
                (True, False, False),
                (True, True, True),
                (False, False, True),
                (False, True, True),
                ):
            das = dases[proc_nonvirt]
            recipe = self.factory.makeCharmRecipe(
                require_virtualized=recipe_virt)
            build_request = self.factory.makeCharmRecipeBuildRequest(
                recipe=recipe)
            build = recipe.requestBuild(build_request, das)
            self.assertEqual(build_virt, build.virtualized)

    def test_requestBuild_nonvirtualized(self):
        # A non-virtualized processor can build a charm recipe iff the
        # recipe has require_virtualized set to False.
        recipe = self.factory.makeCharmRecipe()
        distro_series = self.factory.makeDistroSeries()
        das = self.makeBuildableDistroArchSeries(
            distroseries=distro_series, supports_virtualized=False,
            supports_nonvirtualized=True)
        build_request = self.factory.makeCharmRecipeBuildRequest(recipe=recipe)
        self.assertRaises(
            CharmRecipeBuildDisallowedArchitecture, recipe.requestBuild,
            build_request, das)
        with admin_logged_in():
            recipe.require_virtualized = False
        recipe.requestBuild(build_request, das)

    def test_requestBuilds(self):
        # requestBuilds schedules a job and returns a corresponding
        # CharmRecipeBuildRequest.
        recipe = self.factory.makeCharmRecipe()
        now = get_transaction_timestamp(IStore(recipe))
        with person_logged_in(recipe.owner.teamowner):
            request = recipe.requestBuilds(recipe.owner.teamowner)
        self.assertThat(request, MatchesStructure(
            date_requested=Equals(now),
            date_finished=Is(None),
            recipe=Equals(recipe),
            status=Equals(CharmRecipeBuildRequestStatus.PENDING),
            error_message=Is(None),
            channels=Is(None),
            architectures=Is(None)))
        [job] = getUtility(ICharmRecipeRequestBuildsJobSource).iterReady()
        self.assertThat(job, MatchesStructure(
            job_id=Equals(request.id),
            job=MatchesStructure.byEquality(status=JobStatus.WAITING),
            recipe=Equals(recipe),
            requester=Equals(recipe.owner.teamowner),
            channels=Is(None),
            architectures=Is(None)))

    def test_requestBuilds_with_channels(self):
        # If asked to build using particular snap channels, requestBuilds
        # passes those through to the job.
        recipe = self.factory.makeCharmRecipe()
        now = get_transaction_timestamp(IStore(recipe))
        with person_logged_in(recipe.owner.teamowner):
            request = recipe.requestBuilds(
                recipe.owner.teamowner, channels={"charmcraft": "edge"})
        self.assertThat(request, MatchesStructure(
            date_requested=Equals(now),
            date_finished=Is(None),
            recipe=Equals(recipe),
            status=Equals(CharmRecipeBuildRequestStatus.PENDING),
            error_message=Is(None),
            channels=MatchesDict({"charmcraft": Equals("edge")}),
            architectures=Is(None)))
        [job] = getUtility(ICharmRecipeRequestBuildsJobSource).iterReady()
        self.assertThat(job, MatchesStructure(
            job_id=Equals(request.id),
            job=MatchesStructure.byEquality(status=JobStatus.WAITING),
            recipe=Equals(recipe),
            requester=Equals(recipe.owner.teamowner),
            channels=Equals({"charmcraft": "edge"}),
            architectures=Is(None)))

    def test_requestBuilds_with_architectures(self):
        # If asked to build for particular architectures, requestBuilds
        # passes those through to the job.
        recipe = self.factory.makeCharmRecipe()
        now = get_transaction_timestamp(IStore(recipe))
        with person_logged_in(recipe.owner.teamowner):
            request = recipe.requestBuilds(
                recipe.owner.teamowner, architectures={"amd64", "i386"})
        self.assertThat(request, MatchesStructure(
            date_requested=Equals(now),
            date_finished=Is(None),
            recipe=Equals(recipe),
            status=Equals(CharmRecipeBuildRequestStatus.PENDING),
            error_message=Is(None),
            channels=Is(None),
            architectures=MatchesSetwise(Equals("amd64"), Equals("i386"))))
        [job] = getUtility(ICharmRecipeRequestBuildsJobSource).iterReady()
        self.assertThat(job, MatchesStructure(
            job_id=Equals(request.id),
            job=MatchesStructure.byEquality(status=JobStatus.WAITING),
            recipe=Equals(recipe),
            requester=Equals(recipe.owner.teamowner),
            channels=Is(None),
            architectures=MatchesSetwise(Equals("amd64"), Equals("i386"))))

    def makeRequestBuildsJob(self, distro_series_version, arch_tags,
                             git_ref=None):
        recipe = self.factory.makeCharmRecipe(git_ref=git_ref)
        distro_series = self.factory.makeDistroSeries(
            distribution=getUtility(ILaunchpadCelebrities).ubuntu,
            version=distro_series_version)
        for arch_tag in arch_tags:
            self.makeBuildableDistroArchSeries(
                distroseries=distro_series, architecturetag=arch_tag)
        return getUtility(ICharmRecipeRequestBuildsJobSource).create(
            recipe, recipe.owner.teamowner, {"charmcraft": "edge"})

    def assertRequestedBuildsMatch(self, builds, job, distro_series_version,
                                   arch_tags, channels):
        self.assertThat(builds, MatchesSetwise(
            *(MatchesStructure(
                requester=Equals(job.requester),
                recipe=Equals(job.recipe),
                distro_arch_series=MatchesStructure(
                    distroseries=MatchesStructure.byEquality(
                        version=distro_series_version),
                    architecturetag=Equals(arch_tag)),
                channels=Equals(channels))
              for arch_tag in arch_tags)))

    def test_requestBuildsFromJob_restricts_explicit_list(self):
        # requestBuildsFromJob limits builds targeted at an explicit list of
        # architectures to those allowed for the recipe.
        self.useFixture(GitHostingFixture(blob=dedent("""\
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
            """)))
        job = self.makeRequestBuildsJob("20.04", ["sparc", "avr", "mips64el"])
        self.assertEqual(
            get_transaction_timestamp(IStore(job.recipe)), job.date_created)
        transaction.commit()
        with person_logged_in(job.requester):
            builds = job.recipe.requestBuildsFromJob(
                job.build_request, channels=removeSecurityProxy(job.channels))
        self.assertRequestedBuildsMatch(
            builds, job, "20.04", ["sparc", "avr"], job.channels)

    def test_requestBuildsFromJob_no_explicit_bases(self):
        # If the recipe doesn't specify any bases, requestBuildsFromJob
        # requests builds for all configured architectures for the default
        # series.
        self.useFixture(FeatureFixture({
            CHARM_RECIPE_ALLOW_CREATE: "on",
            CHARM_RECIPE_BUILD_DISTRIBUTION: "ubuntu",
            "charm.default_build_series.ubuntu": "20.04",
            }))
        self.useFixture(GitHostingFixture(blob="name: foo\n"))
        old_distro_series = self.factory.makeDistroSeries(
            distribution=getUtility(ILaunchpadCelebrities).ubuntu,
            version="18.04")
        for arch_tag in ("mips64el", "riscv64"):
            self.makeBuildableDistroArchSeries(
                distroseries=old_distro_series, architecturetag=arch_tag)
        job = self.makeRequestBuildsJob("20.04", ["mips64el", "riscv64"])
        self.assertEqual(
            get_transaction_timestamp(IStore(job.recipe)), job.date_created)
        transaction.commit()
        with person_logged_in(job.requester):
            builds = job.recipe.requestBuildsFromJob(
                job.build_request, channels=removeSecurityProxy(job.channels))
        self.assertRequestedBuildsMatch(
            builds, job, "20.04", ["mips64el", "riscv64"], job.channels)

    def test_requestBuildsFromJob_architectures_parameter(self):
        # If an explicit set of architectures was given as a parameter,
        # requestBuildsFromJob intersects those with any other constraints
        # when requesting builds.
        self.useFixture(GitHostingFixture(blob="name: foo\n"))
        job = self.makeRequestBuildsJob(
            "20.04", ["avr", "mips64el", "riscv64"])
        self.assertEqual(
            get_transaction_timestamp(IStore(job.recipe)), job.date_created)
        transaction.commit()
        with person_logged_in(job.requester):
            builds = job.recipe.requestBuildsFromJob(
                job.build_request, channels=removeSecurityProxy(job.channels),
                architectures={"avr", "riscv64"})
        self.assertRequestedBuildsMatch(
            builds, job, "20.04", ["avr", "riscv64"], job.channels)

    def test_delete_without_builds(self):
        # A charm recipe with no builds can be deleted.
        owner = self.factory.makePerson()
        project = self.factory.makeProduct()
        recipe = self.factory.makeCharmRecipe(
            registrant=owner, owner=owner, project=project, name="condemned")
        self.assertIsNotNone(
            getUtility(ICharmRecipeSet).getByName(owner, project, "condemned"))
        with person_logged_in(recipe.owner):
            recipe.destroySelf()
        self.assertIsNone(
            getUtility(ICharmRecipeSet).getByName(owner, project, "condemned"))


class TestCharmRecipeSet(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestCharmRecipeSet, self).setUp()
        self.useFixture(FeatureFixture({CHARM_RECIPE_ALLOW_CREATE: "on"}))

    def test_class_implements_interfaces(self):
        # The CharmRecipeSet class implements ICharmRecipeSet.
        self.assertProvides(getUtility(ICharmRecipeSet), ICharmRecipeSet)

    def makeCharmRecipeComponents(self, git_ref=None):
        """Return a dict of values that can be used to make a charm recipe.

        Suggested use: provide as kwargs to ICharmRecipeSet.new.

        :param git_ref: An `IGitRef`, or None.
        """
        registrant = self.factory.makePerson()
        components = {
            "registrant": registrant,
            "owner": self.factory.makeTeam(owner=registrant),
            "project": self.factory.makeProduct(),
            "name": self.factory.getUniqueUnicode("charm-name"),
            }
        if git_ref is None:
            git_ref = self.factory.makeGitRefs()[0]
        components["git_ref"] = git_ref
        return components

    def test_creation_git(self):
        # The metadata entries supplied when a charm recipe is created for a
        # Git branch are present on the new object.
        [ref] = self.factory.makeGitRefs()
        components = self.makeCharmRecipeComponents(git_ref=ref)
        recipe = getUtility(ICharmRecipeSet).new(**components)
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
        # Attempting to create a charm recipe without a Git repository
        # fails.
        registrant = self.factory.makePerson()
        self.assertRaises(
            NoSourceForCharmRecipe, getUtility(ICharmRecipeSet).new,
            registrant, registrant, self.factory.makeProduct(),
            self.factory.getUniqueUnicode("charm-name"))

    def test_getByName(self):
        owner = self.factory.makePerson()
        project = self.factory.makeProduct()
        project_recipe = self.factory.makeCharmRecipe(
            registrant=owner, owner=owner, project=project, name="proj-charm")
        self.factory.makeCharmRecipe(
            registrant=owner, owner=owner, name="proj-charm")

        self.assertEqual(
            project_recipe,
            getUtility(ICharmRecipeSet).getByName(
                owner, project, "proj-charm"))

    def test_findByPerson(self):
        # ICharmRecipeSet.findByPerson returns all charm recipes with the
        # given owner or based on repositories with the given owner.
        owners = [self.factory.makePerson() for i in range(2)]
        recipes = []
        for owner in owners:
            recipes.append(self.factory.makeCharmRecipe(
                registrant=owner, owner=owner))
            [ref] = self.factory.makeGitRefs(owner=owner)
            recipes.append(self.factory.makeCharmRecipe(git_ref=ref))
        recipe_set = getUtility(ICharmRecipeSet)
        self.assertContentEqual(
            recipes[:2], recipe_set.findByPerson(owners[0]))
        self.assertContentEqual(
            recipes[2:], recipe_set.findByPerson(owners[1]))

    def test_findByProject(self):
        # ICharmRecipeSet.findByProject returns all charm recipes based on
        # repositories for the given project, and charm recipes associated
        # directly with the project.
        projects = [self.factory.makeProduct() for i in range(2)]
        recipes = []
        for project in projects:
            [ref] = self.factory.makeGitRefs(target=project)
            recipes.append(self.factory.makeCharmRecipe(git_ref=ref))
            recipes.append(self.factory.makeCharmRecipe(project=project))
        [ref] = self.factory.makeGitRefs(target=None)
        recipes.append(self.factory.makeCharmRecipe(git_ref=ref))
        recipe_set = getUtility(ICharmRecipeSet)
        self.assertContentEqual(
            recipes[:2], recipe_set.findByProject(projects[0]))
        self.assertContentEqual(
            recipes[2:4], recipe_set.findByProject(projects[1]))

    def test_findByGitRepository(self):
        # ICharmRecipeSet.findByGitRepository returns all charm recipes with
        # the given Git repository.
        repositories = [self.factory.makeGitRepository() for i in range(2)]
        recipes = []
        for repository in repositories:
            for i in range(2):
                [ref] = self.factory.makeGitRefs(repository=repository)
                recipes.append(self.factory.makeCharmRecipe(git_ref=ref))
        recipe_set = getUtility(ICharmRecipeSet)
        self.assertContentEqual(
            recipes[:2], recipe_set.findByGitRepository(repositories[0]))
        self.assertContentEqual(
            recipes[2:], recipe_set.findByGitRepository(repositories[1]))

    def test_findByGitRepository_paths(self):
        # ICharmRecipeSet.findByGitRepository can restrict by reference
        # paths.
        repositories = [self.factory.makeGitRepository() for i in range(2)]
        recipes = []
        for repository in repositories:
            for i in range(3):
                [ref] = self.factory.makeGitRefs(repository=repository)
                recipes.append(self.factory.makeCharmRecipe(git_ref=ref))
        recipe_set = getUtility(ICharmRecipeSet)
        self.assertContentEqual(
            [], recipe_set.findByGitRepository(repositories[0], paths=[]))
        self.assertContentEqual(
            [recipes[0]],
            recipe_set.findByGitRepository(
                repositories[0], paths=[recipes[0].git_ref.path]))
        self.assertContentEqual(
            recipes[:2],
            recipe_set.findByGitRepository(
                repositories[0],
                paths=[recipes[0].git_ref.path, recipes[1].git_ref.path]))

    def test_findByGitRef(self):
        # ICharmRecipeSet.findByGitRef returns all charm recipes with the
        # given Git reference.
        repositories = [self.factory.makeGitRepository() for i in range(2)]
        refs = []
        recipes = []
        for repository in repositories:
            refs.extend(self.factory.makeGitRefs(
                paths=["refs/heads/master", "refs/heads/other"]))
            recipes.append(self.factory.makeCharmRecipe(git_ref=refs[-2]))
            recipes.append(self.factory.makeCharmRecipe(git_ref=refs[-1]))
        recipe_set = getUtility(ICharmRecipeSet)
        for ref, recipe in zip(refs, recipes):
            self.assertContentEqual([recipe], recipe_set.findByGitRef(ref))

    def test_findByContext(self):
        # ICharmRecipeSet.findByContext returns all charm recipes with the
        # given context.
        person = self.factory.makePerson()
        project = self.factory.makeProduct()
        repository = self.factory.makeGitRepository(
            owner=person, target=project)
        refs = self.factory.makeGitRefs(
            repository=repository,
            paths=["refs/heads/master", "refs/heads/other"])
        other_repository = self.factory.makeGitRepository()
        other_refs = self.factory.makeGitRefs(
            repository=other_repository,
            paths=["refs/heads/master", "refs/heads/other"])
        recipes = []
        recipes.append(self.factory.makeCharmRecipe(git_ref=refs[0]))
        recipes.append(self.factory.makeCharmRecipe(git_ref=refs[1]))
        recipes.append(self.factory.makeCharmRecipe(
            registrant=person, owner=person, git_ref=other_refs[0]))
        recipes.append(self.factory.makeCharmRecipe(
            project=project, git_ref=other_refs[1]))
        recipe_set = getUtility(ICharmRecipeSet)
        self.assertContentEqual(recipes[:3], recipe_set.findByContext(person))
        self.assertContentEqual(
            [recipes[0], recipes[1], recipes[3]],
            recipe_set.findByContext(project))
        self.assertContentEqual(
            recipes[:2], recipe_set.findByContext(repository))
        self.assertContentEqual(
            [recipes[0]], recipe_set.findByContext(refs[0]))
        self.assertRaises(
            BadCharmRecipeSearchContext, recipe_set.findByContext,
            self.factory.makeDistribution())

    def test_detachFromGitRepository(self):
        # ICharmRecipeSet.detachFromGitRepository clears the given Git
        # repository from all charm recipes.
        repositories = [self.factory.makeGitRepository() for i in range(2)]
        recipes = []
        paths = []
        refs = []
        for repository in repositories:
            for i in range(2):
                [ref] = self.factory.makeGitRefs(repository=repository)
                paths.append(ref.path)
                refs.append(ref)
                recipes.append(self.factory.makeCharmRecipe(
                    git_ref=ref, date_created=ONE_DAY_AGO))
        getUtility(ICharmRecipeSet).detachFromGitRepository(repositories[0])
        self.assertEqual(
            [None, None, repositories[1], repositories[1]],
            [recipe.git_repository for recipe in recipes])
        self.assertEqual(
            [None, None, paths[2], paths[3]],
            [recipe.git_path for recipe in recipes])
        self.assertEqual(
            [None, None, refs[2], refs[3]],
            [recipe.git_ref for recipe in recipes])
        for recipe in recipes[:2]:
            self.assertSqlAttributeEqualsDate(
                recipe, "date_last_modified", UTC_NOW)
