# Copyright 2019-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for OCI image building recipe functionality."""

import json
from datetime import datetime

import transaction
from fixtures import FakeLogger
from storm.exceptions import LostObjectError
from storm.store import Store
from testtools import ExpectedException
from testtools.matchers import (
    ContainsDict,
    Equals,
    Is,
    IsInstance,
    MatchesDict,
    MatchesSetwise,
    MatchesStructure,
)
from zope.component import getUtility
from zope.schema import ValidationError
from zope.security.interfaces import ForbiddenAttribute, Unauthorized
from zope.security.proxy import removeSecurityProxy

from lp.app.enums import InformationType
from lp.buildmaster.enums import BuildStatus
from lp.buildmaster.interfaces.processor import IProcessorSet
from lp.code.tests.helpers import GitHostingFixture
from lp.oci.interfaces.ocipushrule import (
    IOCIPushRuleSet,
    OCIPushRuleAlreadyExists,
)
from lp.oci.interfaces.ocirecipe import (
    OCI_RECIPE_ALLOW_CREATE,
    OCI_RECIPE_BUILD_DISTRIBUTION,
    CannotModifyOCIRecipeProcessor,
    DuplicateOCIRecipeName,
    IOCIRecipe,
    IOCIRecipeSet,
    NoSourceForOCIRecipe,
    NoSuchOCIRecipe,
    OCIRecipeBuildAlreadyPending,
    OCIRecipeBuildRequestStatus,
    OCIRecipeNotOwner,
    OCIRecipePrivacyMismatch,
    UsingDistributionCredentials,
)
from lp.oci.interfaces.ocirecipebuild import IOCIRecipeBuildSet
from lp.oci.interfaces.ocirecipejob import IOCIRecipeRequestBuildsJobSource
from lp.oci.interfaces.ociregistrycredentials import (
    OCIRegistryCredentialsNotOwner,
)
from lp.oci.tests.helpers import (
    MatchesOCIRegistryCredentials,
    OCIConfigHelperMixin,
)
from lp.registry.enums import (
    BranchSharingPolicy,
    PersonVisibility,
    TeamMembershipPolicy,
)
from lp.registry.interfaces.accesspolicy import (
    IAccessArtifactSource,
    IAccessPolicyArtifactSource,
    IAccessPolicySource,
)
from lp.registry.interfaces.ociproject import OCIProjectRecipeInvalid
from lp.registry.interfaces.series import SeriesStatus
from lp.registry.model.accesspolicy import AccessArtifact, AccessArtifactGrant
from lp.services.config import config
from lp.services.database.constants import ONE_DAY_AGO, UTC_NOW
from lp.services.database.interfaces import IStore
from lp.services.database.sqlbase import flush_database_caches
from lp.services.features.testing import FeatureFixture
from lp.services.job.runner import JobRunner
from lp.services.webapp.interfaces import OAuthPermission
from lp.services.webapp.publisher import canonical_url
from lp.services.webapp.snapshot import notify_modified
from lp.services.webhooks.testing import LogsScheduledWebhooks
from lp.testing import (
    StormStatementRecorder,
    TestCaseWithFactory,
    admin_logged_in,
    api_url,
    login_admin,
    login_person,
    person_logged_in,
)
from lp.testing.dbuser import dbuser
from lp.testing.layers import DatabaseFunctionalLayer, LaunchpadFunctionalLayer
from lp.testing.pages import webservice_for_person


class TestOCIRecipe(OCIConfigHelperMixin, TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.useFixture(FeatureFixture({OCI_RECIPE_ALLOW_CREATE: "on"}))

    def test_implements_interface(self):
        target = self.factory.makeOCIRecipe()
        with admin_logged_in():
            self.assertProvides(target, IOCIRecipe)

    def test_default_distribution_on_project_pillar(self):
        # If OCI_RECIPE_BUILD_DISTRIBUTION flag is not set, we use Ubuntu.
        project = self.factory.makeProduct()
        oci_project = self.factory.makeOCIProject(pillar=project)
        recipe = self.factory.makeOCIRecipe(oci_project=oci_project)
        self.assertEqual("ubuntu", recipe.distribution.name)

    def test_feature_flag_distribution_on_project_pillar(self):
        # With the OCI_RECIPE_BUILD_DISTRIBUTION feature flag set, we should
        # use the distribution with the given name.
        distro_name = "mydistro"
        distribution = self.factory.makeDistribution(name=distro_name)
        project = self.factory.makeProduct()
        oci_project = self.factory.makeOCIProject(pillar=project)
        recipe = self.factory.makeOCIRecipe(oci_project=oci_project)
        with FeatureFixture({OCI_RECIPE_BUILD_DISTRIBUTION: distro_name}):
            self.assertEqual(distribution, recipe.distribution)

    def test_feature_flag_inexisting_distribution_on_project_pillar(self):
        # If we mistakenly set the flag to a non-existing distribution,
        # things should break explicitly.
        project = self.factory.makeProduct()
        oci_project = self.factory.makeOCIProject(pillar=project)
        recipe = self.factory.makeOCIRecipe(oci_project=oci_project)
        with FeatureFixture({OCI_RECIPE_BUILD_DISTRIBUTION: "banana-distro"}):
            expected_msg = (
                "'banana-distro' is not a valid value for feature flag '%s'"
                % OCI_RECIPE_BUILD_DISTRIBUTION
            )
            self.assertRaisesWithContent(
                ValueError, expected_msg, getattr, recipe, "distribution"
            )

    def test_distribution_for_distro_based_oci_project(self):
        # For distribution-based OCI projects, we should use OCIProject's
        # distribution as the recipe distribution.
        distribution = self.factory.makeDistribution()
        oci_project = self.factory.makeOCIProject(pillar=distribution)
        recipe = self.factory.makeOCIRecipe(oci_project=oci_project)
        self.assertEqual(distribution, recipe.distribution)

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
            recipe, "date_last_modified", UTC_NOW
        )

    def test_checkRequestBuild(self):
        ocirecipe = removeSecurityProxy(self.factory.makeOCIRecipe())
        unrelated_person = self.factory.makePerson()
        self.assertRaises(
            OCIRecipeNotOwner, ocirecipe._checkRequestBuild, unrelated_person
        )

    def getDistroArchSeries(
        self, distroseries, proc_name="386", arch_tag="i386"
    ):
        processor = getUtility(IProcessorSet).getByName(proc_name)

        das = self.factory.makeDistroArchSeries(
            distroseries=distroseries,
            architecturetag=arch_tag,
            processor=processor,
        )
        fake_chroot = self.factory.makeLibraryFileAlias(
            filename="fake_chroot.tar.gz", db_only=True
        )
        das.addOrUpdateChroot(fake_chroot)
        return das

    def test_hasPendingBuilds(self):
        ocirecipe = removeSecurityProxy(
            self.factory.makeOCIRecipe(require_virtualized=False)
        )
        distro = ocirecipe.oci_project.distribution
        series = self.factory.makeDistroSeries(
            distribution=distro, status=SeriesStatus.CURRENT
        )

        arch_series_386 = self.getDistroArchSeries(series, "386", "386")
        arch_series_hppa = self.getDistroArchSeries(series, "hppa", "hppa")

        # Successful build (i386)
        self.factory.makeOCIRecipeBuild(
            recipe=ocirecipe,
            status=BuildStatus.FULLYBUILT,
            distro_arch_series=arch_series_386,
        )
        # Failed build (i386)
        self.factory.makeOCIRecipeBuild(
            recipe=ocirecipe,
            status=BuildStatus.FAILEDTOBUILD,
            distro_arch_series=arch_series_386,
        )
        # Building build (i386)
        self.factory.makeOCIRecipeBuild(
            recipe=ocirecipe,
            status=BuildStatus.BUILDING,
            distro_arch_series=arch_series_386,
        )
        # Building build (hppa)
        self.factory.makeOCIRecipeBuild(
            recipe=ocirecipe,
            status=BuildStatus.BUILDING,
            distro_arch_series=arch_series_hppa,
        )

        self.assertFalse(ocirecipe._hasPendingBuilds([arch_series_386]))
        self.assertFalse(ocirecipe._hasPendingBuilds([arch_series_hppa]))
        self.assertFalse(
            ocirecipe._hasPendingBuilds([arch_series_386, arch_series_hppa])
        )

        # The only pending build, for i386.
        self.factory.makeOCIRecipeBuild(
            recipe=ocirecipe,
            status=BuildStatus.NEEDSBUILD,
            distro_arch_series=arch_series_386,
        )

        self.assertTrue(ocirecipe._hasPendingBuilds([arch_series_386]))
        self.assertFalse(ocirecipe._hasPendingBuilds([arch_series_hppa]))
        self.assertFalse(
            ocirecipe._hasPendingBuilds([arch_series_386, arch_series_hppa])
        )

        # Add a pending for hppa
        self.factory.makeOCIRecipeBuild(
            recipe=ocirecipe,
            status=BuildStatus.NEEDSBUILD,
            distro_arch_series=arch_series_hppa,
        )

        self.assertTrue(
            ocirecipe._hasPendingBuilds([arch_series_386, arch_series_hppa])
        )

    def test_requestBuild(self):
        ocirecipe = self.factory.makeOCIRecipe()
        das = self.factory.makeDistroArchSeries()
        build = ocirecipe.requestBuild(ocirecipe.owner, das)
        self.assertEqual(build.status, BuildStatus.NEEDSBUILD)

    def test_requestBuild_already_exists(self):
        ocirecipe = self.factory.makeOCIRecipe()
        das = self.factory.makeDistroArchSeries()
        ocirecipe.requestBuild(ocirecipe.owner, das)

        self.assertRaises(
            OCIRecipeBuildAlreadyPending,
            ocirecipe.requestBuild,
            ocirecipe.owner,
            das,
        )

    def test_requestBuild_triggers_webhooks(self):
        # Requesting a build triggers webhooks.
        logger = self.useFixture(FakeLogger())
        with FeatureFixture({OCI_RECIPE_ALLOW_CREATE: "on"}):
            recipe = self.factory.makeOCIRecipe()
            das = self.factory.makeDistroArchSeries()
            hook = self.factory.makeWebhook(
                target=recipe, event_types=["oci-recipe:build:0.1"]
            )
            build = recipe.requestBuild(recipe.owner, das)

        expected_payload = {
            "recipe_build": Equals(
                canonical_url(build, force_local_path=True)
            ),
            "action": Equals("created"),
            "recipe": Equals(canonical_url(recipe, force_local_path=True)),
            "build_request": Is(None),
            "status": Equals("Needs building"),
            "registry_upload_status": Equals("Unscheduled"),
        }
        with person_logged_in(recipe.owner):
            delivery = hook.deliveries.one()
            self.assertThat(
                delivery,
                MatchesStructure(
                    event_type=Equals("oci-recipe:build:0.1"),
                    payload=MatchesDict(expected_payload),
                ),
            )
            with dbuser(config.IWebhookDeliveryJobSource.dbuser):
                self.assertEqual(
                    "<WebhookDeliveryJob for webhook %d on %r>"
                    % (hook.id, hook.target),
                    repr(delivery),
                )
                self.assertThat(
                    logger.output,
                    LogsScheduledWebhooks(
                        [
                            (
                                hook,
                                "oci-recipe:build:0.1",
                                MatchesDict(expected_payload),
                            )
                        ]
                    ),
                )

    def test_requestBuildsFromJob_creates_builds(self):
        ocirecipe = removeSecurityProxy(
            self.factory.makeOCIRecipe(require_virtualized=False)
        )
        owner = ocirecipe.owner
        distro = ocirecipe.oci_project.distribution
        series = self.factory.makeDistroSeries(
            distribution=distro, status=SeriesStatus.CURRENT
        )
        arch_series_386 = self.getDistroArchSeries(series, "386", "386")
        arch_series_hppa = self.getDistroArchSeries(series, "hppa", "hppa")
        job = getUtility(IOCIRecipeRequestBuildsJobSource).create(
            ocirecipe, owner
        )

        with person_logged_in(job.requester):
            builds = ocirecipe.requestBuildsFromJob(
                job.requester, build_request=job.build_request
            )
            self.assertThat(
                builds,
                MatchesSetwise(
                    MatchesStructure(
                        recipe=Equals(ocirecipe),
                        processor=Equals(arch_series_386.processor),
                    ),
                    MatchesStructure(
                        recipe=Equals(ocirecipe),
                        processor=Equals(arch_series_hppa.processor),
                    ),
                ),
            )

    def test_requestBuildsFromJob_unauthorized_user(self):
        ocirecipe = removeSecurityProxy(self.factory.makeOCIRecipe())
        self.factory.makeDistroSeries(
            distribution=ocirecipe.oci_project.distribution,
            status=SeriesStatus.CURRENT,
        )
        another_user = self.factory.makePerson()
        job = getUtility(IOCIRecipeRequestBuildsJobSource).create(
            ocirecipe, another_user
        )
        with person_logged_in(job.requester):
            self.assertRaises(
                OCIRecipeNotOwner,
                ocirecipe.requestBuildsFromJob,
                job.requester,
                build_request=job.build_request,
            )

    def test_requestBuildsFromJob_with_pending_jobs(self):
        ocirecipe = removeSecurityProxy(self.factory.makeOCIRecipe())
        distro = ocirecipe.oci_project.distribution
        series = self.factory.makeDistroSeries(
            distribution=distro, status=SeriesStatus.CURRENT
        )
        arch_series_386 = self.getDistroArchSeries(series, "386", "386")
        self.factory.makeOCIRecipeBuild(
            recipe=ocirecipe,
            status=BuildStatus.NEEDSBUILD,
            distro_arch_series=arch_series_386,
        )
        job = getUtility(IOCIRecipeRequestBuildsJobSource).create(
            ocirecipe, ocirecipe.owner
        )

        with person_logged_in(job.requester):
            self.assertRaises(
                OCIRecipeBuildAlreadyPending,
                ocirecipe.requestBuildsFromJob,
                job.requester,
                build_request=job.build_request,
            )

    def test_requestBuildsFromJob_triggers_webhooks(self):
        # requestBuildsFromJob triggers webhooks, and the payload includes a
        # link to the build request.
        self.useFixture(FeatureFixture({OCI_RECIPE_ALLOW_CREATE: "on"}))
        recipe = removeSecurityProxy(
            self.factory.makeOCIRecipe(require_virtualized=False)
        )
        distro = recipe.oci_project.distribution
        series = self.factory.makeDistroSeries(
            distribution=distro, status=SeriesStatus.CURRENT
        )
        self.getDistroArchSeries(series, "386", "386")
        self.getDistroArchSeries(series, "hppa", "hppa")
        job = getUtility(IOCIRecipeRequestBuildsJobSource).create(
            recipe, recipe.owner
        )

        logger = self.useFixture(FakeLogger())
        hook = self.factory.makeWebhook(
            target=job.recipe, event_types=["oci-recipe:build:0.1"]
        )
        with person_logged_in(job.requester):
            builds = recipe.requestBuildsFromJob(
                job.requester, build_request=job.build_request
            )
            self.assertEqual(2, len(builds))
            payload_matchers = [
                MatchesDict(
                    {
                        "recipe_build": Equals(
                            canonical_url(build, force_local_path=True)
                        ),
                        "action": Equals("created"),
                        "recipe": Equals(
                            canonical_url(job.recipe, force_local_path=True)
                        ),
                        "build_request": Equals(
                            canonical_url(
                                job.build_request, force_local_path=True
                            )
                        ),
                        "status": Equals("Needs building"),
                        "registry_upload_status": Equals("Unscheduled"),
                    }
                )
                for build in builds
            ]
            self.assertThat(
                hook.deliveries,
                MatchesSetwise(
                    *(
                        MatchesStructure(
                            event_type=Equals("oci-recipe:build:0.1"),
                            payload=payload_matcher,
                        )
                        for payload_matcher in payload_matchers
                    )
                ),
            )
            self.assertThat(
                logger.output,
                LogsScheduledWebhooks(
                    [
                        (hook, "oci-recipe:build:0.1", payload_matcher)
                        for payload_matcher in payload_matchers
                    ]
                ),
            )

    def test_destroySelf(self):
        self.setConfig()
        oci_recipe = self.factory.makeOCIRecipe()
        # Create associated builds:
        build_request = oci_recipe.requestBuilds(oci_recipe.owner, ["386"])
        build_ids = [
            self.factory.makeOCIRecipeBuild(
                recipe=oci_recipe, build_request=build_request
            ).id
            for _ in range(3)
        ]
        # Create associated push rules:
        push_rule_ids = [
            self.factory.makeOCIPushRule(recipe=oci_recipe).id
            for i in range(3)
        ]

        with person_logged_in(oci_recipe.owner):
            oci_recipe.destroySelf()
        flush_database_caches()

        for build_id in build_ids:
            self.assertIsNone(getUtility(IOCIRecipeBuildSet).getByID(build_id))
        for push_rule_id in push_rule_ids:
            self.assertIsNone(
                getUtility(IOCIPushRuleSet).getByID(push_rule_id)
            )

    def test_related_webhooks_deleted(self):
        owner = self.factory.makePerson()
        with FeatureFixture({OCI_RECIPE_ALLOW_CREATE: "on"}):
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
        builds = [
            self.factory.makeOCIRecipeBuild(recipe=oci_recipe)
            for x in range(3)
        ]
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
            [fullybuilt, instacancelled], list(oci_recipe.completed_builds)
        )
        self.assertEqual([], list(oci_recipe.pending_builds))

    def test_push_rules(self):
        self.setConfig()
        oci_recipe = self.factory.makeOCIRecipe()
        for _ in range(3):
            self.factory.makeOCIPushRule(recipe=oci_recipe)
        # Add some others
        for _ in range(3):
            self.factory.makeOCIPushRule()

        for rule in oci_recipe.push_rules:
            self.assertEqual(rule.recipe, oci_recipe)

    def test_newPushRule(self):
        self.setConfig()
        recipe = self.factory.makeOCIRecipe()
        url = self.factory.getUniqueURL()
        image_name = self.factory.getUniqueUnicode()
        credentials = {
            "username": "test-username",
            "password": "test-password",
        }

        with person_logged_in(recipe.registrant):
            push_rule = recipe.newPushRule(
                recipe.registrant,
                url,
                image_name,
                credentials,
                credentials_owner=recipe.registrant,
            )
            self.assertThat(
                push_rule,
                MatchesStructure(
                    image_name=Equals(image_name),
                    registry_credentials=MatchesOCIRegistryCredentials(
                        MatchesStructure.byEquality(
                            owner=recipe.registrant, url=url
                        ),
                        Equals(credentials),
                    ),
                ),
            )
            self.assertEqual(push_rule, recipe.push_rules[0])

    def test_newPushRule_default_owner(self):
        # The registry credentials for a new push rule default to being
        # owned by the recipe owner.
        self.setConfig()
        recipe = self.factory.makeOCIRecipe()
        url = self.factory.getUniqueURL()
        image_name = self.factory.getUniqueUnicode()
        credentials = {
            "username": "test-username",
            "password": "test-password",
        }

        with person_logged_in(recipe.registrant):
            push_rule = recipe.newPushRule(
                recipe.registrant, url, image_name, credentials
            )
            self.assertThat(
                push_rule,
                MatchesStructure(
                    image_name=Equals(image_name),
                    registry_credentials=MatchesOCIRegistryCredentials(
                        MatchesStructure.byEquality(
                            owner=recipe.owner, url=url
                        ),
                        Equals(credentials),
                    ),
                ),
            )
            self.assertEqual(push_rule, recipe.push_rules[0])

    def test_newPushRule_invalid_url(self):
        self.setConfig()
        recipe = self.factory.makeOCIRecipe()
        url = "asdf://foo.com"
        image_name = self.factory.getUniqueUnicode()
        credentials = {
            "username": "test-username",
            "password": "test-password",
        }

        with person_logged_in(recipe.owner):
            self.assertRaises(
                ValidationError,
                recipe.newPushRule,
                recipe.owner,
                url,
                image_name,
                credentials,
                credentials_owner=recipe.owner,
            )
            # Avoid trying to flush the incomplete object on cleanUp.
            Store.of(recipe).rollback()

    def test_newPushRule_same_details(self):
        self.setConfig()
        recipe = self.factory.makeOCIRecipe()
        url = self.factory.getUniqueURL()
        image_name = self.factory.getUniqueUnicode()
        credentials = {
            "username": "test-username",
            "password": "test-password",
        }

        with person_logged_in(recipe.owner):
            recipe.newPushRule(
                recipe.owner,
                url,
                image_name,
                credentials,
                credentials_owner=recipe.owner,
            )
            self.assertRaises(
                OCIPushRuleAlreadyExists,
                recipe.newPushRule,
                recipe.owner,
                url,
                image_name,
                credentials,
                credentials_owner=recipe.owner,
            )

    def test_newPushRule_not_owner(self):
        # If the registrant is not the owner or a member of the owner team,
        # push rule creation fails.
        self.setConfig()
        recipe = self.factory.makeOCIRecipe()
        url = self.factory.getUniqueURL()
        image_name = self.factory.getUniqueUnicode()
        credentials = {
            "username": "test-username",
            "password": "test-password",
        }
        other_person = self.factory.makePerson()
        other_team = self.factory.makeTeam(owner=other_person)

        with person_logged_in(recipe.registrant):
            expected_message = "%s cannot create credentials owned by %s." % (
                recipe.registrant.display_name,
                other_person.display_name,
            )
            with ExpectedException(
                OCIRegistryCredentialsNotOwner, expected_message
            ):
                recipe.newPushRule(
                    recipe.registrant,
                    url,
                    image_name,
                    credentials,
                    credentials_owner=other_person,
                )
            expected_message = "%s is not a member of %s." % (
                recipe.registrant.display_name,
                other_team.display_name,
            )
            with ExpectedException(
                OCIRegistryCredentialsNotOwner, expected_message
            ):
                recipe.newPushRule(
                    recipe.registrant,
                    url,
                    image_name,
                    credentials,
                    credentials_owner=other_team,
                )

    def test_newPushRule_distribution_credentials(self):
        # If the OCIRecipe is in a Distribution with credentials set
        # we cannot create new push rules
        self.setConfig()
        distribution = self.factory.makeDistribution()
        credentials = self.factory.makeOCIRegistryCredentials()
        project = self.factory.makeOCIProject(pillar=distribution)
        recipe = self.factory.makeOCIRecipe(oci_project=project)
        with person_logged_in(distribution.owner):
            distribution.oci_registry_credentials = credentials
            project.setOfficialRecipeStatus(recipe, True)

        url = "asdf://foo.com"
        image_name = self.factory.getUniqueUnicode()
        credentials = {
            "username": "test-username",
            "password": "test-password",
        }

        with person_logged_in(recipe.owner):
            with ExpectedException(UsingDistributionCredentials):
                recipe.newPushRule(
                    recipe.registrant,
                    url,
                    image_name,
                    credentials,
                    credentials_owner=recipe.registrant,
                )

    def test_set_official_directly_is_forbidden(self):
        recipe = self.factory.makeOCIRecipe()
        self.assertRaises(
            ForbiddenAttribute, setattr, recipe, "official", True
        )

    def test_set_recipe_as_official_for_oci_project(self):
        distro = self.factory.makeDistribution()
        owner = distro.owner
        login_person(owner)
        oci_project1 = self.factory.makeOCIProject(
            registrant=owner, pillar=distro
        )
        oci_project2 = self.factory.makeOCIProject(
            registrant=owner, pillar=distro
        )

        oci_proj1_recipes = [
            self.factory.makeOCIRecipe(
                oci_project=oci_project1, registrant=owner, owner=owner
            )
            for _ in range(3)
        ]

        # Recipes for project 2
        oci_proj2_recipes = [
            self.factory.makeOCIRecipe(
                oci_project=oci_project2, registrant=owner, owner=owner
            )
            for _ in range(2)
        ]

        self.assertTrue(oci_project1.getOfficialRecipes().is_empty())
        self.assertTrue(oci_project2.getOfficialRecipes().is_empty())
        for recipe in oci_proj1_recipes + oci_proj2_recipes:
            self.assertFalse(recipe.official)

        # Cache permissions.
        oci_project1.setOfficialRecipeStatus

        # Set official for project1 and make sure nothing else got changed.
        with StormStatementRecorder() as recorder:
            oci_project1.setOfficialRecipeStatus(oci_proj1_recipes[0], True)
            Store.of(oci_project1).flush()
        self.assertEqual(1, recorder.count)

        self.assertTrue(oci_project2.getOfficialRecipes().is_empty())
        self.assertEqual(
            oci_proj1_recipes[0], oci_project1.getOfficialRecipes()[0]
        )
        self.assertTrue(oci_proj1_recipes[0].official)
        for recipe in oci_proj1_recipes[1:] + oci_proj2_recipes:
            self.assertFalse(recipe.official)

        # Set back no recipe as official.
        with StormStatementRecorder() as recorder:
            oci_project1.setOfficialRecipeStatus(oci_proj1_recipes[0], False)
            Store.of(oci_project1).flush()
        self.assertEqual(1, recorder.count)

        for recipe in oci_proj1_recipes + oci_proj2_recipes:
            self.assertFalse(recipe.official)

    def test_set_recipe_as_official_for_wrong_oci_project(self):
        distro = self.factory.makeDistribution()
        owner = distro.owner
        login_person(owner)
        oci_project = self.factory.makeOCIProject(
            registrant=owner, pillar=distro
        )
        another_oci_project = self.factory.makeOCIProject(
            registrant=owner, pillar=distro
        )

        recipe = self.factory.makeOCIRecipe(
            oci_project=oci_project, registrant=owner
        )

        self.assertRaises(
            OCIProjectRecipeInvalid,
            another_oci_project.setOfficialRecipeStatus,
            recipe,
            True,
        )

    def test_permission_check_on_setOfficialRecipe(self):
        distro = self.factory.makeDistribution()
        owner = distro.owner
        login_person(owner)
        oci_project = self.factory.makeOCIProject(
            registrant=owner, pillar=distro
        )

        another_user = self.factory.makePerson()
        with person_logged_in(another_user):
            self.assertRaises(
                Unauthorized, getattr, oci_project, "setOfficialRecipeStatus"
            )

    def test_oci_project_get_recipe_by_name_and_owner(self):
        owner = self.factory.makePerson()
        login_person(owner)
        oci_project = self.factory.makeOCIProject(registrant=owner)

        recipe = self.factory.makeOCIRecipe(
            oci_project=oci_project,
            registrant=owner,
            owner=owner,
            name="foo-recipe",
        )

        self.assertEqual(
            recipe,
            oci_project.getRecipeByNameAndOwner(recipe.name, owner.name),
        )
        self.assertIsNone(
            oci_project.getRecipeByNameAndOwner(recipe.name, "someone")
        )
        self.assertIsNone(
            oci_project.getRecipeByNameAndOwner("some-recipe", owner.name)
        )

    def test_search_recipe_from_oci_project(self):
        owner = self.factory.makePerson()
        login_person(owner)
        oci_project = self.factory.makeOCIProject(registrant=owner)
        another_oci_project = self.factory.makeOCIProject(registrant=owner)

        recipe1 = self.factory.makeOCIRecipe(
            name="a something", oci_project=oci_project, registrant=owner
        )
        recipe2 = self.factory.makeOCIRecipe(
            name="banana", oci_project=oci_project, registrant=owner
        )
        # Recipe from another project.
        self.factory.makeOCIRecipe(
            name="something too",
            oci_project=another_oci_project,
            registrant=owner,
        )

        self.assertEqual([recipe1], list(oci_project.searchRecipes("somet")))
        self.assertEqual([recipe2], list(oci_project.searchRecipes("bana")))
        self.assertEqual([], list(oci_project.searchRecipes("foo")))

    def test_search_recipe_from_oci_project_is_ordered(self):
        login_admin()
        team = self.factory.makeTeam()
        owner1 = self.factory.makePerson(name="a-user")
        owner2 = self.factory.makePerson(name="b-user")
        owner3 = self.factory.makePerson(name="foo-person")
        team.addMember(owner1, team)
        team.addMember(owner2, team)
        team.addMember(owner3, team)

        distro = self.factory.makeDistribution(oci_project_admin=team)
        oci_project = self.factory.makeOCIProject(
            registrant=team, pillar=distro
        )
        recipe1 = self.factory.makeOCIRecipe(
            name="same-name",
            oci_project=oci_project,
            registrant=owner1,
            owner=owner1,
        )
        recipe2 = self.factory.makeOCIRecipe(
            name="same-name",
            oci_project=oci_project,
            registrant=owner2,
            owner=owner2,
        )
        recipe3 = self.factory.makeOCIRecipe(
            name="a-first",
            oci_project=oci_project,
            registrant=owner1,
            owner=owner1,
        )
        # This one should be filtered out.
        self.factory.makeOCIRecipe(
            name="xxx",
            oci_project=oci_project,
            registrant=owner3,
            owner=owner3,
        )

        # It should be sorted by owner's name first, then recipe name.
        self.assertEqual(
            [recipe3, recipe1, recipe2], list(oci_project.searchRecipes("a"))
        )

    def test_build_args_dict(self):
        args = {"MY_VERSION": "1.0.3", "ANOTHER_VERSION": "2.9.88"}
        recipe = self.factory.makeOCIRecipe(build_args=args)
        # Force fetch it from database
        store = IStore(recipe)
        store.invalidate(recipe)
        self.assertEqual(args, recipe.build_args)

    def test_build_args_not_dict(self):
        invalid_build_args_set = [
            [1, 2, 3],
            "some string",
            123,
        ]
        for invalid_build_args in invalid_build_args_set:
            self.assertRaises(
                AssertionError,
                self.factory.makeOCIRecipe,
                build_args=invalid_build_args,
            )

    def test_build_args_flatten_dict(self):
        # Makes sure we only store one level of key=pair, flattening to
        # string every value.
        args = {
            "VAR1": {"something": [1, 2, 3]},
            "VAR2": 123,
            "VAR3": "A string",
        }
        recipe = self.factory.makeOCIRecipe(build_args=args)
        # Force fetch it from database
        store = IStore(recipe)
        store.invalidate(recipe)
        self.assertEqual(
            {
                "VAR1": "{'something': [1, 2, 3]}",
                "VAR2": "123",
                "VAR3": "A string",
            },
            recipe.build_args,
        )

    def test_use_distribution_credentials_set(self):
        self.setConfig()
        distribution = self.factory.makeDistribution()
        credentials = self.factory.makeOCIRegistryCredentials()
        with person_logged_in(distribution.owner):
            distribution.oci_registry_credentials = credentials
        project = self.factory.makeOCIProject(pillar=distribution)
        recipe = self.factory.makeOCIRecipe(oci_project=project)
        with person_logged_in(distribution.owner):
            project.setOfficialRecipeStatus(recipe, True)
        self.assertTrue(recipe.use_distribution_credentials)

    def test_use_distribution_credentials_not_set(self):
        distribution = self.factory.makeDistribution()
        project = self.factory.makeOCIProject(pillar=distribution)
        recipe = self.factory.makeOCIRecipe(oci_project=project)
        self.assertFalse(recipe.use_distribution_credentials)

    def test_image_name_set(self):
        distribution = self.factory.makeDistribution()
        project = self.factory.makeOCIProject(pillar=distribution)
        recipe = self.factory.makeOCIRecipe(oci_project=project)
        image_name = self.factory.getUniqueUnicode()
        with person_logged_in(recipe.owner):
            recipe.image_name = image_name
        self.assertEqual(image_name, removeSecurityProxy(recipe)._image_name)

    def test_image_name_not_set(self):
        distribution = self.factory.makeDistribution()
        project = self.factory.makeOCIProject(pillar=distribution)
        recipe = self.factory.makeOCIRecipe(oci_project=project)
        self.assertEqual(recipe.name, recipe.image_name)

    def test_public_recipe_should_not_be_linked_to_private_content(self):
        login_admin()
        private_team = self.factory.makeTeam(
            visibility=PersonVisibility.PRIVATE,
            membership_policy=TeamMembershipPolicy.MODERATED,
        )
        owner = self.factory.makePerson(member_of=[private_team])
        pillar = self.factory.makeProduct(
            owner=private_team,
            registrant=owner,
            information_type=InformationType.PROPRIETARY,
            branch_sharing_policy=BranchSharingPolicy.PROPRIETARY,
        )
        oci_project = self.factory.makeOCIProject(
            registrant=owner, pillar=pillar
        )

        [private_git_ref] = self.factory.makeGitRefs(
            target=pillar,
            owner=owner,
            information_type=InformationType.PROPRIETARY,
            paths=["refs/heads/v1.0-20.04"],
        )

        private_recipe = self.factory.makeOCIRecipe(
            owner=private_team,
            registrant=owner,
            oci_project=oci_project,
            git_ref=private_git_ref,
            information_type=InformationType.PROPRIETARY,
        )
        public_recipe = self.factory.makeOCIRecipe()

        # Should not be able to make the recipe PUBLIC if it's linked to
        self.assertRaises(
            OCIRecipePrivacyMismatch,
            setattr,
            private_recipe,
            "information_type",
            InformationType.PUBLIC,
        )
        # We should not be able to link public recipe to a private repo.
        self.assertRaises(
            OCIRecipePrivacyMismatch,
            setattr,
            public_recipe,
            "git_ref",
            private_git_ref,
        )
        # We should not be able to link public recipe to a private owner.
        self.assertRaises(
            OCIRecipePrivacyMismatch,
            setattr,
            public_recipe,
            "owner",
            private_team,
        )


class TestOCIRecipeAccessControl(TestCaseWithFactory, OCIConfigHelperMixin):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.setConfig()

    def test_change_oci_project_pillar_reconciles_access(self):
        person = self.factory.makePerson()
        initial_project = self.factory.makeProduct(
            name="initial-project", owner=person, registrant=person
        )
        final_project = self.factory.makeProduct(
            name="final-project", owner=person, registrant=person
        )
        oci_project = self.factory.makeOCIProject(
            ociprojectname="the-oci-project",
            pillar=initial_project,
            registrant=person,
        )
        recipes = []
        for _ in range(10):
            recipes.append(
                self.factory.makeOCIRecipe(
                    registrant=person,
                    owner=person,
                    oci_project=oci_project,
                    information_type=InformationType.USERDATA,
                )
            )

        access_artifacts = getUtility(IAccessArtifactSource).find(recipes)
        initial_access_policy = (
            getUtility(IAccessPolicySource)
            .find([(initial_project, InformationType.USERDATA)])
            .one()
        )
        apasource = getUtility(IAccessPolicyArtifactSource)
        policy_artifacts = apasource.find(
            [
                (recipe_artifact, initial_access_policy)
                for recipe_artifact in access_artifacts
            ]
        )
        self.assertEqual(
            {i.policy.pillar for i in policy_artifacts}, {initial_project}
        )

        # Changing OCI project's pillar should move the policy artifacts of
        # all OCI recipes associated to the new pillar.
        flush_database_caches()
        with admin_logged_in():
            oci_project.pillar = final_project

        final_access_policy = (
            getUtility(IAccessPolicySource)
            .find([(final_project, InformationType.USERDATA)])
            .one()
        )
        policy_artifacts = apasource.find(
            [
                (recipe_artifact, final_access_policy)
                for recipe_artifact in access_artifacts
            ]
        )
        self.assertEqual(
            {i.policy.pillar for i in policy_artifacts}, {final_project}
        )

    def getGrants(self, ocirecipe, person=None):
        conditions = [AccessArtifact.ocirecipe == ocirecipe]
        if person is not None:
            conditions.append(AccessArtifactGrant.grantee == person)
        return IStore(AccessArtifactGrant).find(
            AccessArtifactGrant,
            AccessArtifactGrant.abstract_artifact_id == AccessArtifact.id,
            *conditions,
        )

    def test_reconcile_set_public(self):
        owner = self.factory.makePerson()
        recipe = self.factory.makeOCIRecipe(
            registrant=owner,
            owner=owner,
            information_type=InformationType.USERDATA,
        )
        another_user = self.factory.makePerson()
        with admin_logged_in():
            recipe.subscribe(another_user, recipe.owner)
            self.assertEqual(1, self.getGrants(recipe, another_user).count())
            self.assertThat(
                recipe.getSubscription(another_user),
                MatchesStructure(
                    person=Equals(another_user),
                    recipe=Equals(recipe),
                    subscribed_by=Equals(recipe.owner),
                    date_created=IsInstance(datetime),
                ),
            )

            recipe.information_type = InformationType.PUBLIC
            self.assertEqual(0, self.getGrants(recipe, another_user).count())
            self.assertThat(
                recipe.getSubscription(another_user),
                MatchesStructure(
                    person=Equals(another_user),
                    recipe=Equals(recipe),
                    subscribed_by=Equals(recipe.owner),
                    date_created=IsInstance(datetime),
                ),
            )

    def test_owner_is_subscribed_automatically(self):
        recipe = self.factory.makeOCIRecipe()
        owner = recipe.owner
        registrant = recipe.registrant
        self.assertTrue(recipe.visibleByUser(owner))
        self.assertIn(owner, recipe.subscribers)
        with person_logged_in(owner):
            self.assertThat(
                recipe.getSubscription(owner),
                MatchesStructure(
                    person=Equals(owner),
                    subscribed_by=Equals(registrant),
                    date_created=IsInstance(datetime),
                ),
            )

    def test_owner_can_grant_access(self):
        owner = self.factory.makePerson()
        recipe = self.factory.makeOCIRecipe(
            registrant=owner,
            owner=owner,
            information_type=InformationType.USERDATA,
        )
        other_person = self.factory.makePerson()
        with person_logged_in(other_person):
            self.assertRaises(Unauthorized, getattr, recipe, "subscribe")
        with person_logged_in(owner):
            recipe.subscribe(other_person, owner)
            self.assertIn(other_person, recipe.subscribers)

    def test_private_is_invisible_by_default(self):
        owner = self.factory.makePerson()
        person = self.factory.makePerson()
        recipe = self.factory.makeOCIRecipe(
            registrant=owner,
            owner=owner,
            information_type=InformationType.USERDATA,
        )
        with person_logged_in(owner):
            self.assertFalse(recipe.visibleByUser(person))

    def test_private_is_visible_by_team_member(self):
        person = self.factory.makePerson()
        team = self.factory.makeTeam(
            members=[person], membership_policy=TeamMembershipPolicy.MODERATED
        )
        recipe = self.factory.makeOCIRecipe(
            owner=team,
            registrant=person,
            information_type=InformationType.USERDATA,
        )
        with person_logged_in(team):
            self.assertTrue(recipe.visibleByUser(person))

    def test_subscribing_changes_visibility(self):
        person = self.factory.makePerson()
        owner = self.factory.makePerson()
        recipe = self.factory.makeOCIRecipe(
            registrant=owner,
            owner=owner,
            information_type=InformationType.USERDATA,
        )

        with person_logged_in(owner):
            self.assertFalse(recipe.visibleByUser(person))
            recipe.subscribe(person, recipe.owner)
            self.assertThat(
                recipe.getSubscription(person),
                MatchesStructure(
                    person=Equals(person),
                    recipe=Equals(recipe),
                    subscribed_by=Equals(recipe.owner),
                    date_created=IsInstance(datetime),
                ),
            )
            # Calling again should be a no-op.
            recipe.subscribe(person, recipe.owner)
            self.assertTrue(recipe.visibleByUser(person))

            recipe.unsubscribe(person, recipe.owner)
            self.assertFalse(recipe.visibleByUser(person))
            self.assertIsNone(recipe.getSubscription(person))

    def test_owner_can_unsubscribe_anyone(self):
        person = self.factory.makePerson()
        owner = self.factory.makePerson()
        admin = self.factory.makeAdministrator()
        recipe = self.factory.makeOCIRecipe(
            registrant=owner,
            owner=owner,
            information_type=InformationType.USERDATA,
        )
        with person_logged_in(admin):
            recipe.subscribe(person, admin)
            self.assertTrue(recipe.visibleByUser(person))
        with person_logged_in(owner):
            recipe.unsubscribe(person, owner)
            self.assertFalse(recipe.visibleByUser(person))


class TestOCIRecipeProcessors(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp(user="foo.bar@canonical.com")
        self.default_procs = [
            getUtility(IProcessorSet).getByName("386"),
            getUtility(IProcessorSet).getByName("amd64"),
        ]
        self.unrestricted_procs = self.default_procs + [
            getUtility(IProcessorSet).getByName("hppa")
        ]
        self.arm = self.factory.makeProcessor(
            name="arm", restricted=True, build_by_default=False
        )
        self.distroseries = self.factory.makeDistroSeries()
        distribution = self.distroseries.distribution
        self.useFixture(
            FeatureFixture(
                {
                    OCI_RECIPE_ALLOW_CREATE: "on",
                    "oci.build_series.%s"
                    % distribution.name: self.distroseries.name,
                }
            )
        )

    def test_available_processors(self):
        # Only those processors that are enabled for the recipe's
        # distroseries are available.
        for processor in self.default_procs:
            self.factory.makeDistroArchSeries(
                distroseries=self.distroseries,
                architecturetag=processor.name,
                processor=processor,
            )
        self.factory.makeDistroArchSeries(
            architecturetag=self.arm.name, processor=self.arm
        )
        oci_project = self.factory.makeOCIProject(
            pillar=self.distroseries.distribution
        )
        recipe = self.factory.makeOCIRecipe(oci_project=oci_project)
        self.assertContentEqual(
            self.default_procs, recipe.available_processors
        )

    def test_new_default_processors(self):
        # OCIRecipeSet.new creates an OCIRecipeArch for each available
        # Processor with build_by_default set.
        new_procs = [
            self.factory.makeProcessor(name="default", build_by_default=True),
            self.factory.makeProcessor(
                name="nondefault", build_by_default=False
            ),
        ]
        owner = self.factory.makePerson()
        for processor in self.unrestricted_procs + [self.arm] + new_procs:
            self.factory.makeDistroArchSeries(
                distroseries=self.distroseries,
                architecturetag=processor.name,
                processor=processor,
            )
        oci_project = self.factory.makeOCIProject(
            pillar=self.distroseries.distribution
        )
        recipe = getUtility(IOCIRecipeSet).new(
            name=self.factory.getUniqueUnicode(),
            registrant=owner,
            owner=owner,
            oci_project=oci_project,
            git_ref=self.factory.makeGitRefs(paths=["refs/heads/v1.0-20.04"])[
                0
            ],
            build_file=self.factory.getUniqueUnicode(),
        )
        self.assertContentEqual(
            ["386", "amd64", "hppa", "default"],
            [processor.name for processor in recipe.processors],
        )

    def test_new_override_processors(self):
        # OCIRecipeSet.new can be given a custom set of processors.
        owner = self.factory.makePerson()
        oci_project = self.factory.makeOCIProject(
            pillar=self.distroseries.distribution
        )
        recipe = getUtility(IOCIRecipeSet).new(
            name=self.factory.getUniqueUnicode(),
            registrant=owner,
            owner=owner,
            oci_project=oci_project,
            git_ref=self.factory.makeGitRefs(paths=["refs/heads/v1.0-20.04"])[
                0
            ],
            build_file=self.factory.getUniqueUnicode(),
            processors=[self.arm],
        )
        self.assertContentEqual(
            ["arm"], [processor.name for processor in recipe.processors]
        )

    def test_set(self):
        # The property remembers its value correctly.
        recipe = self.factory.makeOCIRecipe()
        recipe.setProcessors([self.arm])
        self.assertContentEqual([self.arm], recipe.processors)
        recipe.setProcessors(self.unrestricted_procs + [self.arm])
        self.assertContentEqual(
            self.unrestricted_procs + [self.arm], recipe.processors
        )
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
                CannotModifyOCIRecipeProcessor,
                recipe.setProcessors,
                [self.default_procs[0], self.arm],
                check_permissions=True,
                user=owner,
            )
            # ... but removing amd64 is OK.
            recipe.setProcessors(
                [self.default_procs[0]], check_permissions=True, user=owner
            )
            self.assertContentEqual([self.default_procs[0]], recipe.processors)
        with admin_logged_in() as admin:
            recipe.setProcessors(
                [self.default_procs[0], self.arm],
                check_permissions=True,
                user=admin,
            )
            self.assertContentEqual(
                [self.default_procs[0], self.arm], recipe.processors
            )
        with person_logged_in(recipe.owner) as owner:
            hppa = getUtility(IProcessorSet).getByName("hppa")
            self.assertFalse(hppa.restricted)
            # Adding hppa while removing arm is forbidden ...
            self.assertRaises(
                CannotModifyOCIRecipeProcessor,
                recipe.setProcessors,
                [self.default_procs[0], hppa],
                check_permissions=True,
                user=owner,
            )
            # ... but adding hppa while retaining arm is OK.
            recipe.setProcessors(
                [self.default_procs[0], self.arm, hppa],
                check_permissions=True,
                user=owner,
            )
            self.assertContentEqual(
                [self.default_procs[0], self.arm, hppa], recipe.processors
            )

    def test_valid_branch_format(self):
        [git_ref] = self.factory.makeGitRefs(paths=["refs/heads/v1.0-20.04"])
        recipe = self.factory.makeOCIRecipe(git_ref=git_ref)
        self.assertTrue(recipe.is_valid_branch_format)

    def test_valid_branch_format_invalid(self):
        # We can't use OCIRecipeSet.new with an invalid path
        # so create a valid one, then change it after
        recipe = self.factory.makeOCIRecipe()
        [git_ref] = self.factory.makeGitRefs(paths=["refs/heads/v1.0-foo"])
        recipe.git_ref = git_ref
        self.assertFalse(recipe.is_valid_branch_format)

    def test_valid_branch_format_invalid_uses_risk(self):
        for risk in ["stable", "candidate", "beta", "edge"]:
            recipe = self.factory.makeOCIRecipe()
            path = "refs/heads/{}-20.04".format(risk)
            [git_ref] = self.factory.makeGitRefs(paths=[path])
            recipe.git_ref = git_ref
            self.assertFalse(recipe.is_valid_branch_format)

    def test_valid_branch_format_invalid_with_slash(self):
        recipe = self.factory.makeOCIRecipe()
        [git_ref] = self.factory.makeGitRefs(paths=["refs/heads/v1.0/bar-foo"])
        recipe.git_ref = git_ref
        self.assertFalse(recipe.is_valid_branch_format)


class TestOCIRecipeSet(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.useFixture(FeatureFixture({OCI_RECIPE_ALLOW_CREATE: "on"}))

    def test_implements_interface(self):
        target_set = getUtility(IOCIRecipeSet)
        with admin_logged_in():
            self.assertProvides(target_set, IOCIRecipeSet)

    def test_new(self):
        registrant = self.factory.makePerson()
        owner = self.factory.makeTeam(members=[registrant])
        oci_project = self.factory.makeOCIProject()
        [git_ref] = self.factory.makeGitRefs(paths=["refs/heads/v1.0-20.04"])
        target = getUtility(IOCIRecipeSet).new(
            name="a name",
            registrant=registrant,
            owner=owner,
            oci_project=oci_project,
            git_ref=git_ref,
            description="a description",
            official=False,
            require_virtualized=False,
            build_file="build file",
            build_path="build path",
        )
        self.assertEqual(target.registrant, registrant)
        self.assertEqual(target.owner, owner)
        self.assertEqual(target.oci_project, oci_project)
        self.assertEqual(target.official, False)
        self.assertEqual(target.require_virtualized, False)
        self.assertEqual(target.git_ref, git_ref)
        self.assertTrue(target.allow_internet)

    def test_already_exists(self):
        owner = self.factory.makePerson()
        oci_project = self.factory.makeOCIProject()
        self.factory.makeOCIRecipe(
            owner=owner,
            registrant=owner,
            name="already exists",
            oci_project=oci_project,
        )

        self.assertRaises(
            DuplicateOCIRecipeName,
            self.factory.makeOCIRecipe,
            owner=owner,
            registrant=owner,
            name="already exists",
            oci_project=oci_project,
        )

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
            build_file="build_file",
        )

    def test_no_source_build_file(self):
        owner = self.factory.makePerson()
        oci_project = self.factory.makeOCIProject()
        recipe_set = getUtility(IOCIRecipeSet)
        [git_ref] = (
            self.factory.makeGitRefs(paths=["refs/heads/v1.0-20.04"]),
        )
        self.assertRaises(
            NoSourceForOCIRecipe,
            recipe_set.new,
            name="no source",
            registrant=owner,
            owner=owner,
            oci_project=oci_project,
            git_ref=git_ref,
            build_file=None,
        )

    def test_getByName(self):
        owner = self.factory.makePerson()
        name = "a test recipe"
        oci_project = self.factory.makeOCIProject()
        target = self.factory.makeOCIRecipe(
            owner=owner, registrant=owner, name=name, oci_project=oci_project
        )

        for _ in range(3):
            self.factory.makeOCIRecipe(oci_project=oci_project)

        result = getUtility(IOCIRecipeSet).getByName(owner, oci_project, name)
        self.assertEqual(target, result)

    def test_getByName_missing(self):
        owner = self.factory.makePerson()
        oci_project = self.factory.makeOCIProject()
        for _ in range(3):
            self.factory.makeOCIRecipe(
                owner=owner, registrant=owner, oci_project=oci_project
            )
        self.assertRaises(
            NoSuchOCIRecipe,
            getUtility(IOCIRecipeSet).getByName,
            owner=owner,
            oci_project=oci_project,
            name="missing",
        )

    def test_findByGitRepository(self):
        # IOCIRecipeSet.findByGitRepository returns all OCI recipes with the
        # given Git repository.
        self.useFixture(GitHostingFixture())
        repositories = [self.factory.makeGitRepository() for i in range(2)]
        oci_recipes = []
        for repository in repositories:
            for _ in range(2):
                [ref] = self.factory.makeGitRefs(
                    repository=repository, paths=["refs/heads/v1.0-20.04"]
                )
                oci_recipes.append(self.factory.makeOCIRecipe(git_ref=ref))
        oci_recipe_set = getUtility(IOCIRecipeSet)
        self.assertContentEqual(
            oci_recipes[:2],
            oci_recipe_set.findByGitRepository(repositories[0]),
        )
        self.assertContentEqual(
            oci_recipes[2:],
            oci_recipe_set.findByGitRepository(repositories[1]),
        )

    def test_findByGitRepository_paths(self):
        # IOCIRecipeSet.findByGitRepository can restrict by reference paths.
        repositories = [self.factory.makeGitRepository() for i in range(2)]
        oci_recipes = []
        for repository in repositories:
            for i in range(3):
                [ref] = self.factory.makeGitRefs(
                    repository=repository,
                    # Needs a unique path, otherwise we can't search for it.
                    paths=["refs/heads/v1.{}-20.04".format(str(i))],
                )
                oci_recipes.append(self.factory.makeOCIRecipe(git_ref=ref))
        oci_recipe_set = getUtility(IOCIRecipeSet)
        self.assertContentEqual(
            [], oci_recipe_set.findByGitRepository(repositories[0], paths=[])
        )
        self.assertContentEqual(
            [oci_recipes[0]],
            oci_recipe_set.findByGitRepository(
                repositories[0], paths=[oci_recipes[0].git_ref.path]
            ),
        )
        self.assertContentEqual(
            oci_recipes[:2],
            oci_recipe_set.findByGitRepository(
                repositories[0],
                paths=[
                    oci_recipes[0].git_ref.path,
                    oci_recipes[1].git_ref.path,
                ],
            ),
        )

    def test_detachFromGitRepository(self):
        self.useFixture(GitHostingFixture())
        repositories = [self.factory.makeGitRepository() for i in range(2)]
        oci_recipes = []
        paths = []
        refs = []
        for repository in repositories:
            for _ in range(2):
                [ref] = self.factory.makeGitRefs(
                    repository=repository, paths=["refs/heads/v1.0-20.04"]
                )
                paths.append(ref.path)
                refs.append(ref)
                oci_recipes.append(
                    self.factory.makeOCIRecipe(
                        git_ref=ref, date_created=ONE_DAY_AGO
                    )
                )
        getUtility(IOCIRecipeSet).detachFromGitRepository(repositories[0])
        self.assertEqual(
            [None, None, repositories[1], repositories[1]],
            [oci_recipe.git_repository for oci_recipe in oci_recipes],
        )
        self.assertEqual(
            [None, None, paths[2], paths[3]],
            [oci_recipe.git_path for oci_recipe in oci_recipes],
        )
        self.assertEqual(
            [None, None, refs[2], refs[3]],
            [oci_recipe.git_ref for oci_recipe in oci_recipes],
        )
        for oci_recipe in oci_recipes[:2]:
            self.assertSqlAttributeEqualsDate(
                oci_recipe, "date_last_modified", UTC_NOW
            )


class TestOCIRecipeWebservice(OCIConfigHelperMixin, TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.person = self.factory.makePerson(displayname="Test Person")
        self.webservice = webservice_for_person(
            self.person,
            permission=OAuthPermission.WRITE_PUBLIC,
            default_api_version="devel",
        )
        self.useFixture(FeatureFixture({OCI_RECIPE_ALLOW_CREATE: "on"}))

    def getAbsoluteURL(self, target):
        """Get the webservice absolute URL of the given object or relative
        path."""
        if not isinstance(target, str):
            target = api_url(target)
        return self.webservice.getAbsoluteUrl(target)

    def load_from_api(self, url):
        response = self.webservice.get(url)
        self.assertEqual(200, response.status, response.body)
        return response.jsonBody()

    def test_api_get_oci_recipe(self):
        with person_logged_in(self.person):
            oci_project = self.factory.makeOCIProject(registrant=self.person)
            recipe = self.factory.makeOCIRecipe(
                oci_project=oci_project, build_args={"VAR_A": "123"}
            )
            url = api_url(recipe)

        ws_recipe = self.load_from_api(url)

        with person_logged_in(self.person):
            recipe_abs_url = self.getAbsoluteURL(recipe)
            self.assertThat(
                ws_recipe,
                ContainsDict(
                    dict(
                        date_created=Equals(recipe.date_created.isoformat()),
                        date_last_modified=Equals(
                            recipe.date_last_modified.isoformat()
                        ),
                        registrant_link=Equals(
                            self.getAbsoluteURL(recipe.registrant)
                        ),
                        webhooks_collection_link=Equals(
                            recipe_abs_url + "/webhooks"
                        ),
                        name=Equals(recipe.name),
                        owner_link=Equals(self.getAbsoluteURL(recipe.owner)),
                        oci_project_link=Equals(
                            self.getAbsoluteURL(oci_project)
                        ),
                        git_ref_link=Equals(
                            self.getAbsoluteURL(recipe.git_ref)
                        ),
                        description=Equals(recipe.description),
                        build_file=Equals(recipe.build_file),
                        build_args=Equals({"VAR_A": "123"}),
                        build_daily=Equals(recipe.build_daily),
                        build_path=Equals(recipe.build_path),
                    )
                ),
            )

    def test_api_patch_oci_recipe(self):
        with person_logged_in(self.person):
            distro = self.factory.makeDistribution(owner=self.person)
            oci_project = self.factory.makeOCIProject(
                pillar=distro, registrant=self.person
            )
            # Only the owner should be able to edit.
            recipe = self.factory.makeOCIRecipe(
                oci_project=oci_project,
                owner=self.person,
                registrant=self.person,
            )
            url = api_url(recipe)

        new_description = "Some other description"
        resp = self.webservice.patch(
            url,
            "application/json",
            json.dumps({"description": new_description}),
        )

        self.assertEqual(209, resp.status, resp.body)

        ws_project = self.load_from_api(url)
        self.assertEqual(new_description, ws_project["description"])

    def test_api_patch_fails_with_different_user(self):
        with admin_logged_in():
            other_person = self.factory.makePerson()
        with person_logged_in(other_person):
            distro = self.factory.makeDistribution(owner=other_person)
            oci_project = self.factory.makeOCIProject(
                pillar=distro, registrant=other_person
            )
            # Only the owner should be able to edit.
            recipe = self.factory.makeOCIRecipe(
                oci_project=oci_project,
                owner=other_person,
                registrant=other_person,
                description="old description",
            )
            url = api_url(recipe)

        new_description = "Some other description"
        resp = self.webservice.patch(
            url,
            "application/json",
            json.dumps({"description": new_description}),
        )
        self.assertEqual(401, resp.status, resp.body)

        ws_project = self.load_from_api(url)
        self.assertEqual("old description", ws_project["description"])

    def test_api_create_oci_recipe(self):
        with person_logged_in(self.person):
            distro = self.factory.makeDistribution(owner=self.person)
            oci_project = self.factory.makeOCIProject(
                pillar=distro, registrant=self.person
            )
            [git_ref] = self.factory.makeGitRefs(
                paths=["refs/heads/v1.0-20.04"]
            )

            oci_project_url = api_url(oci_project)
            git_ref_url = api_url(git_ref)
            person_url = api_url(self.person)

        obj = {
            "name": "my-recipe",
            "owner": person_url,
            "git_ref": git_ref_url,
            "build_file": "./Dockerfile",
            "build_args": {"VAR": "VAR VALUE"},
            "description": "My recipe",
        }

        resp = self.webservice.named_post(oci_project_url, "newRecipe", **obj)
        self.assertEqual(201, resp.status, resp.body)

        new_obj_url = resp.getHeader("Location")
        ws_recipe = self.load_from_api(new_obj_url)

        with person_logged_in(self.person):
            self.assertThat(
                ws_recipe,
                ContainsDict(
                    dict(
                        name=Equals(obj["name"]),
                        oci_project_link=Equals(
                            self.getAbsoluteURL(oci_project)
                        ),
                        git_ref_link=Equals(self.getAbsoluteURL(git_ref)),
                        build_file=Equals(obj["build_file"]),
                        description=Equals(obj["description"]),
                        owner_link=Equals(self.getAbsoluteURL(self.person)),
                        registrant_link=Equals(
                            self.getAbsoluteURL(self.person)
                        ),
                        build_args=Equals({"VAR": "VAR VALUE"}),
                    )
                ),
            )

    def test_api_create_oci_recipe_invalid_branch_format(self):
        with person_logged_in(self.person):
            distro = self.factory.makeDistribution(owner=self.person)
            oci_project = self.factory.makeOCIProject(
                pillar=distro, registrant=self.person
            )
            [git_ref] = self.factory.makeGitRefs(
                paths=["refs/heads/invalid-branch"]
            )

            oci_project_url = api_url(oci_project)
            git_ref_url = api_url(git_ref)
            person_url = api_url(self.person)

        obj = {
            "name": "my-recipe",
            "owner": person_url,
            "git_ref": git_ref_url,
            "build_file": "./Dockerfile",
            "build_args": {"VAR": "VAR VALUE"},
            "description": "My recipe",
        }

        resp = self.webservice.named_post(oci_project_url, "newRecipe", **obj)
        self.assertEqual(400, resp.status, resp.body)

    def test_api_create_oci_recipe_non_legitimate_user(self):
        """Ensure that a non-legitimate user cannot create recipe using API"""
        self.pushConfig(
            "launchpad",
            min_legitimate_karma=9999,
            min_legitimate_account_age=9999,
        )

        with person_logged_in(self.person):
            distro = self.factory.makeDistribution(owner=self.person)
            oci_project = self.factory.makeOCIProject(
                pillar=distro, registrant=self.person
            )
            git_ref = self.factory.makeGitRefs()[0]

            oci_project_url = api_url(oci_project)
            git_ref_url = api_url(git_ref)
            person_url = api_url(self.person)

        obj = {
            "name": "My recipe",
            "owner": person_url,
            "git_ref": git_ref_url,
            "build_file": "./Dockerfile",
            "description": "My recipe",
        }

        resp = self.webservice.named_post(oci_project_url, "newRecipe", **obj)
        self.assertEqual(401, resp.status, resp.body)

    def test_api_create_oci_recipe_is_disabled_by_feature_flag(self):
        """Ensure that OCI newRecipe API method returns HTTP 401 when the
        feature flag is not set."""
        self.useFixture(FeatureFixture({OCI_RECIPE_ALLOW_CREATE: ""}))

        with person_logged_in(self.person):
            distro = self.factory.makeDistribution(owner=self.person)
            oci_project = self.factory.makeOCIProject(
                pillar=distro, registrant=self.person
            )
            [git_ref] = self.factory.makeGitRefs(
                paths=["refs/heads/v1.0-20.04"]
            )

            oci_project_url = api_url(oci_project)
            git_ref_url = api_url(git_ref)
            person_url = api_url(self.person)

        obj = {
            "name": "My recipe",
            "owner": person_url,
            "git_ref": git_ref_url,
            "build_file": "./Dockerfile",
            "description": "My recipe",
        }

        resp = self.webservice.named_post(oci_project_url, "newRecipe", **obj)
        self.assertEqual(401, resp.status, resp.body)

    def test_api_create_new_push_rule(self):
        """Can you create a new push rule for a recipe via the API?"""

        self.setConfig()

        with person_logged_in(self.person):
            oci_project = self.factory.makeOCIProject(registrant=self.person)
            recipe = self.factory.makeOCIRecipe(
                oci_project=oci_project,
                owner=self.person,
                registrant=self.person,
            )
            url = api_url(recipe)

        obj = {
            "registry_url": self.factory.getUniqueURL(),
            "image_name": self.factory.getUniqueUnicode(),
            "credentials": {"username": "foo", "password": "bar"},
        }

        resp = self.webservice.named_post(url, "newPushRule", **obj)
        self.assertEqual(201, resp.status, resp.body)

        new_obj_url = resp.getHeader("Location")
        ws_push_rule = self.load_from_api(new_obj_url)
        self.assertThat(
            ws_push_rule,
            ContainsDict(
                {
                    "image_name": Equals(obj["image_name"]),
                    "registry_url": Equals(obj["registry_url"]),
                    "username": Equals("foo"),
                }
            ),
        )

    def test_api_create_new_push_rule_distribution_credentials(self):
        """Should not be able to create a push rule in a Distribution."""

        self.setConfig()

        with person_logged_in(self.person):
            distribution = self.factory.makeDistribution()
            credentials = self.factory.makeOCIRegistryCredentials()
            project = self.factory.makeOCIProject(
                pillar=distribution, registrant=self.person
            )
            recipe = self.factory.makeOCIRecipe(
                oci_project=project, owner=self.person, registrant=self.person
            )
            with person_logged_in(distribution.owner):
                distribution.oci_registry_credentials = credentials
                project.setOfficialRecipeStatus(recipe, True)
            url = api_url(recipe)

        obj = {
            "registry_url": self.factory.getUniqueURL(),
            "image_name": self.factory.getUniqueUnicode(),
            "credentials": {"username": "foo", "password": "bar"},
        }

        resp = self.webservice.named_post(url, "newPushRule", **obj)
        self.assertEqual(400, resp.status, resp.body)

    def test_api_push_rules_exported(self):
        """Are push rules exported for a recipe?"""
        self.setConfig()

        image_name = self.factory.getUniqueUnicode()

        with person_logged_in(self.person):
            oci_project = self.factory.makeOCIProject(registrant=self.person)
            recipe = self.factory.makeOCIRecipe(
                oci_project=oci_project,
                owner=self.person,
                registrant=self.person,
            )
            self.factory.makeOCIPushRule(recipe=recipe, image_name=image_name)
            url = api_url(recipe)

        ws_recipe = self.load_from_api(url)
        push_rules = self.load_from_api(
            ws_recipe["push_rules_collection_link"]
        )
        self.assertEqual(image_name, push_rules["entries"][0]["image_name"])

    def test_api_set_image_name(self):
        """Can you set and retrieve the image name via the API?"""
        self.setConfig()

        image_name = self.factory.getUniqueUnicode()

        with person_logged_in(self.person):
            oci_project = self.factory.makeOCIProject(registrant=self.person)
            recipe = self.factory.makeOCIRecipe(
                oci_project=oci_project,
                owner=self.person,
                registrant=self.person,
            )
            url = api_url(recipe)

        resp = self.webservice.patch(
            url, "application/json", json.dumps({"image_name": image_name})
        )

        self.assertEqual(209, resp.status, resp.body)

        ws_project = self.load_from_api(url)
        self.assertEqual(image_name, ws_project["image_name"])


class TestOCIRecipeAsyncWebservice(TestCaseWithFactory):
    layer = LaunchpadFunctionalLayer

    def setUp(self):
        super().setUp()
        self.person = self.factory.makePerson(displayname="Test Person")
        self.webservice = webservice_for_person(
            self.person,
            permission=OAuthPermission.WRITE_PUBLIC,
            default_api_version="devel",
        )
        self.useFixture(FeatureFixture({OCI_RECIPE_ALLOW_CREATE: "on"}))

    def getDistroArchSeries(
        self, distroseries, proc_name="386", arch_tag="i386"
    ):
        processor = getUtility(IProcessorSet).getByName(proc_name)

        das = self.factory.makeDistroArchSeries(
            distroseries=distroseries,
            architecturetag=arch_tag,
            processor=processor,
        )
        fake_chroot = self.factory.makeLibraryFileAlias(
            filename="fake_chroot.tar.gz", db_only=True
        )
        das.addOrUpdateChroot(fake_chroot)
        return das

    def prepareArchSeries(self, ocirecipe):
        distro = ocirecipe.oci_project.distribution
        series = self.factory.makeDistroSeries(
            distribution=distro, status=SeriesStatus.CURRENT
        )

        return [
            self.getDistroArchSeries(series, "386", "386"),
            self.getDistroArchSeries(series, "hppa", "hppa"),
        ]

    def test_requestBuilds_creates_builds(self):
        with person_logged_in(self.person):
            distro = self.factory.makeDistribution(owner=self.person)
            oci_project = self.factory.makeOCIProject(
                registrant=self.person, pillar=distro
            )
            oci_recipe = self.factory.makeOCIRecipe(
                oci_project=oci_project,
                require_virtualized=False,
                owner=self.person,
                registrant=self.person,
            )
            distro_arch_series = self.prepareArchSeries(oci_recipe)
            recipe_url = api_url(oci_recipe)

        response = self.webservice.named_post(recipe_url, "requestBuilds")
        self.assertEqual(201, response.status, response.body)

        with admin_logged_in():
            [job] = getUtility(IOCIRecipeRequestBuildsJobSource).iterReady()
            with dbuser(config.IOCIRecipeRequestBuildsJobSource.dbuser):
                JobRunner([job]).runAll()

        build_request_url = response.getHeader("Location")
        job_id = int(build_request_url.split("/")[-1])

        fmt_date = lambda x: x if x is None else x.isoformat()
        abs_url = lambda x: self.webservice.getAbsoluteUrl(api_url(x))

        ws_build_request = self.webservice.get(build_request_url).jsonBody()
        with person_logged_in(self.person):
            build_request = oci_recipe.getBuildRequest(job_id)

            self.assertThat(
                ws_build_request,
                ContainsDict(
                    dict(
                        recipe_link=Equals(abs_url(build_request.recipe)),
                        status=Equals(
                            OCIRecipeBuildRequestStatus.COMPLETED.title
                        ),
                        date_requested=Equals(
                            fmt_date(build_request.date_requested)
                        ),
                        date_finished=Equals(
                            fmt_date(build_request.date_finished)
                        ),
                        error_message=Equals(build_request.error_message),
                        builds_collection_link=Equals(
                            build_request_url + "/builds"
                        ),
                    )
                ),
            )

        # Checks the structure of OCI recipe build objects created.
        builds = self.webservice.get(
            ws_build_request["builds_collection_link"]
        ).jsonBody()["entries"]
        with person_logged_in(self.person):
            self.assertThat(
                builds,
                MatchesSetwise(
                    *[
                        ContainsDict(
                            {
                                "recipe_link": Equals(abs_url(oci_recipe)),
                                "requester_link": Equals(abs_url(self.person)),
                                "buildstate": Equals("Needs building"),
                                "eta": IsInstance(str, type(None)),
                                "date": IsInstance(str, type(None)),
                                "estimate": IsInstance(bool),
                                "distro_arch_series_link": Equals(
                                    abs_url(arch_series)
                                ),
                                "registry_upload_status": Equals(
                                    "Unscheduled"
                                ),
                                "title": Equals(
                                    "%s build of %s"
                                    % (
                                        arch_series.processor.name,
                                        api_url(oci_recipe),
                                    )
                                ),
                                "score": IsInstance(int),
                                "can_be_rescored": Equals(True),
                                "can_be_cancelled": Equals(True),
                            }
                        )
                        for arch_series in distro_arch_series
                    ]
                ),
            )
