# Copyright 2011-2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the builders webservice ."""

from json import dumps

from testtools.matchers import ContainsDict, Equals, Is
from zope.component import getUtility

from lp.buildmaster.interfaces.builder import IBuilderSet
from lp.registry.interfaces.person import IPersonSet
from lp.services.webapp import canonical_url
from lp.services.webapp.interfaces import OAuthPermission
from lp.testing import (
    RequestTimelineCollector,
    TestCaseWithFactory,
    admin_logged_in,
    api_url,
    logout,
)
from lp.testing.layers import DatabaseFunctionalLayer
from lp.testing.matchers import HasQueryCount
from lp.testing.pages import LaunchpadWebServiceCaller, webservice_for_person


class TestBuildersCollection(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.webservice = LaunchpadWebServiceCaller()

    def test_list(self):
        names = ["bob", "frog"]
        for _ in range(3):
            builder = self.factory.makeBuilder()
            self.factory.makeBinaryPackageBuild().queueBuild().markAsBuilding(
                builder
            )
            names.append(builder.name)
        logout()
        with RequestTimelineCollector() as recorder:
            builders = self.webservice.get(
                "/builders", api_version="devel"
            ).jsonBody()
        self.assertContentEqual(
            names, [b["name"] for b in builders["entries"]]
        )
        self.assertThat(recorder, HasQueryCount(Equals(19)))

    def test_list_with_private_builds(self):
        # Inaccessible private builds aren't linked in builders'
        # current_build fields.
        with admin_logged_in():
            rbpb = self.factory.makeBinaryPackageBuild(
                archive=self.factory.makeArchive(private=True)
            )
            rbpb.queueBuild().markAsBuilding(
                self.factory.makeBuilder(name="restricted")
            )
            bpb = self.factory.makeBinaryPackageBuild(
                archive=self.factory.makeArchive(private=False)
            )
            bpb.queueBuild().markAsBuilding(
                self.factory.makeBuilder(name="public")
            )
            bpb_url = canonical_url(bpb, path_only_if_possible=True)
        logout()

        builders = self.webservice.get(
            "/builders", api_version="devel"
        ).jsonBody()
        current_builds = {
            b["name"]: b["current_build_link"] for b in builders["entries"]
        }
        self.assertEqual(
            "tag:launchpad.net:2008:redacted", current_builds["restricted"]
        )
        self.assertEqual(
            "http://api.launchpad.test/devel" + bpb_url,
            current_builds["public"],
        )

    def test_getBuildQueueSizes(self):
        logout()
        results = self.webservice.named_get(
            "/builders", "getBuildQueueSizes", api_version="devel"
        )
        self.assertEqual(
            ["nonvirt", "virt"], sorted(results.jsonBody().keys())
        )

    def test_getBuildersForQueue(self):
        g1 = self.factory.makeProcessor("g1")
        quantum = self.factory.makeProcessor("quantum")
        self.factory.makeBuilder(processors=[quantum], name="quantum_builder1")
        self.factory.makeBuilder(processors=[quantum], name="quantum_builder2")
        self.factory.makeBuilder(
            processors=[quantum], name="quantum_builder3", virtualized=False
        )
        self.factory.makeBuilder(
            processors=[g1], name="g1_builder", virtualized=False
        )

        logout()
        results = self.webservice.named_get(
            "/builders",
            "getBuildersForQueue",
            processor=api_url(quantum),
            virtualized=True,
            api_version="devel",
        ).jsonBody()
        self.assertEqual(
            ["quantum_builder1", "quantum_builder2"],
            sorted(builder["name"] for builder in results["entries"]),
        )

    def test_new(self):
        person = self.factory.makePerson()
        badmins = getUtility(IPersonSet).getByName("launchpad-buildd-admins")
        webservice = webservice_for_person(
            person, permission=OAuthPermission.WRITE_PRIVATE
        )
        args = dict(
            name="foo",
            processors=["/+processors/386"],
            title="foobar",
            url="http://foo.buildd:8221/",
            virtualized=False,
            api_version="devel",
        )

        response = webservice.named_post("/builders", "new", **args)
        self.assertEqual(401, response.status)

        with admin_logged_in():
            badmins.addMember(person, badmins)
        response = webservice.named_post("/builders", "new", **args)
        self.assertEqual(201, response.status)

        self.assertThat(
            webservice.get("/builders/foo").jsonBody(),
            ContainsDict(
                {
                    "name": Equals("foo"),
                    "title": Equals("foobar"),
                    "url": Equals("http://foo.buildd:8221/"),
                    "virtualized": Is(False),
                    "open_resources": Is(None),
                    "restricted_resources": Is(None),
                }
            ),
        )

    def test_new_resources(self):
        person = self.factory.makePerson()
        badmins = getUtility(IPersonSet).getByName("launchpad-buildd-admins")
        webservice = webservice_for_person(
            person, permission=OAuthPermission.WRITE_PRIVATE
        )
        args = dict(
            name="foo",
            processors=["/+processors/386"],
            title="foobar",
            url="http://foo.buildd:8221/",
            virtualized=True,
            open_resources=["large"],
            restricted_resources=["gpu"],
            api_version="devel",
        )

        response = webservice.named_post("/builders", "new", **args)
        self.assertEqual(401, response.status)

        with admin_logged_in():
            badmins.addMember(person, badmins)
        response = webservice.named_post("/builders", "new", **args)
        self.assertEqual(201, response.status)

        self.assertThat(
            webservice.get("/builders/foo").jsonBody(),
            ContainsDict(
                {
                    "name": Equals("foo"),
                    "title": Equals("foobar"),
                    "url": Equals("http://foo.buildd:8221/"),
                    "virtualized": Is(True),
                    "open_resources": Equals(["large"]),
                    "restricted_resources": Equals(["gpu"]),
                }
            ),
        )


class TestBuilderEntry(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.webservice = LaunchpadWebServiceCaller()

    def test_security(self):
        # Most builder attributes can only be set by buildd admins.
        # We've introduced registry_experts privileges on 3 attributes
        # for builder reset, tested in next method.

        builder = self.factory.makeBuilder()
        user = self.factory.makePerson()
        user_webservice = webservice_for_person(
            user, permission=OAuthPermission.WRITE_PUBLIC
        )
        clean_status_patch = dumps({"clean_status": "Cleaning"})
        logout()

        # A normal user is unauthorized.
        response = user_webservice.patch(
            api_url(builder),
            "application/json",
            clean_status_patch,
            api_version="devel",
        )
        self.assertEqual(401, response.status)

        # But a buildd admin can set the attribute.
        with admin_logged_in():
            buildd_admins = getUtility(IPersonSet).getByName(
                "launchpad-buildd-admins"
            )
            buildd_admins.addMember(user, buildd_admins.teamowner)
        response = user_webservice.patch(
            api_url(builder),
            "application/json",
            clean_status_patch,
            api_version="devel",
        )
        self.assertEqual(209, response.status)
        self.assertEqual("Cleaning", response.jsonBody()["clean_status"])

    def test_security_builder_reset(self):
        builder = getUtility(IBuilderSet)["bob"]
        person = self.factory.makePerson()
        user_webservice = webservice_for_person(
            person, permission=OAuthPermission.WRITE_PUBLIC
        )
        change_patch = dumps(
            {"builderok": False, "manual": False, "failnotes": "test notes"}
        )
        logout()

        # A normal user is unauthorized.
        response = user_webservice.patch(
            api_url(builder),
            "application/json",
            change_patch,
            api_version="devel",
        )
        self.assertEqual(401, response.status)

        # But a registry expert can set the attributes.
        with admin_logged_in():
            reg_expert = getUtility(IPersonSet).getByName("registry")
            reg_expert.addMember(person, reg_expert)
        response = user_webservice.patch(
            api_url(builder),
            "application/json",
            change_patch,
            api_version="devel",
        )
        self.assertEqual(209, response.status)
        self.assertEqual(False, response.jsonBody()["builderok"])
        self.assertEqual(False, response.jsonBody()["manual"])
        self.assertEqual("test notes", response.jsonBody()["failnotes"])

    def test_exports_processor(self):
        processor = self.factory.makeProcessor("s1")
        builder = self.factory.makeBuilder(processors=[processor])

        logout()
        entry = self.webservice.get(
            api_url(builder), api_version="devel"
        ).jsonBody()
        self.assertEndsWith(entry["processor_link"], "/+processors/s1")

    def test_getBuildRecords(self):
        builder = self.factory.makeBuilder()
        build = self.factory.makeBinaryPackageBuild(builder=builder)
        build_title = build.title

        logout()
        results = self.webservice.named_get(
            api_url(builder),
            "getBuildRecords",
            pocket="Release",
            api_version="devel",
        ).jsonBody()
        self.assertEqual(
            [build_title], [entry["title"] for entry in results["entries"]]
        )
        results = self.webservice.named_get(
            api_url(builder),
            "getBuildRecords",
            pocket="Proposed",
            api_version="devel",
        ).jsonBody()
        self.assertEqual(0, len(results["entries"]))
