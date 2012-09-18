# Copyright 2009-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

from functools import partial

import soupmatchers
from storm.locals import Store
from testtools.matchers import (
    Equals,
    MatchesAll,
    )
import transaction
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.buildmaster.enums import (
    BuildFarmJobType,
    BuildStatus,
    )
from lp.buildmaster.interfaces.buildfarmjob import (
    IBuildFarmJobSource,
    InconsistentBuildFarmJobError,
    )
from lp.registry.interfaces.person import IPersonSet
from lp.services.database.sqlbase import flush_database_updates
from lp.services.webapp.servers import LaunchpadTestRequest
from lp.soyuz.browser.build import getSpecificJobs
from lp.soyuz.browser.builder import BuilderEditView
from lp.testing import (
    celebrity_logged_in,
    login,
    record_two_runs,
    StormStatementRecorder,
    TestCaseWithFactory,
    )
from lp.testing.fakemethod import FakeMethod
from lp.testing.layers import LaunchpadFunctionalLayer
from lp.testing.matchers import HasQueryCount
from lp.testing.sampledata import ADMIN_EMAIL
from lp.testing.views import create_initialized_view
from lp.translations.interfaces.translationtemplatesbuild import (
    ITranslationTemplatesBuildSource,
    )


class TestBuilderEditView(TestCaseWithFactory):

    layer = LaunchpadFunctionalLayer

    def setUp(self):
        super(TestBuilderEditView, self).setUp()
        # Login as an admin to ensure access to the view's context
        # object.
        login(ADMIN_EMAIL)
        self.builder = removeSecurityProxy(self.factory.makeBuilder())

    def initialize_view(self):
        form = {
            "field.manual": "on",
            "field.actions.update": "Change",
            }
        request = LaunchpadTestRequest(method="POST", form=form)
        view = BuilderEditView(self.builder, request)
        return view

    def test_posting_form_doesnt_call_slave_xmlrpc(self):
        # Posting the +edit for should not call isAvailable, which
        # would do xmlrpc to a slave builder and is explicitly forbidden
        # in a webapp process.
        view = self.initialize_view()

        # Stub out the slaveStatusSentence() method with a fake one that
        # records if it's been called.
        view.context.slaveStatusSentence = FakeMethod(result=[0])

        view.initialize()

        # If the dummy slaveStatusSentence() was called the call count
        # would not be zero.
        self.assertTrue(view.context.slaveStatusSentence.call_count == 0)


class TestgetSpecificJobs(TestCaseWithFactory):

    layer = LaunchpadFunctionalLayer

    def createTranslationTemplateBuild(self):
        build_farm_job_source = getUtility(IBuildFarmJobSource)
        build_farm_job = build_farm_job_source.new(
            BuildFarmJobType.TRANSLATIONTEMPLATESBUILD)
        source = getUtility(ITranslationTemplatesBuildSource)
        branch = self.factory.makeBranch()
        return source.create(build_farm_job, branch)

    def createSourcePackageRecipeBuild(self):
        sprb = self.factory.makeSourcePackageRecipeBuild()
        Store.of(sprb).flush()
        return sprb

    def createBinaryPackageBuild(self):
        build = self.factory.makeBinaryPackageBuild()
        return build

    def createBuilds(self):
        builds = []
        for i in xrange(2):
            builds.append(self.createBinaryPackageBuild())
            builds.append(self.createTranslationTemplateBuild())
            builds.append(self.createSourcePackageRecipeBuild())
        return builds

    def test_getSpecificJobs(self):
        builds = self.createBuilds()
        specific_jobs = getSpecificJobs(
            [build.build_farm_job for build in builds])
        self.assertContentEqual(
            builds, specific_jobs)

    def test_getSpecificJobs_preserves_order(self):
        builds = self.createBuilds()
        specific_jobs = getSpecificJobs(
            [build.build_farm_job for build in builds])
        self.assertEqual(
            [(build.id, build.__class__) for build in builds],
            [(job.id, job.__class__) for job in specific_jobs])

    def test_getSpecificJobs_duplicated_builds(self):
        builds = self.createBuilds()
        duplicated_builds = builds + builds
        specific_jobs = getSpecificJobs(
            [build.build_farm_job for build in duplicated_builds])
        self.assertEqual(len(duplicated_builds), len(specific_jobs))

    def test_getSpecificJobs_empty(self):
        self.assertContentEqual([], getSpecificJobs([]))

    def test_getSpecificJobs_sql_queries_count(self):
        # getSpecificJobs issues a constant number of queries.
        builds = self.createBuilds()
        build_farm_jobs = [build.build_farm_job for build in builds]
        flush_database_updates()
        with StormStatementRecorder() as recorder:
            getSpecificJobs(build_farm_jobs)
        builds2 = self.createBuilds()
        build_farm_jobs.extend([build.build_farm_job for build in builds2])
        flush_database_updates()
        with StormStatementRecorder() as recorder2:
            getSpecificJobs(build_farm_jobs)
        self.assertThat(recorder, HasQueryCount(Equals(recorder2.count)))

    def test_getSpecificJobs_no_specific_job(self):
        build_farm_job_source = getUtility(IBuildFarmJobSource)
        build_farm_job = build_farm_job_source.new(
            BuildFarmJobType.TRANSLATIONTEMPLATESBUILD)
        flush_database_updates()
        self.assertRaises(
            InconsistentBuildFarmJobError,
            getSpecificJobs, [build_farm_job])


class BuildCreationMixin(object):

    def markAsBuilt(self, build):
        lfa = self.factory.makeLibraryFileAlias()
        naked_build = removeSecurityProxy(build)
        naked_build.log = lfa
        naked_build.date_started = self.factory.getUniqueDate()
        naked_build.date_finished = self.factory.getUniqueDate()
        naked_build.status = BuildStatus.FULLYBUILT
        transaction.commit()

    def createTranslationTemplateBuildWithBuilder(self, builder=None):
        if builder is None:
            builder = self.factory.makeBuilder()
        build_farm_job_source = getUtility(IBuildFarmJobSource)
        build_farm_job = build_farm_job_source.new(
            BuildFarmJobType.TRANSLATIONTEMPLATESBUILD)
        source = getUtility(ITranslationTemplatesBuildSource)
        branch = self.factory.makeBranch()
        build = source.create(build_farm_job, branch)
        removeSecurityProxy(build).builder = builder
        self.markAsBuilt(build)
        return build

    def createRecipeBuildWithBuilder(self, private_branch=False,
                                     builder=None):
        if builder is None:
            builder = self.factory.makeBuilder()
        branch2 = self.factory.makeAnyBranch()
        branch1 = self.factory.makeAnyBranch()
        build = self.factory.makeSourcePackageRecipeBuild(
            recipe=self.factory.makeSourcePackageRecipe(
                branches=[branch1, branch2]))
        if private_branch:
            with celebrity_logged_in('admin'):
                branch1.setPrivate(
                    True, getUtility(IPersonSet).getByEmail(ADMIN_EMAIL))
        Store.of(build).flush()
        removeSecurityProxy(build).builder = builder
        self.markAsBuilt(build)
        return build

    def createBinaryPackageBuild(self, in_ppa=False, builder=None):
        if builder is None:
            builder = self.factory.makeBuilder()
        archive = None
        if in_ppa:
            archive = self.factory.makeArchive()
        build = self.factory.makeBinaryPackageBuild(archive=archive)
        naked_build = removeSecurityProxy(build)
        naked_build.builder = builder
        naked_build.date_started = self.factory.getUniqueDate()
        naked_build.date_finished = self.factory.getUniqueDate()
        self.markAsBuilt(build)
        return build


class TestBuilderHistoryView(TestCaseWithFactory, BuildCreationMixin):

    layer = LaunchpadFunctionalLayer

    nb_objects = 2

    def setUp(self):
        super(TestBuilderHistoryView, self).setUp()
        self.builder = self.factory.makeBuilder()

    def test_build_history_queries_count_view_recipe_builds(self):
        # The builder's history view creation (i.e. the call to
        # view.setupBuildList) issues a constant number of queries
        # when recipe builds are displayed.
        def builder_history_render():
            create_initialized_view(self.builder, '+history').render()
        recorder1, recorder2 = record_two_runs(
            builder_history_render,
            partial(self.createRecipeBuildWithBuilder, builder=self.builder),
            self.nb_objects)

        # XXX: rvb 2011-11-14: The only query remaining is the one that
        # results from a call to
        # sourcepackagerecipebuild.buildqueue_record for each recipe build.
        self.assertThat(
            recorder2,
            HasQueryCount(Equals(recorder1.count + 1 * self.nb_objects)))

    def test_build_history_queries_count_binary_package_builds(self):
        # Rendering to builder's history issues a constant number of queries
        # when binary builds are displayed.
        def builder_history_render():
            create_initialized_view(self.builder, '+history').render()
        recorder1, recorder2 = record_two_runs(
            builder_history_render,
            partial(self.createBinaryPackageBuild, builder=self.builder),
            self.nb_objects)

        self.assertThat(recorder2, HasQueryCount(Equals(recorder1.count)))

    def test_build_history_queries_count_binary_package_builds_in_ppa(self):
        # Rendering to builder's history issues a constant number of queries
        # when ppa binary builds are displayed.
        def builder_history_render():
            create_initialized_view(self.builder, '+history').render()
        createBinaryPackageBuildInPPA = partial(
            self.createBinaryPackageBuild, in_ppa=True, builder=self.builder)
        recorder1, recorder2 = record_two_runs(
            builder_history_render, createBinaryPackageBuildInPPA,
            self.nb_objects)

        self.assertThat(recorder2, HasQueryCount(Equals(recorder1.count)))

    def test_build_history_queries_count_translation_template_builds(self):
        # Rendering to builder's history issues a constant number of queries
        # when translation template builds are displayed.
        def builder_history_render():
            create_initialized_view(self.builder, '+history').render()
        recorder1, recorder2 = record_two_runs(
            builder_history_render,
            partial(
                self.createTranslationTemplateBuildWithBuilder,
                builder=self.builder),
            self.nb_objects)

        self.assertThat(recorder2, HasQueryCount(Equals(recorder1.count)))

    def test_build_history_private_build_view(self):
        self.createRecipeBuildWithBuilder(builder=self.builder)
        self.createRecipeBuildWithBuilder(
            private_branch=True, builder=self.builder)
        view = create_initialized_view(self.builder, '+history')
        view.setupBuildList()

        self.assertIn(None, view.complete_builds)

    def test_build_history_private_build_display(self):
        self.createRecipeBuildWithBuilder(builder=self.builder)
        self.createRecipeBuildWithBuilder(
            private_branch=True, builder=self.builder)
        view = create_initialized_view(self.builder, '+history')
        private_build_icon_matcher = soupmatchers.HTMLContains(
            soupmatchers.Tag(
                'Private build icon', 'img', attrs={'src': '/@@/private'}))
        private_build_matcher = soupmatchers.HTMLContains(
            soupmatchers.Tag('Private build', 'td', text='Private job'))

        self.assertThat(
            view.render(),
            MatchesAll(private_build_matcher, private_build_icon_matcher))
        
    def test_build_history_with_ttbj_on_deleted_branch(self):
        build = self.createTranslationTemplateBuildWithBuilder(
            builder=self.builder)
        removeSecurityProxy(build.branch)._deleteJobs()
        view = create_initialized_view(self.builder, '+history')
        self.assertIn('No build records.', view.render())
