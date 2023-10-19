# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test bases for charms."""

from testtools.matchers import ContainsDict, Equals
from zope.component import getAdapter, getUtility

from lp.app.interfaces.security import IAuthorization
from lp.charms.interfaces.charmbase import (
    ICharmBase,
    ICharmBaseSet,
    NoSuchCharmBase,
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


class TestCharmBase(TestCaseWithFactory):
    layer = ZopelessDatabaseLayer

    def test_implements_interface(self):
        # CharmBase implements ICharmBase.
        charm_base = self.factory.makeCharmBase()
        self.assertProvides(charm_base, ICharmBase)

    def test_anonymous(self):
        # Anyone can view an `ICharmBase`.
        charm_base = self.factory.makeCharmBase()
        authz = getAdapter(charm_base, IAuthorization, name="launchpad.View")
        self.assertTrue(authz.checkUnauthenticated())

    def test_destroySelf(self):
        distro_series = self.factory.makeDistroSeries()
        charm_base = self.factory.makeCharmBase(distro_series=distro_series)
        charm_base_set = getUtility(ICharmBaseSet)
        self.assertEqual(
            charm_base, charm_base_set.getByDistroSeries(distro_series)
        )
        charm_base.destroySelf()
        self.assertRaises(
            NoSuchCharmBase, charm_base_set.getByDistroSeries, distro_series
        )


class TestCharmBaseProcessors(TestCaseWithFactory):
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
        # CharmBaseSet.new creates a CharmBaseArch for each available
        # Processor for the corresponding series.
        charm_base = getUtility(ICharmBaseSet).new(
            registrant=self.factory.makePerson(),
            distro_series=self.distroseries,
            build_snap_channels={},
        )
        self.assertContentEqual(self.procs, charm_base.processors)

    def test_new_override_processors(self):
        # CharmBaseSet.new can be given a custom set of processors.
        charm_base = getUtility(ICharmBaseSet).new(
            registrant=self.factory.makePerson(),
            distro_series=self.distroseries,
            build_snap_channels={},
            processors=self.procs[:2],
        )
        self.assertContentEqual(self.procs[:2], charm_base.processors)

    def test_set(self):
        # The property remembers its value correctly.
        charm_base = self.factory.makeCharmBase()
        charm_base.setProcessors(self.restricted_procs)
        self.assertContentEqual(self.restricted_procs, charm_base.processors)
        charm_base.setProcessors(self.procs)
        self.assertContentEqual(self.procs, charm_base.processors)
        charm_base.setProcessors([])
        self.assertContentEqual([], charm_base.processors)


class TestCharmBaseSet(TestCaseWithFactory):
    layer = ZopelessDatabaseLayer

    def test_getByDistroSeries(self):
        distro_series = self.factory.makeDistroSeries()
        charm_base_set = getUtility(ICharmBaseSet)
        charm_base = self.factory.makeCharmBase(distro_series=distro_series)
        self.factory.makeCharmBase()
        self.assertEqual(
            charm_base, charm_base_set.getByDistroSeries(distro_series)
        )
        self.assertRaises(
            NoSuchCharmBase,
            charm_base_set.getByDistroSeries,
            self.factory.makeDistroSeries(),
        )

    def test_getAll(self):
        charm_bases = [self.factory.makeCharmBase() for _ in range(3)]
        self.assertContentEqual(
            charm_bases, getUtility(ICharmBaseSet).getAll()
        )


class TestCharmBaseWebservice(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_new_unpriv(self):
        # An unprivileged user cannot create a CharmBase.
        person = self.factory.makePerson()
        distroseries = self.factory.makeDistroSeries()
        distroseries_url = api_url(distroseries)
        webservice = webservice_for_person(
            person, permission=OAuthPermission.WRITE_PUBLIC
        )
        webservice.default_api_version = "devel"
        response = webservice.named_post(
            "/+charm-bases",
            "new",
            distro_series=distroseries_url,
            build_snap_channels={"charmcraft": "stable"},
        )
        self.assertEqual(401, response.status)

    def test_new(self):
        # A registry expert can create a CharmBase.
        person = self.factory.makeRegistryExpert()
        distroseries = self.factory.makeDistroSeries()
        distroseries_url = api_url(distroseries)
        webservice = webservice_for_person(
            person, permission=OAuthPermission.WRITE_PUBLIC
        )
        webservice.default_api_version = "devel"
        logout()
        response = webservice.named_post(
            "/+charm-bases",
            "new",
            distro_series=distroseries_url,
            build_snap_channels={"charmcraft": "stable"},
        )
        self.assertEqual(201, response.status)
        charm_base = webservice.get(response.getHeader("Location")).jsonBody()
        with person_logged_in(person):
            self.assertThat(
                charm_base,
                ContainsDict(
                    {
                        "registrant_link": Equals(
                            webservice.getAbsoluteUrl(api_url(person))
                        ),
                        "distro_series_link": Equals(
                            webservice.getAbsoluteUrl(distroseries_url)
                        ),
                        "build_snap_channels": Equals(
                            {"charmcraft": "stable"}
                        ),
                    }
                ),
            )

    def test_new_duplicate_distro_series(self):
        # An attempt to create a CharmBase with a duplicate distro series is
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
            "/+charm-bases",
            "new",
            distro_series=distroseries_url,
            build_snap_channels={"charmcraft": "stable"},
        )
        self.assertEqual(201, response.status)
        response = webservice.named_post(
            "/+charm-bases",
            "new",
            distro_series=distroseries_url,
            build_snap_channels={"charmcraft": "stable"},
        )
        self.assertEqual(400, response.status)
        self.assertEqual(
            (
                "%s is already in use by another base." % distroseries_str
            ).encode(),
            response.body,
        )

    def test_getByDistroSeries(self):
        # lp.charm_bases.getByDistroSeries returns a matching CharmBase.
        person = self.factory.makePerson()
        distroseries = self.factory.makeDistroSeries()
        distroseries_url = api_url(distroseries)
        webservice = webservice_for_person(
            person, permission=OAuthPermission.READ_PUBLIC
        )
        webservice.default_api_version = "devel"
        with celebrity_logged_in("registry_experts"):
            self.factory.makeCharmBase(distro_series=distroseries)
        response = webservice.named_get(
            "/+charm-bases",
            "getByDistroSeries",
            distro_series=distroseries_url,
        )
        self.assertEqual(200, response.status)
        self.assertEqual(
            webservice.getAbsoluteUrl(distroseries_url),
            response.jsonBody()["distro_series_link"],
        )

    def test_getByDistroSeries_missing(self):
        # lp.charm_bases.getByDistroSeries returns 404 for a non-existent
        # CharmBase.
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
            "/+charm-bases",
            "getByDistroSeries",
            distro_series=distroseries_url,
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

    def setProcessors(self, user, charm_base_url, names):
        ws = webservice_for_person(
            user, permission=OAuthPermission.WRITE_PUBLIC
        )
        return ws.named_post(
            charm_base_url,
            "setProcessors",
            processors=["/+processors/%s" % name for name in names],
            api_version="devel",
        )

    def assertProcessors(self, user, charm_base_url, names):
        body = (
            webservice_for_person(user)
            .get(charm_base_url + "/processors", api_version="devel")
            .jsonBody()
        )
        self.assertContentEqual(
            names, [entry["name"] for entry in body["entries"]]
        )

    def test_setProcessors_admin(self):
        """An admin can change the supported processor set."""
        self.setUpProcessors()
        with admin_logged_in():
            charm_base = self.factory.makeCharmBase(
                distro_series=self.distroseries,
                processors=self.unrestricted_procs,
            )
            charm_base_url = api_url(charm_base)
        admin = self.factory.makeAdministrator()
        self.assertProcessors(
            admin, charm_base_url, self.unrestricted_proc_names
        )

        response = self.setProcessors(
            admin,
            charm_base_url,
            [self.unrestricted_proc_names[0], self.restricted_proc_names[0]],
        )
        self.assertEqual(200, response.status)
        self.assertProcessors(
            admin,
            charm_base_url,
            [self.unrestricted_proc_names[0], self.restricted_proc_names[0]],
        )

    def test_setProcessors_non_admin_forbidden(self):
        """Only admins and registry experts can call setProcessors."""
        self.setUpProcessors()
        with admin_logged_in():
            charm_base = self.factory.makeCharmBase(
                distro_series=self.distroseries
            )
            charm_base_url = api_url(charm_base)
        person = self.factory.makePerson()

        response = self.setProcessors(
            person, charm_base_url, [self.unrestricted_proc_names[0]]
        )
        self.assertEqual(401, response.status)

    def test_collection(self):
        # lp.charm_bases is a collection of all CharmBases.
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
                self.factory.makeCharmBase(distro_series=distroseries)
        response = webservice.get("/+charm-bases")
        self.assertEqual(200, response.status)
        self.assertContentEqual(
            distroseries_urls,
            [
                entry["distro_series_link"]
                for entry in response.jsonBody()["entries"]
            ],
        )
