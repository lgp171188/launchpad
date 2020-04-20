# Copyright 2019-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for OCI image building recipe functionality."""

from __future__ import absolute_import, print_function, unicode_literals

import base64
import json

from fixtures import FakeLogger
from nacl.public import PrivateKey
from six import string_types
from storm.exceptions import LostObjectError
from testtools.matchers import (
    ContainsDict,
    Equals,
    MatchesDict,
    MatchesStructure,
    )
import transaction
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.buildmaster.enums import BuildStatus
from lp.buildmaster.interfaces.processor import IProcessorSet
from lp.oci.interfaces.ocirecipe import (
    CannotModifyOCIRecipeProcessor,
    DuplicateOCIRecipeName,
    IOCIRecipe,
    IOCIRecipeSet,
    NoSourceForOCIRecipe,
    NoSuchOCIRecipe,
    OCI_RECIPE_ALLOW_CREATE,
    OCI_RECIPE_WEBHOOKS_FEATURE_FLAG,
    OCIRecipeBuildAlreadyPending,
    OCIRecipeNotOwner,
    )
from lp.oci.interfaces.ocirecipebuild import IOCIRecipeBuildSet
from lp.services.config import config
from lp.services.database.constants import (
    ONE_DAY_AGO,
    UTC_NOW,
    )
from lp.services.database.sqlbase import flush_database_caches
from lp.services.features.testing import FeatureFixture
from lp.services.webapp.interfaces import OAuthPermission
from lp.services.webapp.publisher import canonical_url
from lp.services.webapp.snapshot import notify_modified
from lp.services.webhooks.testing import LogsScheduledWebhooks
from lp.testing import (
    admin_logged_in,
    api_url,
    person_logged_in,
    TestCaseWithFactory,
    )
from lp.testing.dbuser import dbuser
from lp.testing.layers import DatabaseFunctionalLayer
from lp.testing.pages import webservice_for_person


class TestOCIRecipe(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestOCIRecipe, self).setUp()
        self.useFixture(FeatureFixture({OCI_RECIPE_ALLOW_CREATE: 'on'}))

    def test_implements_interface(self):
        target = self.factory.makeOCIRecipe()
        with admin_logged_in():
            self.assertProvides(target, IOCIRecipe)

    def test_initial_date_last_modified(self):
        # The initial value of date_last_modified is date_created.
        recipe = self.factory.makeOCIRecipe(date_created=ONE_DAY_AGO)
        self.assertEqual(recipe.date_created, recipe.date_last_modified)

    def test_modifiedevent_sets_date_last_modified(self):
        # When an OCIRecipe receives an object modified event, the last
        # modified date is set to UTC_NOW.
        recipe = self.factory.makeOCIRecipe(date_created=ONE_DAY_AGO)
        with notify_modified(removeSecurityProxy(recipe), ["name"]):
            pass
        self.assertSqlAttributeEqualsDate(
            recipe, "date_last_modified", UTC_NOW)

    def test_checkRequestBuild(self):
        ocirecipe = removeSecurityProxy(self.factory.makeOCIRecipe())
        unrelated_person = self.factory.makePerson()
        self.assertRaises(
            OCIRecipeNotOwner,
            ocirecipe._checkRequestBuild,
            unrelated_person)

    def test_requestBuild(self):
        ocirecipe = self.factory.makeOCIRecipe()
        oci_arch = self.factory.makeOCIRecipeArch(recipe=ocirecipe)
        build = ocirecipe.requestBuild(ocirecipe.owner, oci_arch)
        self.assertEqual(build.status, BuildStatus.NEEDSBUILD)

    def test_requestBuild_already_exists(self):
        ocirecipe = self.factory.makeOCIRecipe()
        oci_arch = self.factory.makeOCIRecipeArch(recipe=ocirecipe)
        ocirecipe.requestBuild(ocirecipe.owner, oci_arch)

        self.assertRaises(
            OCIRecipeBuildAlreadyPending,
            ocirecipe.requestBuild,
            ocirecipe.owner, oci_arch)

    def test_requestBuild_triggers_webhooks(self):
        # Requesting a build triggers webhooks.
        logger = self.useFixture(FakeLogger())
        with FeatureFixture({OCI_RECIPE_WEBHOOKS_FEATURE_FLAG: "on",
                             OCI_RECIPE_ALLOW_CREATE: 'on'}):
            recipe = self.factory.makeOCIRecipe()
            oci_arch = self.factory.makeOCIRecipeArch(recipe=recipe)
            hook = self.factory.makeWebhook(
                target=recipe, event_types=["oci-recipe:build:0.1"])
            build = recipe.requestBuild(recipe.owner, oci_arch)

        expected_payload = {
            "recipe_build": Equals(
                canonical_url(build, force_local_path=True)),
            "action": Equals("created"),
            "recipe": Equals(canonical_url(recipe, force_local_path=True)),
            "status": Equals("Needs building"),
            'registry_upload_status': Equals('Unscheduled'),
            }
        with person_logged_in(recipe.owner):
            delivery = hook.deliveries.one()
            self.assertThat(
                delivery, MatchesStructure(
                    event_type=Equals("oci-recipe:build:0.1"),
                    payload=MatchesDict(expected_payload)))
            with dbuser(config.IWebhookDeliveryJobSource.dbuser):
                self.assertEqual(
                    "<WebhookDeliveryJob for webhook %d on %r>" % (
                        hook.id, hook.target),
                    repr(delivery))
                self.assertThat(
                    logger.output,
                    LogsScheduledWebhooks([
                        (hook, "oci-recipe:build:0.1",
                         MatchesDict(expected_payload))]))

    def test_destroySelf(self):
        oci_recipe = self.factory.makeOCIRecipe()
        build_ids = []
        for x in range(3):
            build_ids.append(
                self.factory.makeOCIRecipeBuild(recipe=oci_recipe).id)

        with person_logged_in(oci_recipe.owner):
            oci_recipe.destroySelf()
        flush_database_caches()

        for build_id in build_ids:
            self.assertIsNone(getUtility(IOCIRecipeBuildSet).getByID(build_id))

    def test_related_webhooks_deleted(self):
        owner = self.factory.makePerson()
        with FeatureFixture({OCI_RECIPE_WEBHOOKS_FEATURE_FLAG: "on",
                             OCI_RECIPE_ALLOW_CREATE: 'on'}):
            recipe = self.factory.makeOCIRecipe(registrant=owner, owner=owner)
            webhook = self.factory.makeWebhook(target=recipe)
        with person_logged_in(recipe.owner):
            webhook.ping()
            recipe.destroySelf()
            transaction.commit()
            self.assertRaises(LostObjectError, getattr, webhook, "target")

    def test_getBuilds(self):
        # Test the various getBuilds methods.
        oci_recipe = self.factory.makeOCIRecipe()
        builds = [self.factory.makeOCIRecipeBuild(recipe=oci_recipe)
                  for x in range(3)]
        # We want the latest builds first.
        builds.reverse()

        self.assertEqual(builds, list(oci_recipe.builds))
        self.assertEqual([], list(oci_recipe.completed_builds))
        self.assertEqual(builds, list(oci_recipe.pending_builds))

        # Change the status of one of the builds and retest.
        builds[0].updateStatus(BuildStatus.BUILDING)
        builds[0].updateStatus(BuildStatus.FULLYBUILT)
        self.assertEqual(builds, list(oci_recipe.builds))
        self.assertEqual(builds[:1], list(oci_recipe.completed_builds))
        self.assertEqual(builds[1:], list(oci_recipe.pending_builds))

    def test_getBuilds_cancelled_never_started_last(self):
        # A cancelled build that was never even started sorts to the end.
        oci_recipe = self.factory.makeOCIRecipe()
        fullybuilt = self.factory.makeOCIRecipeBuild(recipe=oci_recipe)
        instacancelled = self.factory.makeOCIRecipeBuild(recipe=oci_recipe)
        fullybuilt.updateStatus(BuildStatus.BUILDING)
        fullybuilt.updateStatus(BuildStatus.FULLYBUILT)
        instacancelled.updateStatus(BuildStatus.CANCELLED)
        self.assertEqual([fullybuilt, instacancelled], list(oci_recipe.builds))
        self.assertEqual(
            [fullybuilt, instacancelled], list(oci_recipe.completed_builds))
        self.assertEqual([], list(oci_recipe.pending_builds))

    def test_push_rules(self):
        self.pushConfig(
            "oci",
            registry_secrets_public_key=base64.b64encode(
                bytes(PrivateKey.generate().public_key)).decode("UTF-8"))
        oci_recipe = self.factory.makeOCIRecipe()
        for _ in range(3):
            self.factory.makeOCIPushRule(recipe=oci_recipe)
        # Add some others
        for _ in range(3):
            self.factory.makeOCIPushRule()

        for rule in oci_recipe.push_rules:
            self.assertEqual(rule.recipe, oci_recipe)


class TestOCIRecipeProcessors(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestOCIRecipeProcessors, self).setUp(
            user="foo.bar@canonical.com")
        self.default_procs = [
            getUtility(IProcessorSet).getByName("386"),
            getUtility(IProcessorSet).getByName("amd64")]
        self.unrestricted_procs = (
            self.default_procs + [getUtility(IProcessorSet).getByName("hppa")])
        self.arm = self.factory.makeProcessor(
            name="arm", restricted=True, build_by_default=False)
        self.distroseries = self.factory.makeDistroSeries()
        self.useFixture(FeatureFixture({
            OCI_RECIPE_ALLOW_CREATE: "on",
            "oci.build_series.%s" % self.distroseries.distribution.name:
                self.distroseries.name
            }))

    def test_available_processors(self):
        # Only those processors that are enabled for the recipe's
        # distroseries are available.
        for processor in self.default_procs:
            self.factory.makeDistroArchSeries(
                distroseries=self.distroseries, architecturetag=processor.name,
                processor=processor)
        self.factory.makeDistroArchSeries(
            architecturetag=self.arm.name, processor=self.arm)
        oci_project = self.factory.makeOCIProject(
            pillar=self.distroseries.distribution)
        recipe = self.factory.makeOCIRecipe(oci_project=oci_project)
        self.assertContentEqual(
            self.default_procs, recipe.available_processors)

    def test_new_default_processors(self):
        # OCIRecipeSet.new creates an OCIRecipeArch for each available
        # Processor with build_by_default set.
        new_procs = [
            self.factory.makeProcessor(name="default", build_by_default=True),
            self.factory.makeProcessor(
                name="nondefault", build_by_default=False),
            ]
        owner = self.factory.makePerson()
        for processor in self.unrestricted_procs + [self.arm] + new_procs:
            self.factory.makeDistroArchSeries(
                distroseries=self.distroseries, architecturetag=processor.name,
                processor=processor)
        oci_project = self.factory.makeOCIProject(
            pillar=self.distroseries.distribution)
        recipe = getUtility(IOCIRecipeSet).new(
            name=self.factory.getUniqueUnicode(), registrant=owner,
            owner=owner, oci_project=oci_project,
            git_ref=self.factory.makeGitRefs()[0],
            build_file=self.factory.getUniqueUnicode())
        self.assertContentEqual(
            ["386", "amd64", "hppa", "default"],
            [processor.name for processor in recipe.processors])

    def test_new_override_processors(self):
        # OCIRecipeSet.new can be given a custom set of processors.
        owner = self.factory.makePerson()
        oci_project = self.factory.makeOCIProject(
            pillar=self.distroseries.distribution)
        recipe = getUtility(IOCIRecipeSet).new(
            name=self.factory.getUniqueUnicode(), registrant=owner,
            owner=owner, oci_project=oci_project,
            git_ref=self.factory.makeGitRefs()[0],
            build_file=self.factory.getUniqueUnicode(), processors=[self.arm])
        self.assertContentEqual(
            ["arm"], [processor.name for processor in recipe.processors])

    def test_set(self):
        # The property remembers its value correctly.
        recipe = self.factory.makeOCIRecipe()
        recipe.setProcessors([self.arm])
        self.assertContentEqual([self.arm], recipe.processors)
        recipe.setProcessors(self.unrestricted_procs + [self.arm])
        self.assertContentEqual(
            self.unrestricted_procs + [self.arm], recipe.processors)
        recipe.setProcessors([])
        self.assertContentEqual([], recipe.processors)

    def test_set_non_admin(self):
        """Non-admins can only enable or disable unrestricted processors."""
        recipe = self.factory.makeOCIRecipe()
        recipe.setProcessors(self.default_procs)
        self.assertContentEqual(self.default_procs, recipe.processors)
        with person_logged_in(recipe.owner) as owner:
            # Adding arm is forbidden ...
            self.assertRaises(
                CannotModifyOCIRecipeProcessor, recipe.setProcessors,
                [self.default_procs[0], self.arm],
                check_permissions=True, user=owner)
            # ... but removing amd64 is OK.
            recipe.setProcessors(
                [self.default_procs[0]], check_permissions=True, user=owner)
            self.assertContentEqual([self.default_procs[0]], recipe.processors)
        with admin_logged_in() as admin:
            recipe.setProcessors(
                [self.default_procs[0], self.arm],
                check_permissions=True, user=admin)
            self.assertContentEqual(
                [self.default_procs[0], self.arm], recipe.processors)
        with person_logged_in(recipe.owner) as owner:
            hppa = getUtility(IProcessorSet).getByName("hppa")
            self.assertFalse(hppa.restricted)
            # Adding hppa while removing arm is forbidden ...
            self.assertRaises(
                CannotModifyOCIRecipeProcessor, recipe.setProcessors,
                [self.default_procs[0], hppa],
                check_permissions=True, user=owner)
            # ... but adding hppa while retaining arm is OK.
            recipe.setProcessors(
                [self.default_procs[0], self.arm, hppa],
                check_permissions=True, user=owner)
            self.assertContentEqual(
                [self.default_procs[0], self.arm, hppa], recipe.processors)


class TestOCIRecipeSet(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestOCIRecipeSet, self).setUp()
        self.useFixture(FeatureFixture({OCI_RECIPE_ALLOW_CREATE: 'on'}))

    def test_implements_interface(self):
        target_set = getUtility(IOCIRecipeSet)
        with admin_logged_in():
            self.assertProvides(target_set, IOCIRecipeSet)

    def test_new(self):
        registrant = self.factory.makePerson()
        owner = self.factory.makeTeam(members=[registrant])
        oci_project = self.factory.makeOCIProject()
        [git_ref] = self.factory.makeGitRefs()
        target = getUtility(IOCIRecipeSet).new(
            name='a name',
            registrant=registrant,
            owner=owner,
            oci_project=oci_project,
            git_ref=git_ref,
            description='a description',
            official=False,
            require_virtualized=False,
            build_file='build file')
        self.assertEqual(target.registrant, registrant)
        self.assertEqual(target.owner, owner)
        self.assertEqual(target.oci_project, oci_project)
        self.assertEqual(target.official, False)
        self.assertEqual(target.require_virtualized, False)
        self.assertEqual(target.git_ref, git_ref)

    def test_already_exists(self):
        owner = self.factory.makePerson()
        oci_project = self.factory.makeOCIProject()
        self.factory.makeOCIRecipe(
            owner=owner, registrant=owner, name="already exists",
            oci_project=oci_project)

        self.assertRaises(
            DuplicateOCIRecipeName,
            self.factory.makeOCIRecipe,
            owner=owner,
            registrant=owner,
            name="already exists",
            oci_project=oci_project)

    def test_no_source_git_ref(self):
        owner = self.factory.makePerson()
        oci_project = self.factory.makeOCIProject()
        recipe_set = getUtility(IOCIRecipeSet)
        self.assertRaises(
            NoSourceForOCIRecipe,
            recipe_set.new,
            name="no source",
            registrant=owner,
            owner=owner,
            oci_project=oci_project,
            git_ref=None,
            build_file='build_file')

    def test_no_source_build_file(self):
        owner = self.factory.makePerson()
        oci_project = self.factory.makeOCIProject()
        recipe_set = getUtility(IOCIRecipeSet)
        [git_ref] = self.factory.makeGitRefs()
        self.assertRaises(
            NoSourceForOCIRecipe,
            recipe_set.new,
            name="no source",
            registrant=owner,
            owner=owner,
            oci_project=oci_project,
            git_ref=git_ref,
            build_file=None)

    def test_getByName(self):
        owner = self.factory.makePerson()
        name = "a test recipe"
        oci_project = self.factory.makeOCIProject()
        target = self.factory.makeOCIRecipe(
            owner=owner, registrant=owner, name=name, oci_project=oci_project)

        for _ in range(3):
            self.factory.makeOCIRecipe(oci_project=oci_project)

        result = getUtility(IOCIRecipeSet).getByName(owner, oci_project, name)
        self.assertEqual(target, result)

    def test_getByName_missing(self):
        owner = self.factory.makePerson()
        oci_project = self.factory.makeOCIProject()
        for _ in range(3):
            self.factory.makeOCIRecipe(
                owner=owner, registrant=owner, oci_project=oci_project)
        self.assertRaises(
            NoSuchOCIRecipe,
            getUtility(IOCIRecipeSet).getByName,
            owner=owner,
            oci_project=oci_project,
            name="missing")

    def test_findByGitRepository(self):
        # IOCIRecipeSet.findByGitRepository returns all OCI recipes with the
        # given Git repository.
        repositories = [self.factory.makeGitRepository() for i in range(2)]
        oci_recipes = []
        for repository in repositories:
            for i in range(2):
                [ref] = self.factory.makeGitRefs(repository=repository)
                oci_recipes.append(self.factory.makeOCIRecipe(git_ref=ref))
        oci_recipe_set = getUtility(IOCIRecipeSet)
        self.assertContentEqual(
            oci_recipes[:2], oci_recipe_set.findByGitRepository(
                repositories[0]))
        self.assertContentEqual(
            oci_recipes[2:], oci_recipe_set.findByGitRepository(
                repositories[1]))

    def test_findByGitRepository_paths(self):
        # IOCIRecipeSet.findByGitRepository can restrict by reference paths.
        repositories = [self.factory.makeGitRepository() for i in range(2)]
        oci_recipes = []
        for repository in repositories:
            for i in range(3):
                [ref] = self.factory.makeGitRefs(repository=repository)
                oci_recipes.append(self.factory.makeOCIRecipe(git_ref=ref))
        oci_recipe_set = getUtility(IOCIRecipeSet)
        self.assertContentEqual(
            [], oci_recipe_set.findByGitRepository(repositories[0], paths=[]))
        self.assertContentEqual(
            [oci_recipes[0]],
            oci_recipe_set.findByGitRepository(
                repositories[0], paths=[oci_recipes[0].git_ref.path]))
        self.assertContentEqual(
            oci_recipes[:2],
            oci_recipe_set.findByGitRepository(
                repositories[0],
                paths=[
                    oci_recipes[0].git_ref.path, oci_recipes[1].git_ref.path]))

    def test_detachFromGitRepository(self):
        repositories = [self.factory.makeGitRepository() for i in range(2)]
        oci_recipes = []
        paths = []
        refs = []
        for repository in repositories:
            for i in range(2):
                [ref] = self.factory.makeGitRefs(repository=repository)
                paths.append(ref.path)
                refs.append(ref)
                oci_recipes.append(self.factory.makeOCIRecipe(
                    git_ref=ref, date_created=ONE_DAY_AGO))
        getUtility(IOCIRecipeSet).detachFromGitRepository(repositories[0])
        self.assertEqual(
            [None, None, repositories[1], repositories[1]],
            [oci_recipe.git_repository for oci_recipe in oci_recipes])
        self.assertEqual(
            [None, None, paths[2], paths[3]],
            [oci_recipe.git_path for oci_recipe in oci_recipes])
        self.assertEqual(
            [None, None, refs[2], refs[3]],
            [oci_recipe.git_ref for oci_recipe in oci_recipes])
        for oci_recipe in oci_recipes[:2]:
            self.assertSqlAttributeEqualsDate(
                oci_recipe, "date_last_modified", UTC_NOW)


class TestOCIRecipeWebservice(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestOCIRecipeWebservice, self).setUp()
        self.person = self.factory.makePerson(
            displayname="Test Person")
        self.webservice = webservice_for_person(
            self.person, permission=OAuthPermission.WRITE_PUBLIC,
            default_api_version="devel")
        self.useFixture(FeatureFixture({OCI_RECIPE_ALLOW_CREATE: 'on'}))

    def getAbsoluteURL(self, target):
        """Get the webservice absolute URL of the given object or relative
        path."""
        if not isinstance(target, string_types):
            target = api_url(target)
        return self.webservice.getAbsoluteUrl(target)

    def load_from_api(self, url):
        response = self.webservice.get(url)
        self.assertEqual(200, response.status, response.body)
        return response.jsonBody()

    def test_api_get_oci_recipe(self):
        with person_logged_in(self.person):
            oci_project = self.factory.makeOCIProject(
                registrant=self.person)
            recipe = self.factory.makeOCIRecipe(
                oci_project=oci_project)
            url = api_url(recipe)

        ws_recipe = self.load_from_api(url)

        with person_logged_in(self.person):
            recipe_abs_url = self.getAbsoluteURL(recipe)
            self.assertThat(ws_recipe, ContainsDict(dict(
                date_created=Equals(recipe.date_created.isoformat()),
                date_last_modified=Equals(recipe.date_last_modified.isoformat()),
                registrant_link=Equals(self.getAbsoluteURL(recipe.registrant)),
                webhooks_collection_link=Equals(recipe_abs_url + "/webhooks"),
                name=Equals(recipe.name),
                owner_link=Equals(self.getAbsoluteURL(recipe.owner)),
                oci_project_link=Equals(self.getAbsoluteURL(oci_project)),
                git_ref_link=Equals(self.getAbsoluteURL(recipe.git_ref)),
                description=Equals(recipe.description),
                build_file=Equals(recipe.build_file),
                build_daily=Equals(recipe.build_daily)
                )))

    def test_api_patch_oci_recipe(self):
        with person_logged_in(self.person):
            distro = self.factory.makeDistribution(owner=self.person)
            oci_project = self.factory.makeOCIProject(
                pillar=distro, registrant=self.person)
            # Only the owner should be able to edit.
            recipe = self.factory.makeOCIRecipe(
                oci_project=oci_project, owner=self.person,
                registrant=self.person)
            url = api_url(recipe)

        new_description = 'Some other description'
        resp = self.webservice.patch(
            url, 'application/json',
            json.dumps({'description': new_description}))

        self.assertEqual(209, resp.status, resp.body)

        ws_project = self.load_from_api(url)
        self.assertEqual(new_description, ws_project['description'])

    def test_api_patch_fails_with_different_user(self):
        with admin_logged_in():
            other_person = self.factory.makePerson()
        with person_logged_in(other_person):
            distro = self.factory.makeDistribution(owner=other_person)
            oci_project = self.factory.makeOCIProject(
                pillar=distro, registrant=other_person)
            # Only the owner should be able to edit.
            recipe = self.factory.makeOCIRecipe(
                oci_project=oci_project, owner=other_person,
                registrant=other_person,
                description="old description")
            url = api_url(recipe)

        new_description = 'Some other description'
        resp = self.webservice.patch(
            url, 'application/json',
            json.dumps({'description': new_description}))
        self.assertEqual(401, resp.status, resp.body)

        ws_project = self.load_from_api(url)
        self.assertEqual("old description", ws_project['description'])

    def test_api_create_oci_recipe(self):
        with person_logged_in(self.person):
            distro = self.factory.makeDistribution(
                owner=self.person)
            oci_project = self.factory.makeOCIProject(
                pillar=distro, registrant=self.person)
            git_ref = self.factory.makeGitRefs()[0]

            oci_project_url = api_url(oci_project)
            git_ref_url = api_url(git_ref)
            person_url = api_url(self.person)

        obj = {
            "name": "my-recipe",
            "owner": person_url,
            "git_ref": git_ref_url,
            "build_file": "./Dockerfile",
            "description": "My recipe"}

        resp = self.webservice.named_post(oci_project_url, "newRecipe", **obj)
        self.assertEqual(201, resp.status, resp.body)

        new_obj_url = resp.getHeader("Location")
        ws_recipe = self.load_from_api(new_obj_url)

        with person_logged_in(self.person):
            self.assertThat(ws_recipe, ContainsDict(dict(
                name=Equals(obj["name"]),
                oci_project_link=Equals(self.getAbsoluteURL(oci_project)),
                git_ref_link=Equals(self.getAbsoluteURL(git_ref)),
                build_file=Equals(obj["build_file"]),
                description=Equals(obj["description"]),
                owner_link=Equals(self.getAbsoluteURL(self.person)),
                registrant_link=Equals(self.getAbsoluteURL(self.person)),
            )))

    def test_api_create_oci_recipe_non_legitimate_user(self):
        """Ensure that a non-legitimate user cannot create recipe using API"""
        self.pushConfig(
            'launchpad', min_legitimate_karma=9999,
            min_legitimate_account_age=9999)

        with person_logged_in(self.person):
            distro = self.factory.makeDistribution(
                owner=self.person)
            oci_project = self.factory.makeOCIProject(
                pillar=distro, registrant=self.person)
            git_ref = self.factory.makeGitRefs()[0]

            oci_project_url = api_url(oci_project)
            git_ref_url = api_url(git_ref)
            person_url = api_url(self.person)

        obj = {
            "name": "My recipe",
            "owner": person_url,
            "git_ref": git_ref_url,
            "build_file": "./Dockerfile",
            "description": "My recipe"}

        resp = self.webservice.named_post(oci_project_url, "newRecipe", **obj)
        self.assertEqual(401, resp.status, resp.body)

    def test_api_create_oci_recipe_is_disabled_by_feature_flag(self):
        """Ensure that OCI newRecipe API method returns HTTP 401 when the
        feature flag is not set."""
        self.useFixture(FeatureFixture({OCI_RECIPE_ALLOW_CREATE: ''}))

        with person_logged_in(self.person):
            distro = self.factory.makeDistribution(
                owner=self.person)
            oci_project = self.factory.makeOCIProject(
                pillar=distro, registrant=self.person)
            git_ref = self.factory.makeGitRefs()[0]

            oci_project_url = api_url(oci_project)
            git_ref_url = api_url(git_ref)
            person_url = api_url(self.person)

        obj = {
            "name": "My recipe",
            "owner": person_url,
            "git_ref": git_ref_url,
            "build_file": "./Dockerfile",
            "description": "My recipe"}

        resp = self.webservice.named_post(oci_project_url, "newRecipe", **obj)
        self.assertEqual(401, resp.status, resp.body)
