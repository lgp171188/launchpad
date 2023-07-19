# Copyright 2015-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import transaction
from storm.store import Store
from testtools.matchers import Equals, GreaterThan, HasLength
from zope.component import getUtility
from zope.security.checker import getChecker
from zope.security.proxy import removeSecurityProxy

from lp.app.enums import InformationType
from lp.charms.interfaces.charmrecipe import (
    CHARM_RECIPE_ALLOW_CREATE,
    CHARM_RECIPE_WEBHOOKS_FEATURE_FLAG,
)
from lp.oci.interfaces.ocirecipe import OCI_RECIPE_ALLOW_CREATE
from lp.registry.enums import BranchSharingPolicy
from lp.services.database.interfaces import IStore
from lp.services.features.testing import FeatureFixture
from lp.services.webapp.authorization import check_permission
from lp.services.webapp.snapshot import notify_modified
from lp.services.webhooks.interfaces import IWebhookSet
from lp.services.webhooks.model import (
    WebhookJob,
    WebhookSet,
    check_webhook_git_ref_pattern,
)
from lp.soyuz.interfaces.livefs import (
    LIVEFS_FEATURE_FLAG,
    LIVEFS_WEBHOOKS_FEATURE_FLAG,
)
from lp.testing import (
    ExpectedException,
    StormStatementRecorder,
    TestCaseWithFactory,
    admin_logged_in,
    anonymous_logged_in,
    login_person,
    person_logged_in,
)
from lp.testing.layers import DatabaseFunctionalLayer
from lp.testing.matchers import HasQueryCount


class TestWebhook(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_modifiedevent_sets_date_last_modified(self):
        # When a Webhook receives an object modified event, the last modified
        # date is set to UTC_NOW.
        webhook = self.factory.makeWebhook()
        transaction.commit()
        with admin_logged_in():
            old_mtime = webhook.date_last_modified
        with notify_modified(webhook, ["delivery_url"]):
            pass
        with admin_logged_in():
            self.assertThat(webhook.date_last_modified, GreaterThan(old_mtime))

    def test_event_types(self):
        # Webhook.event_types is a list of event type strings.
        webhook = self.factory.makeWebhook()
        with admin_logged_in():
            self.assertContentEqual([], webhook.event_types)
            webhook.event_types = ["foo", "bar"]
            self.assertContentEqual(["foo", "bar"], webhook.event_types)

    def test_event_types_bad_structure(self):
        # It's not possible to set Webhook.event_types to a list of the
        # wrong type.
        webhook = self.factory.makeWebhook()
        with admin_logged_in():
            self.assertContentEqual([], webhook.event_types)
            with ExpectedException(AssertionError, ".*"):
                webhook.event_types = ["foo", [1]]
            self.assertContentEqual([], webhook.event_types)

    def test_check_webhook_git_ref_pattern(self):
        # See lib/lp/code/templates/gitrepository-permissions.pt for an
        # explanation of the wildcards logic
        git_ref = "refs/heads/foo-test"
        expected_results = {
            None: True,
            "": True,
            "*": True,
            "*foo*": True,
            "foo": False,
            "foo-test": False,  # it needs to match the full git ref
            "foo*": False,
            "*foo": False,
            "*foo?test": True,
            "*foo[-_.]test": True,
            "*foo![-]test": False,
            "*bar*": False,
            "refs/heads/*": True,  # this should match all branches (not tags)
            "refs/heads/foo*": True,
            "refs/heads/bar*": False,
            "refs/heads/*-test": True,
        }

        results = dict()
        webhook = self.factory.makeWebhook()
        with admin_logged_in():
            for pattern in expected_results:
                webhook.git_ref_pattern = pattern
                results[pattern] = check_webhook_git_ref_pattern(
                    webhook, git_ref
                )

        self.assertEqual(expected_results, results)


class TestWebhookPermissions(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def get_target_owner(self, target):
        return target.owner

    def test_target_owner_can_view(self):
        target = self.factory.makeGitRepository()
        webhook = self.factory.makeWebhook(target=target)
        with person_logged_in(self.get_target_owner(target)):
            self.assertTrue(check_permission("launchpad.View", webhook))

    def test_random_cannot_view(self):
        webhook = self.factory.makeWebhook()
        with person_logged_in(self.factory.makePerson()):
            self.assertFalse(check_permission("launchpad.View", webhook))

    def test_anonymous_cannot_view(self):
        webhook = self.factory.makeWebhook()
        with anonymous_logged_in():
            self.assertFalse(check_permission("launchpad.View", webhook))

    def test_get_permissions(self):
        expected_get_permissions = {
            "launchpad.View": {
                "active",
                "date_created",
                "date_last_modified",
                "deliveries",
                "delivery_url",
                "destroySelf",
                "event_types",
                "getDelivery",
                "id",
                "ping",
                "registrant",
                "registrant_id",
                "secret",
                "setSecret",
                "target",
                "git_ref_pattern",
            },
        }
        webhook = self.factory.makeWebhook()
        checker = getChecker(webhook)
        self.checkPermissions(
            expected_get_permissions, checker.get_permissions, "get"
        )

    def test_set_permissions(self):
        expected_set_permissions = {
            "launchpad.View": {
                "active",
                "delivery_url",
                "event_types",
                "registrant_id",
                "secret",
                "git_ref_pattern",
            },
        }
        webhook = self.factory.makeWebhook()
        checker = getChecker(webhook)
        self.checkPermissions(
            expected_set_permissions, checker.set_permissions, "set"
        )


class TestWebhookSetBase:
    layer = DatabaseFunctionalLayer

    def get_target_owner(self, target):
        return target.owner

    def test_new(self):
        target = self.makeTarget()
        login_person(self.get_target_owner(target))
        person = self.factory.makePerson()
        hook = getUtility(IWebhookSet).new(
            target,
            person,
            "http://path/to/something",
            [self.event_type],
            True,
            "sekrit",
        )
        Store.of(hook).flush()
        self.assertEqual(target, hook.target)
        self.assertEqual(person, hook.registrant)
        self.assertIsNot(None, hook.date_created)
        self.assertEqual(hook.date_created, hook.date_last_modified)
        self.assertEqual("http://path/to/something", hook.delivery_url)
        self.assertEqual(True, hook.active)
        self.assertEqual("sekrit", hook.secret)
        self.assertEqual([self.event_type], hook.event_types)

    def test_getByID(self):
        hook1 = self.factory.makeWebhook()
        hook2 = self.factory.makeWebhook()
        with admin_logged_in():
            self.assertEqual(hook1, getUtility(IWebhookSet).getByID(hook1.id))
            self.assertEqual(hook2, getUtility(IWebhookSet).getByID(hook2.id))
            self.assertIs(None, getUtility(IWebhookSet).getByID(1234))

    def test_findByTarget(self):
        target1 = self.makeTarget()
        target2 = self.makeTarget()
        for target, name in ((target1, "one"), (target2, "two")):
            for i in range(3):
                self.factory.makeWebhook(
                    target, "http://path/%s/%d" % (name, i)
                )
        with person_logged_in(self.get_target_owner(target1)):
            self.assertContentEqual(
                [
                    "http://path/one/0",
                    "http://path/one/1",
                    "http://path/one/2",
                ],
                [
                    hook.delivery_url
                    for hook in getUtility(IWebhookSet).findByTarget(target1)
                ],
            )
        with person_logged_in(self.get_target_owner(target2)):
            self.assertContentEqual(
                [
                    "http://path/two/0",
                    "http://path/two/1",
                    "http://path/two/2",
                ],
                [
                    hook.delivery_url
                    for hook in getUtility(IWebhookSet).findByTarget(target2)
                ],
            )

    def test_delete(self):
        target = self.makeTarget()
        login_person(self.get_target_owner(target))
        hooks = []
        for i in range(3):
            hook = self.factory.makeWebhook(target, "http://path/to/%d" % i)
            hook.ping()
            hooks.append(hook)
        self.assertEqual(3, IStore(WebhookJob).find(WebhookJob).count())
        self.assertContentEqual(
            ["http://path/to/0", "http://path/to/1", "http://path/to/2"],
            [
                hook.delivery_url
                for hook in getUtility(IWebhookSet).findByTarget(target)
            ],
        )

        transaction.commit()
        with StormStatementRecorder() as recorder:
            getUtility(IWebhookSet).delete(hooks[:2])
        self.assertThat(recorder, HasQueryCount(Equals(4)))

        self.assertContentEqual(
            ["http://path/to/2"],
            [
                hook.delivery_url
                for hook in getUtility(IWebhookSet).findByTarget(target)
            ],
        )
        self.assertEqual(1, IStore(WebhookJob).find(WebhookJob).count())
        self.assertEqual(1, hooks[2].deliveries.count())

    def test__checkVisibility_public_artifact(self):
        target = self.makeTarget()
        self.assertTrue(
            WebhookSet._checkVisibility(target, self.get_target_owner(target))
        )

    def test_trigger(self):
        owner = self.factory.makePerson()
        target1 = self.makeTarget(owner=owner)
        target2 = self.makeTarget(owner=owner)
        hook1a = self.factory.makeWebhook(target=target1, event_types=[])
        hook1b = self.factory.makeWebhook(
            target=target1, event_types=[self.event_type]
        )
        hook2a = self.factory.makeWebhook(
            target=target2, event_types=[self.event_type]
        )
        hook2b = self.factory.makeWebhook(
            target=target2, event_types=[self.event_type], active=False
        )

        # Only webhooks subscribed to the relevant target and event type
        # are triggered.
        getUtility(IWebhookSet).trigger(
            target1, self.event_type, {"some": "payload"}
        )
        with admin_logged_in():
            self.assertThat(list(hook1a.deliveries), HasLength(0))
            self.assertThat(list(hook1b.deliveries), HasLength(1))
            self.assertThat(list(hook2a.deliveries), HasLength(0))
            self.assertThat(list(hook2b.deliveries), HasLength(0))
            delivery = hook1b.deliveries.one()
            self.assertEqual(delivery.payload, {"some": "payload"})

        # Disabled webhooks aren't triggered.
        getUtility(IWebhookSet).trigger(
            target2, self.event_type, {"other": "payload"}
        )
        with admin_logged_in():
            self.assertThat(list(hook1a.deliveries), HasLength(0))
            self.assertThat(list(hook1b.deliveries), HasLength(1))
            self.assertThat(list(hook2a.deliveries), HasLength(1))
            self.assertThat(list(hook2b.deliveries), HasLength(0))
            delivery = hook2a.deliveries.one()
            self.assertEqual(delivery.payload, {"other": "payload"})


class TestWebhookSetMergeProposalBase(TestWebhookSetBase):
    def test__checkVisibility_private_artifact(self):
        owner = self.factory.makePerson()
        target = self.makeTarget(
            owner=owner, information_type=InformationType.PROPRIETARY
        )
        self.assertTrue(WebhookSet._checkVisibility(target, owner))

    def test__checkVisibility_private_artifact_team_owned(self):
        owner = self.factory.makeTeam()
        target = self.makeTarget(
            owner=owner, information_type=InformationType.PROPRIETARY
        )
        self.assertTrue(WebhookSet._checkVisibility(target, owner))

    def test__checkVisibility_lost_access_to_private_artifact(self):
        # A user may lose access to a private artifact even if they own it,
        # for example if they leave the team that has a policy grant for
        # branches on that project; in such cases they should stop receiving
        # webhooks.
        project = self.factory.makeProduct(
            branch_sharing_policy=BranchSharingPolicy.PROPRIETARY
        )
        grantee_team = self.factory.makeTeam()
        policy = self.factory.makeAccessPolicy(
            pillar=project, check_existing=True
        )
        self.factory.makeAccessPolicyGrant(policy=policy, grantee=grantee_team)
        grantee_member = self.factory.makePerson(member_of=[grantee_team])
        target = self.makeTarget(owner=grantee_member, project=project)
        self.assertTrue(WebhookSet._checkVisibility(target, grantee_member))
        with person_logged_in(grantee_member):
            grantee_member.leave(grantee_team)
        self.assertFalse(WebhookSet._checkVisibility(target, grantee_member))

    def test__checkVisibility_with_different_context(self):
        project = self.factory.makeProduct(
            branch_sharing_policy=BranchSharingPolicy.PUBLIC_OR_PROPRIETARY
        )
        owner = self.factory.makePerson()
        source = self.makeTarget(
            owner=owner,
            project=project,
            information_type=InformationType.PROPRIETARY,
        )
        reviewer = self.factory.makePerson()
        mp1 = self.makeMergeProposal(
            owner=owner, project=project, source=source, reviewer=reviewer
        )
        mp2 = self.makeMergeProposal(
            project=project, source=source, reviewer=reviewer
        )
        self.assertTrue(
            WebhookSet._checkVisibility(mp1, mp1.merge_target.owner)
        )
        self.assertFalse(
            WebhookSet._checkVisibility(mp2, mp2.merge_target.owner)
        )

    def test_trigger_skips_invisible(self):
        # No webhooks are dispatched if the visibility check fails.
        project = self.factory.makeProduct(
            branch_sharing_policy=BranchSharingPolicy.PUBLIC_OR_PROPRIETARY
        )
        owner = self.factory.makePerson()
        source = self.makeTarget(
            owner=owner,
            project=project,
            information_type=InformationType.PROPRIETARY,
        )
        target1 = self.makeTarget(project=project)
        target2 = self.makeTarget(owner=owner, project=project)
        reviewer = self.factory.makePerson()
        mp1 = self.makeMergeProposal(
            owner=owner, target=target1, source=source, reviewer=reviewer
        )
        mp2 = self.makeMergeProposal(
            owner=owner, target=target2, source=source, reviewer=reviewer
        )
        event_type = "merge-proposal:0.1"
        hook1 = self.factory.makeWebhook(
            target=target1, event_types=[event_type]
        )
        hook2 = self.factory.makeWebhook(
            target=target2, event_types=[event_type]
        )

        # The owner of target1 cannot see source and hence cannot see mp1,
        # so their webhook is kept in the dark too.
        getUtility(IWebhookSet).trigger(
            target1, event_type, {"some": "payload"}, context=mp1
        )
        with admin_logged_in():
            self.assertThat(list(hook1.deliveries), HasLength(0))
            self.assertThat(list(hook2.deliveries), HasLength(0))

        # The owner of target2 can see source and mp2, so it's OK to tell
        # their webhook about the existence of source.
        getUtility(IWebhookSet).trigger(
            target2, event_type, {"some": "payload"}, context=mp2
        )
        with admin_logged_in():
            self.assertThat(list(hook1.deliveries), HasLength(0))
            self.assertThat(list(hook2.deliveries), HasLength(1))
            delivery = hook2.deliveries.one()
            self.assertEqual(delivery.payload, {"some": "payload"})

    def test_trigger_different_source_and_target_owners(self):
        # Only people who can edit the webhook target can view the webhook,
        # so, for a merge proposal between two branches with different
        # owners, the owner of the merge source will in general not be able
        # to see a webhook attached to the target.  trigger copes with this.
        project = self.factory.makeProduct()
        source = self.makeTarget(project=project)
        target = self.makeTarget(project=project)
        mp = self.makeMergeProposal(target=target, source=source)
        event_type = "merge-proposal:0.1"
        hook = self.factory.makeWebhook(
            target=target, event_types=[event_type]
        )
        getUtility(IWebhookSet).trigger(
            target, event_type, {"some": "payload"}, context=mp
        )
        with admin_logged_in():
            self.assertThat(list(hook.deliveries), HasLength(1))
            delivery = hook.deliveries.one()
            self.assertEqual(delivery.payload, {"some": "payload"})


class TestWebhookSetGitRepository(
    TestWebhookSetMergeProposalBase, TestCaseWithFactory
):
    event_type = "git:push:0.1"

    def makeTarget(self, project=None, **kwargs):
        return self.factory.makeGitRepository(target=project, **kwargs)

    def makeMergeProposal(
        self, target=None, source=None, reviewer=None, **kwargs
    ):
        if target is None:
            target = self.makeTarget(**kwargs)
        [target_ref] = self.factory.makeGitRefs(repository=target)
        if source is None:
            source = self.makeTarget(**kwargs)
        [source_ref] = self.factory.makeGitRefs(repository=source)
        owner = removeSecurityProxy(source).owner
        with person_logged_in(owner):
            return self.factory.makeBranchMergeProposalForGit(
                registrant=owner,
                target_ref=target_ref,
                source_ref=source_ref,
                reviewer=reviewer,
            )


class TestWebhookSetBranch(
    TestWebhookSetMergeProposalBase, TestCaseWithFactory
):
    event_type = "bzr:push:0.1"

    def makeTarget(self, project=None, **kwargs):
        return self.factory.makeBranch(product=project, **kwargs)

    def makeMergeProposal(
        self, target=None, source=None, reviewer=None, **kwargs
    ):
        if target is None:
            target = self.makeTarget(**kwargs)
        if source is None:
            source = self.makeTarget(**kwargs)
        owner = removeSecurityProxy(source).owner
        with person_logged_in(owner):
            return self.factory.makeBranchMergeProposal(
                registrant=owner,
                target_branch=target,
                source_branch=source,
                reviewer=reviewer,
            )


class TestWebhookSetSnap(TestWebhookSetBase, TestCaseWithFactory):
    event_type = "snap:build:0.1"

    def makeTarget(self, owner=None, **kwargs):
        if owner is None:
            owner = self.factory.makePerson()
        return self.factory.makeSnap(registrant=owner, owner=owner, **kwargs)


class TestWebhookSetLiveFS(TestWebhookSetBase, TestCaseWithFactory):
    event_type = "livefs:build:0.1"

    def makeTarget(self, owner=None, **kwargs):
        if owner is None:
            owner = self.factory.makePerson()

        with FeatureFixture(
            {LIVEFS_FEATURE_FLAG: "on", LIVEFS_WEBHOOKS_FEATURE_FLAG: "on"}
        ):
            return self.factory.makeLiveFS(
                registrant=owner, owner=owner, **kwargs
            )


class TestWebhookSetOCIRecipe(TestWebhookSetBase, TestCaseWithFactory):
    event_type = "oci-recipe:build:0.1"

    def makeTarget(self, owner=None, **kwargs):
        if owner is None:
            owner = self.factory.makePerson()

        with FeatureFixture({OCI_RECIPE_ALLOW_CREATE: "on"}):
            return self.factory.makeOCIRecipe(
                registrant=owner, owner=owner, **kwargs
            )


class TestWebhookSetCharmRecipe(TestWebhookSetBase, TestCaseWithFactory):
    event_type = "charm-recipe:build:0.1"

    def makeTarget(self, owner=None, **kwargs):
        if owner is None:
            owner = self.factory.makePerson()

        with FeatureFixture(
            {
                CHARM_RECIPE_WEBHOOKS_FEATURE_FLAG: "on",
                CHARM_RECIPE_ALLOW_CREATE: "on",
            }
        ):
            return self.factory.makeCharmRecipe(
                registrant=owner, owner=owner, **kwargs
            )


class TestWebhookSetBugBase(TestWebhookSetBase):
    event_type = "bug:0.1"

    def test__checkVisibility_private_artifact(self):
        owner = self.factory.makePerson()
        target = self.makeTarget(
            owner=owner, information_type=InformationType.PROPRIETARY
        )
        self.assertTrue(WebhookSet._checkVisibility(target, owner))

    def test_webhook_trigger_private_target(self):
        owner = self.factory.makePerson()
        target = self.makeTarget(
            owner=owner,
            information_type=InformationType.PROPRIETARY,
        )
        hook = self.factory.makeWebhook(
            target=target, event_types=[self.event_type]
        )

        with admin_logged_in():
            self.assertThat(list(hook.deliveries), HasLength(0))

        getUtility(IWebhookSet).trigger(
            target, self.event_type, {"some": "payload"}
        )
        with admin_logged_in():
            self.assertThat(list(hook.deliveries), HasLength(1))
            delivery = hook.deliveries.one()
            self.assertEqual(delivery.payload, {"some": "payload"})


class TestWebhookSetProductBugUpdate(
    TestWebhookSetBugBase, TestCaseWithFactory
):
    def makeTarget(self, **kwargs):
        return self.factory.makeProduct(**kwargs)


class TestWebhookSetDistributionBugUpdate(
    TestWebhookSetBugBase, TestCaseWithFactory
):
    def makeTarget(self, **kwargs):
        return self.factory.makeDistribution(**kwargs)


class TestWebhookSetDistributionSourcePackageBugUpdate(
    TestWebhookSetBugBase, TestCaseWithFactory
):
    def get_target_owner(self, target):
        return target.distribution.owner

    def makeTarget(self, **kwargs):
        with admin_logged_in():
            distribution = self.factory.makeDistribution(**kwargs)
            return self.factory.makeDistributionSourcePackage(
                distribution=distribution
            )
