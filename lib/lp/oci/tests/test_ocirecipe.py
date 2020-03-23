# Copyright 2019-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for OCI image building recipe functionality."""

from __future__ import absolute_import, print_function, unicode_literals

import json

from fixtures import FakeLogger
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
from lp.oci.interfaces.ocirecipe import (
    DuplicateOCIRecipeName,
    IOCIRecipe,
    IOCIRecipeSet,
    NoSourceForOCIRecipe,
    NoSuchOCIRecipe,
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
        with FeatureFixture({OCI_RECIPE_WEBHOOKS_FEATURE_FLAG: "on"}):
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
        with FeatureFixture({OCI_RECIPE_WEBHOOKS_FEATURE_FLAG: "on"}):
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


class TestOCIRecipeSet(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

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


class TestOCIRecipeWebservice(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestOCIRecipeWebservice, self).setUp()
        self.person = self.factory.makePerson(displayname="Test Person")
        self.webservice = webservice_for_person(
            self.person, permission=OAuthPermission.WRITE_PUBLIC,
            default_api_version="devel")

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
            project = removeSecurityProxy(self.factory.makeOCIProject(
                registrant=self.person))
            recipe = removeSecurityProxy(self.factory.makeOCIRecipe(
                oci_project=project))
            url = api_url(recipe)

        ws_recipe = self.load_from_api(url)

        recipe_abs_url = self.getAbsoluteURL(recipe)
        self.assertThat(ws_recipe, ContainsDict(dict(
            date_created=Equals(recipe.date_created.isoformat()),
            date_last_modified=Equals(recipe.date_last_modified.isoformat()),
            registrant_link=Equals(self.getAbsoluteURL(recipe.registrant)),
            pending_builds_collection_link=Equals(
                recipe_abs_url + "/pending_builds"),
            webhooks_collection_link=Equals(recipe_abs_url + "/webhooks"),
            name=Equals(recipe.name),
            owner_link=Equals(self.getAbsoluteURL(recipe.owner)),
            oci_project_link=Equals(self.getAbsoluteURL(project)),
            git_ref_link=Equals(self.getAbsoluteURL(recipe.git_ref)),
            description=Equals(recipe.description),
            build_file=Equals(recipe.build_file),
            build_daily=Equals(recipe.build_daily)
            )))

    def test_api_patch_oci_recipe(self):
        with person_logged_in(self.person):
            distro = self.factory.makeDistribution(owner=self.person)
            project = removeSecurityProxy(self.factory.makeOCIProject(
                pillar=distro, registrant=self.person))
            # Only the owner should be able to edit.
            recipe = removeSecurityProxy(self.factory.makeOCIRecipe(
                oci_project=project, owner=self.person,
                registrant=self.person))
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
            project = removeSecurityProxy(self.factory.makeOCIProject(
                pillar=distro, registrant=other_person))
            # Only the owner should be able to edit.
            recipe = removeSecurityProxy(self.factory.makeOCIRecipe(
                oci_project=project, owner=other_person,
                registrant=other_person,
                description="old description"))
            url = api_url(recipe)

        new_description = 'Some other description'
        resp = self.webservice.patch(
            url, 'application/json',
            json.dumps({'description': new_description}))
        self.assertEqual(401, resp.status, resp.body)

        ws_project = self.load_from_api(url)
        self.assertEqual("old description", ws_project['description'])
