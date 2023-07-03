# Copyright 2009-2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Webservice unit tests related to Launchpad blueprints."""

import json

import iso8601
from testtools.matchers import (
    AfterPreprocessing,
    ContainsDict,
    Equals,
    MatchesListwise,
)
from zope.component import getUtility

from lp.app.enums import InformationType
from lp.app.interfaces.launchpad import ILaunchpadCelebrities
from lp.blueprints.enums import SpecificationDefinitionStatus
from lp.registry.enums import SpecificationSharingPolicy
from lp.services.webapp.interaction import ANONYMOUS
from lp.services.webapp.interfaces import OAuthPermission
from lp.testing import (
    TestCaseWithFactory,
    admin_logged_in,
    api_url,
    login,
    person_logged_in,
)
from lp.testing.layers import DatabaseFunctionalLayer
from lp.testing.pages import webservice_for_person


class SpecificationWebserviceTests(TestCaseWithFactory):
    """Test accessing specification top-level webservice."""

    layer = DatabaseFunctionalLayer

    def test_collection(self):
        # `ISpecificationSet` is exposed as a webservice via /specs
        # and is represented by an empty collection.
        user = self.factory.makePerson()
        webservice = webservice_for_person(user)
        response = webservice.get("/specs")
        self.assertEqual(200, response.status)
        self.assertEqual(
            ["entries", "resource_type_link", "start", "total_size"],
            sorted(response.jsonBody().keys()),
        )
        self.assertEqual(0, response.jsonBody()["total_size"])

    def test_creation_for_products(self):
        # `ISpecificationSet.createSpecification` is exposed and
        # allows specification creation for products.
        user = self.factory.makePerson()
        product = self.factory.makeProduct()
        product_url = api_url(product)
        webservice = webservice_for_person(
            user, permission=OAuthPermission.WRITE_PUBLIC
        )
        response = webservice.named_post(
            "/specs",
            "createSpecification",
            name="test-prod",
            title="Product",
            specurl="http://test.com",
            definition_status="Approved",
            summary="A summary",
            target=product_url,
            api_version="devel",
        )
        self.assertEqual(201, response.status)

    def test_creation_honor_product_sharing_policy(self):
        # `ISpecificationSet.createSpecification` respect product
        # specification_sharing_policy.
        user = self.factory.makePerson()
        product = self.factory.makeProduct(
            owner=user,
            specification_sharing_policy=(
                SpecificationSharingPolicy.PROPRIETARY
            ),
        )
        product_url = api_url(product)
        webservice = webservice_for_person(
            user, permission=OAuthPermission.WRITE_PRIVATE
        )
        spec_name = "test-prop"
        response = webservice.named_post(
            "/specs",
            "createSpecification",
            name=spec_name,
            title="Proprietary",
            specurl="http://test.com",
            definition_status="Approved",
            summary="A summary",
            target=product_url,
            api_version="devel",
        )
        self.assertEqual(201, response.status)
        # The new specification was created as PROPROETARY.
        response = webservice.get("%s/+spec/%s" % (product_url, spec_name))
        self.assertEqual(200, response.status)
        self.assertEqual(
            "Proprietary", response.jsonBody()["information_type"]
        )

    def test_creation_for_distribution(self):
        # `ISpecificationSet.createSpecification` also allows
        # specification creation for distributions.
        user = self.factory.makePerson()
        distribution = self.factory.makeDistribution()
        distribution_url = api_url(distribution)
        webservice = webservice_for_person(
            user, permission=OAuthPermission.WRITE_PUBLIC
        )
        response = webservice.named_post(
            "/specs",
            "createSpecification",
            name="test-distro",
            title="Distro",
            specurl="http://test.com",
            definition_status="Approved",
            summary="A summary",
            target=distribution_url,
            api_version="devel",
        )
        self.assertEqual(201, response.status)


class SpecificationAttributeWebserviceTests(TestCaseWithFactory):
    """Test accessing specification attributes over the webservice."""

    layer = DatabaseFunctionalLayer

    def test_representation_is_empty_on_1_dot_0(self):
        # ISpecification is exposed on the 1.0 version so that they can be
        # linked against branches, but none of its fields is exposed on that
        # version as we expect it to undergo significant refactorings before
        # it's ready for prime time.
        spec = self.factory.makeSpecification()
        user = self.factory.makePerson()
        url = "/%s/+spec/%s" % (spec.product.name, spec.name)
        webservice = webservice_for_person(user)
        response = webservice.get(url)
        expected_keys = [
            "self_link",
            "http_etag",
            "resource_type_link",
            "web_link",
            "information_type",
        ]
        self.assertEqual(response.status, 200)
        self.assertContentEqual(expected_keys, response.jsonBody().keys())

    def test_representation_basics(self):
        spec = self.factory.makeSpecification()
        spec_url = api_url(spec)
        webservice = webservice_for_person(
            spec.owner, default_api_version="devel"
        )
        response = webservice.get(spec_url)
        self.assertEqual(200, response.status)
        with person_logged_in(ANONYMOUS):
            self.assertThat(
                response.jsonBody(),
                ContainsDict(
                    {
                        "name": Equals(spec.name),
                        "title": Equals(spec.title),
                        "specification_url": Equals(spec.specurl),
                        "summary": Equals(spec.summary),
                        "implementation_status": Equals(
                            spec.implementation_status.title
                        ),
                        "definition_status": Equals(
                            spec.definition_status.title
                        ),
                        "priority": Equals(spec.priority.title),
                        "date_created": AfterPreprocessing(
                            iso8601.parse_date, Equals(spec.datecreated)
                        ),
                        "whiteboard": Equals(spec.whiteboard),
                        "workitems_text": Equals(spec.workitems_text),
                    }
                ),
            )

    def test_representation_contains_target(self):
        spec = self.factory.makeSpecification(
            product=self.factory.makeProduct()
        )
        spec_url = api_url(spec)
        spec_target_url = api_url(spec.target)
        webservice = webservice_for_person(
            spec.owner, default_api_version="devel"
        )
        response = webservice.get(spec_url)
        self.assertEqual(200, response.status)
        self.assertEndsWith(
            response.jsonBody()["target_link"], spec_target_url
        )

    def test_representation_contains_assignee(self):
        spec = self.factory.makeSpecification(
            assignee=self.factory.makePerson()
        )
        spec_url = api_url(spec)
        spec_assignee_url = api_url(spec.assignee)
        webservice = webservice_for_person(
            spec.owner, default_api_version="devel"
        )
        response = webservice.get(spec_url)
        self.assertEqual(200, response.status)
        self.assertEndsWith(
            response.jsonBody()["assignee_link"], spec_assignee_url
        )

    def test_representation_contains_drafter(self):
        spec = self.factory.makeSpecification(
            drafter=self.factory.makePerson()
        )
        spec_url = api_url(spec)
        spec_drafter_url = api_url(spec.drafter)
        webservice = webservice_for_person(
            spec.owner, default_api_version="devel"
        )
        response = webservice.get(spec_url)
        self.assertEqual(200, response.status)
        self.assertEndsWith(
            response.jsonBody()["drafter_link"], spec_drafter_url
        )

    def test_representation_contains_approver(self):
        spec = self.factory.makeSpecification(
            approver=self.factory.makePerson()
        )
        spec_url = api_url(spec)
        spec_approver_url = api_url(spec.approver)
        webservice = webservice_for_person(
            spec.owner, default_api_version="devel"
        )
        response = webservice.get(spec_url)
        self.assertEqual(200, response.status)
        self.assertEndsWith(
            response.jsonBody()["approver_link"], spec_approver_url
        )

    def test_representation_contains_owner(self):
        spec = self.factory.makeSpecification(owner=self.factory.makePerson())
        spec_url = api_url(spec)
        spec_owner_url = api_url(spec.owner)
        webservice = webservice_for_person(
            spec.owner, default_api_version="devel"
        )
        response = webservice.get(spec_url)
        self.assertEqual(200, response.status)
        self.assertEndsWith(response.jsonBody()["owner_link"], spec_owner_url)

    def test_representation_contains_milestone(self):
        product = self.factory.makeProduct()
        productseries = self.factory.makeProductSeries(product=product)
        milestone = self.factory.makeMilestone(
            product=product, productseries=productseries
        )
        milestone_url = api_url(milestone)
        spec_object = self.factory.makeSpecification(
            product=product, goal=productseries, milestone=milestone
        )
        spec_object_url = api_url(spec_object)
        webservice = webservice_for_person(
            spec_object.owner, default_api_version="devel"
        )
        response = webservice.get(spec_object_url)
        self.assertEqual(200, response.status)
        self.assertEndsWith(
            response.jsonBody()["milestone_link"], milestone_url
        )

    def test_representation_contains_dependencies(self):
        spec = self.factory.makeSpecification()
        spec2 = self.factory.makeSpecification()
        spec2_name = spec2.name
        spec.createDependency(spec2)
        spec_url = api_url(spec)
        webservice = webservice_for_person(
            spec.owner, default_api_version="devel"
        )
        response = webservice.get(spec_url)
        self.assertEqual(200, response.status)
        response = webservice.get(
            response.jsonBody()["dependencies_collection_link"]
        )
        self.assertEqual(200, response.status)
        self.assertThat(
            response.jsonBody(),
            ContainsDict(
                {
                    "total_size": Equals(1),
                    "entries": MatchesListwise(
                        [
                            ContainsDict({"name": Equals(spec2_name)}),
                        ]
                    ),
                }
            ),
        )

    def test_representation_contains_linked_branches(self):
        spec = self.factory.makeSpecification()
        branch = self.factory.makeBranch()
        person = self.factory.makePerson()
        spec.linkBranch(branch, person)
        spec_url = api_url(spec)
        webservice = webservice_for_person(
            spec.owner, default_api_version="devel"
        )
        response = webservice.get(spec_url)
        self.assertEqual(200, response.status)
        response = webservice.get(
            response.jsonBody()["linked_branches_collection_link"]
        )
        self.assertEqual(200, response.status)
        self.assertEqual(1, response.jsonBody()["total_size"])

    def test_representation_contains_bug_links(self):
        spec = self.factory.makeSpecification()
        bug = self.factory.makeBug()
        person = self.factory.makePerson()
        with person_logged_in(person):
            spec.linkBug(bug)
        spec_url = api_url(spec)
        webservice = webservice_for_person(
            spec.owner, default_api_version="devel"
        )
        response = webservice.get(spec_url)
        self.assertEqual(200, response.status)
        response = webservice.get(response.jsonBody()["bugs_collection_link"])
        self.assertThat(
            response.jsonBody(),
            ContainsDict(
                {
                    "total_size": Equals(1),
                    "entries": MatchesListwise(
                        [ContainsDict({"id": Equals(bug.id)})]
                    ),
                }
            ),
        )


class SpecificationMutationTests(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_set_information_type(self):
        product = self.factory.makeProduct(
            specification_sharing_policy=(
                SpecificationSharingPolicy.PUBLIC_OR_PROPRIETARY
            )
        )
        spec = self.factory.makeSpecification(product=product)
        self.assertEqual(InformationType.PUBLIC, spec.information_type)
        spec_url = api_url(spec)
        webservice = webservice_for_person(
            product.owner, permission=OAuthPermission.WRITE_PRIVATE
        )
        response = webservice.patch(
            spec_url,
            "application/json",
            json.dumps(dict(information_type="Proprietary")),
            api_version="devel",
        )
        self.assertEqual(209, response.status)
        with admin_logged_in():
            self.assertEqual(
                InformationType.PROPRIETARY, spec.information_type
            )

    def test_set_target(self):
        old_target = self.factory.makeProduct()
        spec = self.factory.makeSpecification(product=old_target, name="foo")
        new_target = self.factory.makeProduct(displayname="Fooix")
        spec_url = api_url(spec)
        new_target_url = api_url(new_target)
        webservice = webservice_for_person(
            old_target.owner, permission=OAuthPermission.WRITE_PRIVATE
        )
        response = webservice.patch(
            spec_url,
            "application/json",
            json.dumps(dict(target_link=new_target_url)),
            api_version="devel",
        )
        self.assertEqual(301, response.status)
        with admin_logged_in():
            self.assertEqual(new_target, spec.target)

            # Moving another spec with the same name fails.
            other_spec = self.factory.makeSpecification(
                product=old_target, name="foo"
            )
            other_spec_url = api_url(other_spec)
        response = webservice.patch(
            other_spec_url,
            "application/json",
            json.dumps(dict(target_link=new_target_url)),
            api_version="devel",
        )
        self.assertEqual(400, response.status)
        self.assertEqual(
            b"There is already a blueprint named foo for Fooix.", response.body
        )


class SpecificationTargetTests(TestCaseWithFactory):
    """Tests for accessing specifications via their targets."""

    layer = DatabaseFunctionalLayer

    def test_get_specification_on_product(self):
        product = self.factory.makeProduct(name="fooix")
        self.factory.makeSpecification(product=product, name="some-spec")
        product_url = api_url(product)
        webservice = webservice_for_person(
            self.factory.makePerson(), default_api_version="devel"
        )
        response = webservice.named_get(
            product_url, "getSpecification", name="some-spec"
        )
        self.assertEqual(200, response.status)
        self.assertEqual("some-spec", response.jsonBody()["name"])
        response = webservice.get(response.jsonBody()["target_link"])
        self.assertEqual(200, response.status)
        self.assertEqual("fooix", response.jsonBody()["name"])

    def test_get_specification_on_distribution(self):
        distribution = self.factory.makeDistribution(name="foobuntu")
        self.factory.makeSpecification(
            distribution=distribution, name="some-spec"
        )
        distribution_url = api_url(distribution)
        webservice = webservice_for_person(
            self.factory.makePerson(), default_api_version="devel"
        )
        response = webservice.named_get(
            distribution_url, "getSpecification", name="some-spec"
        )
        self.assertEqual(200, response.status)
        self.assertEqual("some-spec", response.jsonBody()["name"])
        response = webservice.get(response.jsonBody()["target_link"])
        self.assertEqual(200, response.status)
        self.assertEqual("foobuntu", response.jsonBody()["name"])

    def test_get_specification_on_productseries(self):
        product = self.factory.makeProduct(name="fooix")
        productseries = self.factory.makeProductSeries(product=product)
        self.factory.makeSpecification(
            product=product, name="some-spec", goal=productseries
        )
        productseries_url = api_url(productseries)
        webservice = webservice_for_person(
            self.factory.makePerson(), default_api_version="devel"
        )
        response = webservice.named_get(
            productseries_url, "getSpecification", name="some-spec"
        )
        self.assertEqual(200, response.status)
        self.assertEqual("some-spec", response.jsonBody()["name"])
        response = webservice.get(response.jsonBody()["target_link"])
        self.assertEqual(200, response.status)
        self.assertEqual("fooix", response.jsonBody()["name"])

    def test_get_specification_on_distroseries(self):
        distribution = self.factory.makeDistribution(name="foobuntu")
        distroseries = self.factory.makeDistroSeries(distribution=distribution)
        self.factory.makeSpecification(
            distribution=distribution, name="some-spec", goal=distroseries
        )
        distroseries_url = api_url(distroseries)
        webservice = webservice_for_person(
            self.factory.makePerson(), default_api_version="devel"
        )
        response = webservice.named_get(
            distroseries_url, "getSpecification", name="some-spec"
        )
        self.assertEqual(200, response.status)
        self.assertEqual("some-spec", response.jsonBody()["name"])
        response = webservice.get(response.jsonBody()["target_link"])
        self.assertEqual(200, response.status)
        self.assertEqual("foobuntu", response.jsonBody()["name"])

    def test_get_specification_not_found(self):
        product = self.factory.makeProduct()
        product_url = api_url(product)
        webservice = webservice_for_person(
            self.factory.makePerson(), default_api_version="devel"
        )
        response = webservice.named_get(
            product_url, "getSpecification", name="nonexistent"
        )
        self.assertEqual(200, response.status)
        self.assertIsNone(response.jsonBody())


class IHasSpecificationsTests(TestCaseWithFactory):
    """Tests for accessing IHasSpecifications methods over the webservice."""

    layer = DatabaseFunctionalLayer

    def test_anonymous_access_to_collection(self):
        product = self.factory.makeProduct()
        self.factory.makeSpecification(product=product, name="spec1")
        self.factory.makeSpecification(product=product, name="spec2")
        product_url = api_url(product)
        webservice = webservice_for_person(None, default_api_version="devel")
        response = webservice.get(product_url)
        self.assertEqual(200, response.status)
        response = webservice.get(
            response.jsonBody()["all_specifications_collection_link"]
        )
        self.assertEqual(200, response.status)
        self.assertContentEqual(
            ["spec1", "spec2"],
            [entry["name"] for entry in response.jsonBody()["entries"]],
        )

    def test_product_all_specifications(self):
        product = self.factory.makeProduct()
        self.factory.makeSpecification(product=product, name="spec1")
        self.factory.makeSpecification(product=product, name="spec2")
        product_url = api_url(product)
        webservice = webservice_for_person(
            self.factory.makePerson(), default_api_version="devel"
        )
        response = webservice.get(product_url)
        self.assertEqual(200, response.status)
        response = webservice.get(
            response.jsonBody()["all_specifications_collection_link"]
        )
        self.assertEqual(200, response.status)
        self.assertContentEqual(
            ["spec1", "spec2"],
            [entry["name"] for entry in response.jsonBody()["entries"]],
        )

    def test_distribution_valid_specifications(self):
        distribution = self.factory.makeDistribution()
        self.factory.makeSpecification(distribution=distribution, name="spec1")
        self.factory.makeSpecification(
            distribution=distribution,
            name="spec2",
            status=SpecificationDefinitionStatus.OBSOLETE,
        )
        distribution_url = api_url(distribution)
        webservice = webservice_for_person(
            self.factory.makePerson(), default_api_version="devel"
        )
        response = webservice.get(distribution_url)
        self.assertEqual(200, response.status)
        response = webservice.get(
            response.jsonBody()["valid_specifications_collection_link"]
        )
        self.assertEqual(200, response.status)
        self.assertContentEqual(
            ["spec1"],
            [entry["name"] for entry in response.jsonBody()["entries"]],
        )


class TestSpecificationSubscription(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_subscribe(self):
        # Test subscribe() API.
        spec = self.factory.makeSpecification()
        person = self.factory.makePerson()
        spec_url = api_url(spec)
        person_url = api_url(person)
        webservice = webservice_for_person(
            person,
            permission=OAuthPermission.WRITE_PUBLIC,
            default_api_version="devel",
        )
        response = webservice.named_post(
            spec_url, "subscribe", person=person_url, essential=True
        )
        self.assertEqual(200, response.status)

        # Check the results.
        login(ANONYMOUS)
        sub = spec.subscription(person)
        self.assertIsNot(None, sub)
        self.assertTrue(sub.essential)

    def test_unsubscribe(self):
        # Test unsubscribe() API.
        spec = self.factory.makeBlueprint()
        person = self.factory.makePerson()
        spec.subscribe(person=person)
        spec_url = api_url(spec)
        person_url = api_url(person)
        webservice = webservice_for_person(
            person,
            permission=OAuthPermission.WRITE_PUBLIC,
            default_api_version="devel",
        )
        response = webservice.named_post(
            spec_url, "unsubscribe", person=person_url
        )
        self.assertEqual(200, response.status)

        # Check the results.
        login(ANONYMOUS)
        self.assertFalse(spec.isSubscribed(person))

    def test_canBeUnsubscribedByUser(self):
        # Test canBeUnsubscribedByUser() API.
        spec = self.factory.makeSpecification()
        person = self.factory.makePerson()
        with person_logged_in(person):
            subscription = spec.subscribe(
                person=person, subscribed_by=person, essential=True
            )
        subscription_url = api_url(subscription)
        admin_webservice = webservice_for_person(
            getUtility(ILaunchpadCelebrities).admin.teamowner,
            default_api_version="devel",
        )
        response = admin_webservice.named_get(
            subscription_url, "canBeUnsubscribedByUser"
        )
        self.assertEqual(200, response.status)
        self.assertIs(True, response.jsonBody())


class TestSpecificationBugLinks(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_bug_linking(self):
        # Set up a spec, person, and bug.
        spec = self.factory.makeSpecification()
        person = self.factory.makePerson()
        bug = self.factory.makeBug()
        spec_url = api_url(spec)
        bug_url = api_url(bug)
        webservice = webservice_for_person(
            person,
            permission=OAuthPermission.WRITE_PUBLIC,
            default_api_version="devel",
        )

        # There are no bugs associated with the spec/blueprint yet.
        response = webservice.get(spec_url)
        self.assertEqual(200, response.status)
        spec_bugs_url = response.jsonBody()["bugs_collection_link"]
        response = webservice.get(spec_bugs_url)
        self.assertEqual(200, response.status)
        self.assertEqual(0, response.jsonBody()["total_size"])

        # Link the bug to the spec via the web service.
        response = webservice.named_post(spec_url, "linkBug", bug=bug_url)
        self.assertEqual(200, response.status)

        # The spec now has one bug associated with it and that bug is the one
        # we linked.
        response = webservice.get(spec_bugs_url)
        self.assertEqual(200, response.status)
        self.assertThat(
            response.jsonBody(),
            ContainsDict(
                {
                    "total_size": Equals(1),
                    "entries": MatchesListwise(
                        [ContainsDict({"id": Equals(bug.id)})]
                    ),
                }
            ),
        )

    def test_bug_unlinking(self):
        # Set up a spec, person, and bug, then link the bug to the spec.
        spec = self.factory.makeBlueprint()
        person = self.factory.makePerson()
        bug = self.factory.makeBug()
        spec_url = api_url(spec)
        bug_url = api_url(bug)
        with person_logged_in(spec.owner):
            spec.linkBug(bug)
        webservice = webservice_for_person(
            person,
            permission=OAuthPermission.WRITE_PUBLIC,
            default_api_version="devel",
        )

        # There is only one bug linked at the moment.
        response = webservice.get(spec_url)
        self.assertEqual(200, response.status)
        spec_bugs_url = response.jsonBody()["bugs_collection_link"]
        response = webservice.get(spec_bugs_url)
        self.assertEqual(200, response.status)
        self.assertEqual(1, response.jsonBody()["total_size"])

        response = webservice.named_post(spec_url, "unlinkBug", bug=bug_url)
        self.assertEqual(200, response.status)

        # Now that we've unlinked the bug, there are no linked bugs at all.
        response = webservice.get(spec_bugs_url)
        self.assertEqual(200, response.status)
        self.assertEqual(0, response.jsonBody()["total_size"])


class TestSpecificationGoalHandling(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.driver = self.factory.makePerson()
        self.proposer = self.factory.makePerson()
        self.product = self.factory.makeProduct(driver=self.driver)
        self.series = self.factory.makeProductSeries(product=self.product)
        self.series_url = api_url(self.series)

    def test_goal_propose_and_accept(self):
        # Webservice clients can propose and accept spec series goals.
        spec = self.factory.makeBlueprint(
            product=self.product, owner=self.proposer
        )
        spec_url = api_url(spec)

        # Propose for series goal
        proposer_webservice = webservice_for_person(
            self.proposer,
            permission=OAuthPermission.WRITE_PUBLIC,
            default_api_version="devel",
        )
        response = proposer_webservice.named_post(
            spec_url, "proposeGoal", goal=self.series_url
        )
        self.assertEqual(200, response.status)
        with person_logged_in(self.proposer):
            self.assertEqual(spec.goal, self.series)
            self.assertFalse(spec.has_accepted_goal)

        # Accept series goal
        driver_webservice = webservice_for_person(
            self.driver,
            permission=OAuthPermission.WRITE_PUBLIC,
            default_api_version="devel",
        )
        response = driver_webservice.named_post(spec_url, "acceptGoal")
        self.assertEqual(200, response.status)
        with person_logged_in(self.driver):
            self.assertTrue(spec.has_accepted_goal)

    def test_goal_propose_decline_and_clear(self):
        # Webservice clients can decline and clear spec series goals.
        spec = self.factory.makeBlueprint(
            product=self.product, owner=self.proposer
        )
        spec_url = api_url(spec)

        # Propose for series goal
        proposer_webservice = webservice_for_person(
            self.proposer,
            permission=OAuthPermission.WRITE_PUBLIC,
            default_api_version="devel",
        )
        response = proposer_webservice.named_post(
            spec_url, "proposeGoal", goal=self.series_url
        )
        self.assertEqual(200, response.status)
        with person_logged_in(self.proposer):
            self.assertEqual(spec.goal, self.series)
            self.assertFalse(spec.has_accepted_goal)

        # Decline series goal
        driver_webservice = webservice_for_person(
            self.driver,
            permission=OAuthPermission.WRITE_PUBLIC,
            default_api_version="devel",
        )
        response = driver_webservice.named_post(spec_url, "declineGoal")
        self.assertEqual(200, response.status)
        with person_logged_in(self.driver):
            self.assertFalse(spec.has_accepted_goal)
            self.assertEqual(spec.goal, self.series)

        # Clear series goal as a driver
        response = driver_webservice.named_post(
            spec_url, "proposeGoal", goal=None
        )
        self.assertEqual(200, response.status)
        with person_logged_in(self.driver):
            self.assertIsNone(spec.goal)
