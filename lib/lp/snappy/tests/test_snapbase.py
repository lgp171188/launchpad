# Copyright 2019-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test bases for snaps."""

from testtools.matchers import (
    ContainsDict,
    Equals,
    Is,
    MatchesListwise,
    MatchesRegex,
    MatchesStructure,
)
from zope.component import getAdapter, getUtility
from zope.security.proxy import removeSecurityProxy

from lp.app.interfaces.security import IAuthorization
from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.services.webapp.interfaces import OAuthPermission
from lp.snappy.interfaces.snapbase import (
    CannotDeleteSnapBase,
    ISnapBase,
    ISnapBaseSet,
    NoSuchSnapBase,
    SnapBaseFeature,
)
from lp.soyuz.interfaces.component import IComponentSet
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


class TestSnapBase(TestCaseWithFactory):
    layer = ZopelessDatabaseLayer

    def test_implements_interface(self):
        # SnapBase implements ISnapBase.
        snap_base = self.factory.makeSnapBase()
        self.assertProvides(snap_base, ISnapBase)

    def test_new_not_default(self):
        snap_base = self.factory.makeSnapBase()
        self.assertFalse(snap_base.is_default)

    def test_anonymous(self):
        # Anyone can view an `ISnapBase`.
        snap_base = self.factory.makeSnapBase()
        authz = getAdapter(snap_base, IAuthorization, name="launchpad.View")
        self.assertTrue(authz.checkUnauthenticated())

    def test_destroySelf(self):
        snap_base = self.factory.makeSnapBase()
        snap_base_name = snap_base.name
        snap_base_set = getUtility(ISnapBaseSet)
        self.assertEqual(snap_base, snap_base_set.getByName(snap_base_name))
        snap_base.destroySelf()
        self.assertRaises(
            NoSuchSnapBase, snap_base_set.getByName, snap_base_name
        )

    def test_destroySelf_refuses_default(self):
        snap_base = self.factory.makeSnapBase()
        getUtility(ISnapBaseSet).setDefault(snap_base)
        self.assertRaises(CannotDeleteSnapBase, snap_base.destroySelf)

    def test_features(self):
        snap_base = self.factory.makeSnapBase(
            features={SnapBaseFeature.ALLOW_DUPLICATE_BUILD_ON: True}
        )

        # feature are saved to the database by their title
        self.assertEqual(
            {
                "allow_duplicate_build_on": True,
            },
            removeSecurityProxy(snap_base)._features,
        )

        # pretend that the database contains an invalid value
        removeSecurityProxy(snap_base)._features["unknown_feature"] = True
        self.assertEqual(
            {
                SnapBaseFeature.ALLOW_DUPLICATE_BUILD_ON: True,
            },
            snap_base.features,
        )

    def test_blank_features(self):
        snap_base = self.factory.makeSnapBase(name="foo")
        removeSecurityProxy(snap_base)._features = None
        self.assertEqual({}, snap_base.features)


class TestSnapBaseProcessors(TestCaseWithFactory):
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
        # SnapBaseSet.new creates a SnapBaseArch for each available
        # Processor for the corresponding series.
        snap_base = getUtility(ISnapBaseSet).new(
            registrant=self.factory.makePerson(),
            name=self.factory.getUniqueUnicode(),
            display_name=self.factory.getUniqueUnicode(),
            distro_series=self.distroseries,
            build_channels={},
            features={},
        )
        self.assertContentEqual(self.procs, snap_base.processors)

    def test_new_override_processors(self):
        # SnapBaseSet.new can be given a custom set of processors.
        snap_base = getUtility(ISnapBaseSet).new(
            registrant=self.factory.makePerson(),
            name=self.factory.getUniqueUnicode(),
            display_name=self.factory.getUniqueUnicode(),
            distro_series=self.distroseries,
            build_channels={},
            features={},
            processors=self.procs[:2],
        )
        self.assertContentEqual(self.procs[:2], snap_base.processors)

    def test_set(self):
        # The property remembers its value correctly.
        snap_base = self.factory.makeSnapBase()
        snap_base.setProcessors(self.restricted_procs)
        self.assertContentEqual(self.restricted_procs, snap_base.processors)
        snap_base.setProcessors(self.procs)
        self.assertContentEqual(self.procs, snap_base.processors)
        snap_base.setProcessors([])
        self.assertContentEqual([], snap_base.processors)


class TestSnapBaseSet(TestCaseWithFactory):
    layer = ZopelessDatabaseLayer

    def test_getByName(self):
        snap_base_set = getUtility(ISnapBaseSet)
        snap_base = self.factory.makeSnapBase(name="foo")
        self.factory.makeSnapBase()
        self.assertEqual(snap_base, snap_base_set.getByName("foo"))
        self.assertRaises(NoSuchSnapBase, snap_base_set.getByName, "bar")

    def test_getDefault(self):
        snap_base_set = getUtility(ISnapBaseSet)
        snap_base = self.factory.makeSnapBase()
        self.factory.makeSnapBase()
        self.assertIsNone(snap_base_set.getDefault())
        snap_base_set.setDefault(snap_base)
        self.assertEqual(snap_base, snap_base_set.getDefault())

    def test_setDefault(self):
        snap_base_set = getUtility(ISnapBaseSet)
        snap_bases = [self.factory.makeSnapBase() for _ in range(3)]
        snap_base_set.setDefault(snap_bases[0])
        self.assertEqual(
            [True, False, False],
            [snap_base.is_default for snap_base in snap_bases],
        )
        snap_base_set.setDefault(snap_bases[1])
        self.assertEqual(
            [False, True, False],
            [snap_base.is_default for snap_base in snap_bases],
        )
        snap_base_set.setDefault(None)
        self.assertEqual(
            [False, False, False],
            [snap_base.is_default for snap_base in snap_bases],
        )

    def test_getAll(self):
        snap_bases = [self.factory.makeSnapBase() for _ in range(3)]
        self.assertContentEqual(snap_bases, getUtility(ISnapBaseSet).getAll())


class TestSnapBaseWebservice(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_new_unpriv(self):
        # An unprivileged user cannot create a SnapBase.
        person = self.factory.makePerson()
        distroseries = self.factory.makeDistroSeries()
        distroseries_url = api_url(distroseries)
        webservice = webservice_for_person(
            person, permission=OAuthPermission.WRITE_PUBLIC
        )
        webservice.default_api_version = "devel"
        response = webservice.named_post(
            "/+snap-bases",
            "new",
            name="dummy",
            display_name="Dummy",
            distro_series=distroseries_url,
            build_channels={"snapcraft": "stable"},
        )
        self.assertEqual(401, response.status)

    def test_new(self):
        # A registry expert can create a SnapBase.
        person = self.factory.makeRegistryExpert()
        distroseries = self.factory.makeDistroSeries()
        distroseries_url = api_url(distroseries)
        webservice = webservice_for_person(
            person, permission=OAuthPermission.WRITE_PUBLIC
        )
        webservice.default_api_version = "devel"
        logout()
        response = webservice.named_post(
            "/+snap-bases",
            "new",
            name="dummy",
            display_name="Dummy",
            distro_series=distroseries_url,
            build_channels={"snapcraft": "stable"},
            features={"allow_duplicate_build_on": True},
        )
        self.assertEqual(201, response.status)
        snap_base = webservice.get(response.getHeader("Location")).jsonBody()
        with person_logged_in(person):
            self.assertThat(
                snap_base,
                ContainsDict(
                    {
                        "registrant_link": Equals(
                            webservice.getAbsoluteUrl(api_url(person))
                        ),
                        "name": Equals("dummy"),
                        "display_name": Equals("Dummy"),
                        "distro_series_link": Equals(
                            webservice.getAbsoluteUrl(distroseries_url)
                        ),
                        "build_channels": Equals({"snapcraft": "stable"}),
                        "features": Equals({"allow_duplicate_build_on": True}),
                        "is_default": Is(False),
                    }
                ),
            )

    def test_new_duplicate_name(self):
        # An attempt to create a SnapBase with a duplicate name is rejected.
        person = self.factory.makeRegistryExpert()
        distroseries = self.factory.makeDistroSeries()
        distroseries_url = api_url(distroseries)
        webservice = webservice_for_person(
            person, permission=OAuthPermission.WRITE_PUBLIC
        )
        webservice.default_api_version = "devel"
        logout()
        response = webservice.named_post(
            "/+snap-bases",
            "new",
            name="dummy",
            display_name="Dummy",
            distro_series=distroseries_url,
            build_channels={"snapcraft": "stable"},
        )
        self.assertEqual(201, response.status)
        response = webservice.named_post(
            "/+snap-bases",
            "new",
            name="dummy",
            display_name="Dummy",
            distro_series=distroseries_url,
            build_channels={"snapcraft": "stable"},
        )
        self.assertEqual(400, response.status)
        self.assertEqual(
            b"name: dummy is already in use by another base.", response.body
        )

    def test_new_invalid_features(self):
        person = self.factory.makeRegistryExpert()
        distroseries = self.factory.makeDistroSeries()
        distroseries_url = api_url(distroseries)
        webservice = webservice_for_person(
            person, permission=OAuthPermission.WRITE_PUBLIC
        )
        webservice.default_api_version = "devel"
        logout()
        response = webservice.named_post(
            "/+snap-bases",
            "new",
            name="dummy",
            display_name="Dummy",
            distro_series=distroseries_url,
            build_channels={"snapcraft": "stable"},
            features={
                "allow_duplicate_build_on": True,
                "invalid_feature": True,
            },
        )
        self.assertEqual(400, response.status)
        self.assertStartsWith(
            response.body, b'features: Invalid value "invalid_feature".'
        )

    def test_getByName(self):
        # lp.snap_bases.getByName returns a matching SnapBase.
        person = self.factory.makePerson()
        webservice = webservice_for_person(
            person, permission=OAuthPermission.READ_PUBLIC
        )
        webservice.default_api_version = "devel"
        with celebrity_logged_in("registry_experts"):
            self.factory.makeSnapBase(name="dummy")
        response = webservice.named_get(
            "/+snap-bases", "getByName", name="dummy"
        )
        self.assertEqual(200, response.status)
        self.assertEqual("dummy", response.jsonBody()["name"])

    def test_getByName_missing(self):
        # lp.snap_bases.getByName returns 404 for a non-existent SnapBase.
        person = self.factory.makePerson()
        webservice = webservice_for_person(
            person, permission=OAuthPermission.READ_PUBLIC
        )
        webservice.default_api_version = "devel"
        logout()
        response = webservice.named_get(
            "/+snap-bases", "getByName", name="nonexistent"
        )
        self.assertEqual(404, response.status)
        self.assertEqual(b"No such base: 'nonexistent'.", response.body)

    def test_getDefault(self):
        # lp.snap_bases.getDefault returns the default SnapBase, if any.
        person = self.factory.makePerson()
        webservice = webservice_for_person(
            person, permission=OAuthPermission.READ_PUBLIC
        )
        webservice.default_api_version = "devel"
        response = webservice.named_get("/+snap-bases", "getDefault")
        self.assertEqual(200, response.status)
        self.assertIsNone(response.jsonBody())
        with celebrity_logged_in("registry_experts"):
            getUtility(ISnapBaseSet).setDefault(
                self.factory.makeSnapBase(name="default-base")
            )
            self.factory.makeSnapBase()
        response = webservice.named_get("/+snap-bases", "getDefault")
        self.assertEqual(200, response.status)
        self.assertEqual("default-base", response.jsonBody()["name"])

    def test_setDefault_unpriv(self):
        # An unprivileged user cannot set the default SnapBase.
        person = self.factory.makePerson()
        with celebrity_logged_in("registry_experts"):
            snap_base = self.factory.makeSnapBase()
            snap_base_url = api_url(snap_base)
        webservice = webservice_for_person(
            person, permission=OAuthPermission.WRITE_PUBLIC
        )
        webservice.default_api_version = "devel"
        response = webservice.named_post(
            "/+snap-bases", "setDefault", snap_base=snap_base_url
        )
        self.assertEqual(401, response.status)

    def test_setDefault(self):
        # A registry expert can set the default SnapBase.
        person = self.factory.makeRegistryExpert()
        with person_logged_in(person):
            snap_bases = [self.factory.makeSnapBase() for _ in range(3)]
            snap_base_urls = [api_url(snap_base) for snap_base in snap_bases]
        webservice = webservice_for_person(
            person, permission=OAuthPermission.WRITE_PUBLIC
        )
        webservice.default_api_version = "devel"
        response = webservice.named_post(
            "/+snap-bases", "setDefault", snap_base=snap_base_urls[0]
        )
        self.assertEqual(200, response.status)
        with person_logged_in(person):
            self.assertEqual(
                snap_bases[0], getUtility(ISnapBaseSet).getDefault()
            )
        response = webservice.named_post(
            "/+snap-bases", "setDefault", snap_base=snap_base_urls[1]
        )
        self.assertEqual(200, response.status)
        with person_logged_in(person):
            self.assertEqual(
                snap_bases[1], getUtility(ISnapBaseSet).getDefault()
            )

    def test_addArchiveDependency_unpriv(self):
        # An unprivileged user cannot add an archive dependency.
        person = self.factory.makePerson()
        with celebrity_logged_in("registry_experts"):
            snap_base = self.factory.makeSnapBase()
            archive = self.factory.makeArchive()
            snap_base_url = api_url(snap_base)
            archive_url = api_url(archive)
        webservice = webservice_for_person(
            person, permission=OAuthPermission.WRITE_PUBLIC
        )
        webservice.default_api_version = "devel"
        response = webservice.named_post(
            snap_base_url,
            "addArchiveDependency",
            dependency=archive_url,
            pocket="Release",
            component="main",
        )
        self.assertThat(
            response,
            MatchesStructure(
                status=Equals(401),
                body=MatchesRegex(
                    rb".*addArchiveDependency.*launchpad.Edit.*"
                ),
            ),
        )

    def test_addArchiveDependency(self):
        # A registry expert can add an archive dependency.
        person = self.factory.makeRegistryExpert()
        with person_logged_in(person):
            snap_base = self.factory.makeSnapBase()
            archive = self.factory.makeArchive()
            snap_base_url = api_url(snap_base)
            archive_url = api_url(archive)
            self.assertEqual([], list(snap_base.dependencies))
        webservice = webservice_for_person(
            person, permission=OAuthPermission.WRITE_PUBLIC
        )
        webservice.default_api_version = "devel"
        response = webservice.named_post(
            snap_base_url,
            "addArchiveDependency",
            dependency=archive_url,
            pocket="Release",
            component="main",
        )
        self.assertEqual(201, response.status)
        with person_logged_in(person):
            self.assertThat(
                list(snap_base.dependencies),
                MatchesListwise(
                    [
                        MatchesStructure(
                            archive=Is(None),
                            snap_base=Equals(snap_base),
                            dependency=Equals(archive),
                            pocket=Equals(PackagePublishingPocket.RELEASE),
                            component=Equals(
                                getUtility(IComponentSet)["main"]
                            ),
                            component_name=Equals("main"),
                            title=Equals(archive.displayname),
                        ),
                    ]
                ),
            )

    def test_addArchiveDependency_invalid(self):
        # Invalid requests generate a BadRequest error.
        person = self.factory.makeRegistryExpert()
        with person_logged_in(person):
            snap_base = self.factory.makeSnapBase()
            archive = self.factory.makeArchive()
            snap_base.addArchiveDependency(
                archive, PackagePublishingPocket.RELEASE
            )
            snap_base_url = api_url(snap_base)
            archive_url = api_url(archive)
        webservice = webservice_for_person(
            person, permission=OAuthPermission.WRITE_PUBLIC
        )
        webservice.default_api_version = "devel"
        response = webservice.named_post(
            snap_base_url,
            "addArchiveDependency",
            dependency=archive_url,
            pocket="Release",
            component="main",
        )
        self.assertThat(
            response,
            MatchesStructure.byEquality(
                status=400, body=b"This dependency is already registered."
            ),
        )

    def test_removeArchiveDependency_unpriv(self):
        # An unprivileged user cannot remove an archive dependency.
        person = self.factory.makePerson()
        with celebrity_logged_in("registry_experts"):
            snap_base = self.factory.makeSnapBase()
            archive = self.factory.makeArchive()
            snap_base.addArchiveDependency(
                archive, PackagePublishingPocket.RELEASE
            )
            snap_base_url = api_url(snap_base)
            archive_url = api_url(archive)
        webservice = webservice_for_person(
            person, permission=OAuthPermission.WRITE_PUBLIC
        )
        webservice.default_api_version = "devel"
        response = webservice.named_post(
            snap_base_url, "removeArchiveDependency", dependency=archive_url
        )
        self.assertThat(
            response,
            MatchesStructure(
                status=Equals(401),
                body=MatchesRegex(
                    rb".*removeArchiveDependency.*launchpad.Edit.*"
                ),
            ),
        )

    def test_removeArchiveDependency(self):
        # A registry expert can remove an archive dependency.
        person = self.factory.makeRegistryExpert()
        with person_logged_in(person):
            snap_base = self.factory.makeSnapBase()
            archive = self.factory.makeArchive()
            snap_base.addArchiveDependency(
                archive, PackagePublishingPocket.RELEASE
            )
            snap_base_url = api_url(snap_base)
            archive_url = api_url(archive)
            self.assertNotEqual([], list(snap_base.dependencies))
        webservice = webservice_for_person(
            person, permission=OAuthPermission.WRITE_PUBLIC
        )
        webservice.default_api_version = "devel"
        response = webservice.named_post(
            snap_base_url, "removeArchiveDependency", dependency=archive_url
        )
        self.assertEqual(200, response.status)
        with person_logged_in(person):
            self.assertEqual([], list(snap_base.dependencies))

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

    def setProcessors(self, user, snap_base_url, names):
        ws = webservice_for_person(
            user, permission=OAuthPermission.WRITE_PUBLIC
        )
        return ws.named_post(
            snap_base_url,
            "setProcessors",
            processors=["/+processors/%s" % name for name in names],
            api_version="devel",
        )

    def assertProcessors(self, user, snap_base_url, names):
        body = (
            webservice_for_person(user)
            .get(snap_base_url + "/processors", api_version="devel")
            .jsonBody()
        )
        self.assertContentEqual(
            names, [entry["name"] for entry in body["entries"]]
        )

    def test_setProcessors_admin(self):
        """An admin can change the supported processor set."""
        self.setUpProcessors()
        with admin_logged_in():
            snap_base = self.factory.makeSnapBase(
                distro_series=self.distroseries,
                processors=self.unrestricted_procs,
            )
            snap_base_url = api_url(snap_base)
        admin = self.factory.makeAdministrator()
        self.assertProcessors(
            admin, snap_base_url, self.unrestricted_proc_names
        )

        response = self.setProcessors(
            admin,
            snap_base_url,
            [self.unrestricted_proc_names[0], self.restricted_proc_names[0]],
        )
        self.assertEqual(200, response.status)
        self.assertProcessors(
            admin,
            snap_base_url,
            [self.unrestricted_proc_names[0], self.restricted_proc_names[0]],
        )

    def test_setProcessors_non_admin_forbidden(self):
        """Only admins and registry experts can call setProcessors."""
        self.setUpProcessors()
        with admin_logged_in():
            snap_base = self.factory.makeSnapBase(
                distro_series=self.distroseries
            )
            snap_base_url = api_url(snap_base)
        person = self.factory.makePerson()

        response = self.setProcessors(
            person, snap_base_url, [self.unrestricted_proc_names[0]]
        )
        self.assertEqual(401, response.status)

    def test_collection(self):
        # lp.snap_bases is a collection of all SnapBases.
        person = self.factory.makePerson()
        webservice = webservice_for_person(
            person, permission=OAuthPermission.READ_PUBLIC
        )
        webservice.default_api_version = "devel"
        with celebrity_logged_in("registry_experts"):
            for i in range(3):
                self.factory.makeSnapBase(name="base-%d" % i)
        response = webservice.get("/+snap-bases")
        self.assertEqual(200, response.status)
        self.assertContentEqual(
            ["base-0", "base-1", "base-2"],
            [entry["name"] for entry in response.jsonBody()["entries"]],
        )
