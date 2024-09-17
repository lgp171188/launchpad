# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test bases for rocks."""

from testtools.matchers import ContainsDict, Equals
from zope.component import getAdapter, getUtility

from lp.app.interfaces.security import IAuthorization
from lp.rocks.interfaces.rockbase import (
    IRockBase,
    IRockBaseSet,
    NoSuchRockBase,
)
from lp.services.webapp.interfaces import OAuthPermission
from lp.testing import (
    TestCaseWithFactory,
    admin_logged_in,
    api_url,
    celebrity_logged_in,
    logout,
    person_logged_in,
)
from lp.testing.layers import DatabaseFunctionalLayer, ZopelessDatabaseLayer
from lp.testing.pages import webservice_for_person


class TestRockBase(TestCaseWithFactory):

    layer = ZopelessDatabaseLayer

    def test_implements_interface(self):
        # RockBase implements IRockBase.
        rock_base = self.factory.makeRockBase()
        self.assertProvides(rock_base, IRockBase)

    def test_anonymous(self):
        # Anyone can view an `IRockBase`.
        rock_base = self.factory.makeRockBase()
        authz = getAdapter(rock_base, IAuthorization, name="launchpad.View")
        self.assertTrue(authz.checkUnauthenticated())

    def test_destroySelf(self):
        distro_series = self.factory.makeDistroSeries()
        rock_base = self.factory.makeRockBase(distro_series=distro_series)
        rock_base_set = getUtility(IRockBaseSet)
        self.assertEqual(
            rock_base, rock_base_set.getByDistroSeries(distro_series)
        )
        rock_base.destroySelf()
        self.assertRaises(
            NoSuchRockBase, rock_base_set.getByDistroSeries, distro_series
        )


class TestRockBaseProcessors(TestCaseWithFactory):

    layer = ZopelessDatabaseLayer

    def setUp(self):
        super().setUp(user="foo.bar@canonical.com")
        self.unrestricted_procs = [
            self.factory.makeProcessor() for _ in range(3)
        ]
        self.restricted_procs = [
            self.factory.makeProcessor(restricted=True, build_by_default=False)
            for _ in range(2)
        ]
        self.procs = self.unrestricted_procs + self.restricted_procs
        self.factory.makeProcessor()
        self.distroseries = self.factory.makeDistroSeries()
        for processor in self.procs:
            self.factory.makeDistroArchSeries(
                distroseries=self.distroseries,
                architecturetag=processor.name,
                processor=processor,
            )

    def test_new_default_processors(self):
        # RockBaseSet.new creates a RockBaseArch for each available
        # Processor for the corresponding series.
        rock_base = getUtility(IRockBaseSet).new(
            registrant=self.factory.makePerson(),
            distro_series=self.distroseries,
            build_channels={},
        )
        self.assertContentEqual(self.procs, rock_base.processors)

    def test_new_override_processors(self):
        # RockBaseSet.new can be given a custom set of processors.
        rock_base = getUtility(IRockBaseSet).new(
            registrant=self.factory.makePerson(),
            distro_series=self.distroseries,
            build_channels={},
            processors=self.procs[:2],
        )
        self.assertContentEqual(self.procs[:2], rock_base.processors)

    def test_set(self):
        # The property remembers its value correctly.
        rock_base = self.factory.makeRockBase()
        rock_base.setProcessors(self.restricted_procs)
        self.assertContentEqual(self.restricted_procs, rock_base.processors)
        rock_base.setProcessors(self.procs)
        self.assertContentEqual(self.procs, rock_base.processors)
        rock_base.setProcessors([])
        self.assertContentEqual([], rock_base.processors)


class TestRockBaseSet(TestCaseWithFactory):

    layer = ZopelessDatabaseLayer

    def test_getByDistroSeries(self):
        distro_series = self.factory.makeDistroSeries()
        rock_base_set = getUtility(IRockBaseSet)
        rock_base = self.factory.makeRockBase(distro_series=distro_series)
        self.factory.makeRockBase()
        self.assertEqual(
            rock_base, rock_base_set.getByDistroSeries(distro_series)
        )
        self.assertRaises(
            NoSuchRockBase,
            rock_base_set.getByDistroSeries,
            self.factory.makeDistroSeries(),
        )

    def test_getAll(self):
        rock_bases = [self.factory.makeRockBase() for _ in range(3)]
        self.assertContentEqual(rock_bases, getUtility(IRockBaseSet).getAll())


class TestRockBaseWebservice(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_new_unprivileged(self):
        # An unprivileged user cannot create a RockBase.
        person = self.factory.makePerson()
        distroseries = self.factory.makeDistroSeries()
        distroseries_url = api_url(distroseries)
        webservice = webservice_for_person(
            person, permission=OAuthPermission.WRITE_PUBLIC
        )
        webservice.default_api_version = "devel"
        response = webservice.named_post(
            "/+rock-bases",
            "new",
            distro_series=distroseries_url,
            build_channels={"rockcraft": "stable"},
        )
        self.assertEqual(401, response.status)

    def test_new(self):
        # A registry expert can create a RockBase.
        person = self.factory.makeRegistryExpert()
        distroseries = self.factory.makeDistroSeries()
        distroseries_url = api_url(distroseries)
        webservice = webservice_for_person(
            person, permission=OAuthPermission.WRITE_PUBLIC
        )
        webservice.default_api_version = "devel"
        logout()
        response = webservice.named_post(
            "/+rock-bases",
            "new",
            distro_series=distroseries_url,
            build_channels={"rockcraft": "stable"},
        )
        self.assertEqual(201, response.status)
        rock_base = webservice.get(response.getHeader("Location")).jsonBody()
        with person_logged_in(person):
            self.assertThat(
                rock_base,
                ContainsDict(
                    {
                        "registrant_link": Equals(
                            webservice.getAbsoluteUrl(api_url(person))
                        ),
                        "distro_series_link": Equals(
                            webservice.getAbsoluteUrl(distroseries_url)
                        ),
                        "build_channels": Equals({"rockcraft": "stable"}),
                    }
                ),
            )

    def test_new_duplicate_distro_series(self):
        # An attempt to create a RockBase with a duplicate distro series is
        # rejected.
        person = self.factory.makeRegistryExpert()
        distroseries = self.factory.makeDistroSeries()
        distroseries_str = str(distroseries)
        distroseries_url = api_url(distroseries)
        webservice = webservice_for_person(
            person, permission=OAuthPermission.WRITE_PUBLIC
        )
        webservice.default_api_version = "devel"
        logout()
        response = webservice.named_post(
            "/+rock-bases",
            "new",
            distro_series=distroseries_url,
            build_channels={"rockcraft": "stable"},
        )
        self.assertEqual(201, response.status)
        response = webservice.named_post(
            "/+rock-bases",
            "new",
            distro_series=distroseries_url,
            build_channels={"rockcraft": "stable"},
        )
        self.assertEqual(400, response.status)
        self.assertEqual(
            (
                "%s is already in use by another base." % distroseries_str
            ).encode(),
            response.body,
        )

    def test_getByDistroSeries(self):
        # lp.rock_bases.getByDistroSeries returns a matching RockBase.
        person = self.factory.makePerson()
        distroseries = self.factory.makeDistroSeries()
        distroseries_url = api_url(distroseries)
        webservice = webservice_for_person(
            person, permission=OAuthPermission.READ_PUBLIC
        )
        webservice.default_api_version = "devel"
        with celebrity_logged_in("registry_experts"):
            self.factory.makeRockBase(distro_series=distroseries)
        response = webservice.named_get(
            "/+rock-bases", "getByDistroSeries", distro_series=distroseries_url
        )
        self.assertEqual(200, response.status)
        self.assertEqual(
            webservice.getAbsoluteUrl(distroseries_url),
            response.jsonBody()["distro_series_link"],
        )

    def test_getByDistroSeries_missing(self):
        # lp.rock_bases.getByDistroSeries returns 404 for a non-existent
        # RockBase.
        person = self.factory.makePerson()
        distroseries = self.factory.makeDistroSeries()
        distroseries_str = str(distroseries)
        distroseries_url = api_url(distroseries)
        webservice = webservice_for_person(
            person, permission=OAuthPermission.READ_PUBLIC
        )
        webservice.default_api_version = "devel"
        logout()
        response = webservice.named_get(
            "/+rock-bases", "getByDistroSeries", distro_series=distroseries_url
        )
        self.assertEqual(404, response.status)
        self.assertEqual(
            ("No base for %s." % distroseries_str).encode(), response.body
        )

    def setUpProcessors(self):
        self.unrestricted_procs = [
            self.factory.makeProcessor() for _ in range(3)
        ]
        self.unrestricted_proc_names = [
            processor.name for processor in self.unrestricted_procs
        ]
        self.restricted_procs = [
            self.factory.makeProcessor(restricted=True, build_by_default=False)
            for _ in range(2)
        ]
        self.restricted_proc_names = [
            processor.name for processor in self.restricted_procs
        ]
        self.procs = self.unrestricted_procs + self.restricted_procs
        self.factory.makeProcessor()
        self.distroseries = self.factory.makeDistroSeries()
        for processor in self.procs:
            self.factory.makeDistroArchSeries(
                distroseries=self.distroseries,
                architecturetag=processor.name,
                processor=processor,
            )

    def setProcessors(self, user, rock_base_url, names):
        ws = webservice_for_person(
            user, permission=OAuthPermission.WRITE_PUBLIC
        )
        return ws.named_post(
            rock_base_url,
            "setProcessors",
            processors=["/+processors/%s" % name for name in names],
            api_version="devel",
        )

    def assertProcessors(self, user, rock_base_url, names):
        body = (
            webservice_for_person(user)
            .get(rock_base_url + "/processors", api_version="devel")
            .jsonBody()
        )
        self.assertContentEqual(
            names, [entry["name"] for entry in body["entries"]]
        )

    def test_setProcessors_admin(self):
        """An admin can change the supported processor set."""
        self.setUpProcessors()
        with admin_logged_in():
            rock_base = self.factory.makeRockBase(
                distro_series=self.distroseries,
                processors=self.unrestricted_procs,
            )
            rock_base_url = api_url(rock_base)
        admin = self.factory.makeAdministrator()
        self.assertProcessors(
            admin, rock_base_url, self.unrestricted_proc_names
        )

        response = self.setProcessors(
            admin,
            rock_base_url,
            [self.unrestricted_proc_names[0], self.restricted_proc_names[0]],
        )
        self.assertEqual(200, response.status)
        self.assertProcessors(
            admin,
            rock_base_url,
            [self.unrestricted_proc_names[0], self.restricted_proc_names[0]],
        )

    def test_setProcessors_non_admin_forbidden(self):
        """Only admins and registry experts can call setProcessors."""
        self.setUpProcessors()
        with admin_logged_in():
            rock_base = self.factory.makeRockBase(
                distro_series=self.distroseries
            )
            rock_base_url = api_url(rock_base)
        person = self.factory.makePerson()

        response = self.setProcessors(
            person, rock_base_url, [self.unrestricted_proc_names[0]]
        )
        self.assertEqual(401, response.status)

    def test_collection(self):
        # lp.rock_bases is a collection of all RockBases.
        person = self.factory.makePerson()
        webservice = webservice_for_person(
            person, permission=OAuthPermission.READ_PUBLIC
        )
        webservice.default_api_version = "devel"
        distroseries_urls = []
        with celebrity_logged_in("registry_experts"):
            for _ in range(3):
                distroseries = self.factory.makeDistroSeries()
                distroseries_urls.append(
                    webservice.getAbsoluteUrl(api_url(distroseries))
                )
                self.factory.makeRockBase(distro_series=distroseries)
        response = webservice.get("/+rock-bases")
        self.assertEqual(200, response.status)
        self.assertContentEqual(
            distroseries_urls,
            [
                entry["distro_series_link"]
                for entry in response.jsonBody()["entries"]
            ],
        )
