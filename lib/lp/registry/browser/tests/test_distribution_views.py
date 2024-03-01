# Copyright 2009-2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import soupmatchers
import transaction
from fixtures import FakeLogger
from testtools.matchers import (
    Equals,
    MatchesListwise,
    MatchesSetwise,
    MatchesStructure,
)
from zope.component import getUtility

from lp.app.enums import InformationType
from lp.archivepublisher.interfaces.publisherconfig import IPublisherConfigSet
from lp.buildmaster.interfaces.processor import IProcessorSet
from lp.oci.tests.helpers import OCIConfigHelperMixin
from lp.registry.browser.distribution import DistributionPublisherConfigView
from lp.registry.enums import DistributionDefaultTraversalPolicy
from lp.registry.interfaces.distribution import IDistributionSet
from lp.registry.interfaces.distributionmirror import (
    MirrorContent,
    MirrorStatus,
)
from lp.services.webapp.publisher import canonical_url
from lp.services.webapp.servers import LaunchpadTestRequest
from lp.services.worlddata.interfaces.country import ICountrySet
from lp.soyuz.interfaces.archive import CannotModifyArchiveProcessor
from lp.testing import (
    TestCaseWithFactory,
    login,
    login_celebrity,
    login_person,
    person_logged_in,
    record_two_runs,
)
from lp.testing.layers import DatabaseFunctionalLayer
from lp.testing.matchers import HasQueryCount
from lp.testing.sampledata import LAUNCHPAD_ADMIN
from lp.testing.views import create_initialized_view


class TestDistributionPublisherConfigView(TestCaseWithFactory):
    """Test `DistributionPublisherConfigView`."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        # Create a test distribution.
        super().setUp()
        self.distro = self.factory.makeDistribution(no_pubconf=True)
        login(LAUNCHPAD_ADMIN)

        self.ROOT_DIR = "rootdir/test"
        self.BASE_URL = "http://base.url"
        self.COPY_BASE_URL = "http://copybase.url"

    def test_empty_initial_values(self):
        # Test that the page will display empty field values with no
        # existing config set up.
        view = DistributionPublisherConfigView(
            self.distro, LaunchpadTestRequest()
        )

        for value in view.initial_values:
            self.assertEqual("", value)

    def test_previous_initial_values(self):
        # Test that the initial values are the same as the ones in the
        # existing database record.
        pubconf = self.factory.makePublisherConfig(distribution=self.distro)

        view = DistributionPublisherConfigView(
            self.distro, LaunchpadTestRequest()
        )

        self.assertEqual(pubconf.root_dir, view.initial_values["root_dir"])
        self.assertEqual(pubconf.base_url, view.initial_values["base_url"])
        self.assertEqual(
            pubconf.copy_base_url, view.initial_values["copy_base_url"]
        )

    def _change_and_test_config(self):
        form = {
            "field.actions.save": "save",
            "field.root_dir": self.ROOT_DIR,
            "field.base_url": self.BASE_URL,
            "field.copy_base_url": self.COPY_BASE_URL,
        }

        view = DistributionPublisherConfigView(
            self.distro, LaunchpadTestRequest(method="POST", form=form)
        )
        view.initialize()

        config = getUtility(IPublisherConfigSet).getByDistribution(self.distro)

        self.assertEqual(self.ROOT_DIR, config.root_dir)
        self.assertEqual(self.BASE_URL, config.base_url)
        self.assertEqual(self.COPY_BASE_URL, config.copy_base_url)

    def test_add_new_config(self):
        # Test POSTing a new config.
        self._change_and_test_config()

    def test_change_existing_config(self):
        # Test POSTing to change existing config.
        self.factory.makePublisherConfig(
            distribution=self.distro,
            root_dir="random",
            base_url="blah",
            copy_base_url="foo",
        )
        self._change_and_test_config()

    def test_validate_absolute_root_dir(self):
        form = {
            "field.actions.save": "save",
            "field.root_dir": "/srv/launchpad.test/distro-name",
            "field.base_url": self.BASE_URL,
            "field.copy_base_url": self.COPY_BASE_URL,
        }
        view = create_initialized_view(self.distro, name="+pubconf", form=form)
        self.assertEqual([], view.errors)

    def test_validate_relative_root_dir(self):
        form = {
            "field.actions.save": "save",
            "field.root_dir": "distro-name",
            "field.base_url": self.BASE_URL,
            "field.copy_base_url": self.COPY_BASE_URL,
        }
        view = create_initialized_view(self.distro, name="+pubconf", form=form)
        self.assertEqual([], view.errors)

    def test_validate_relative_root_dir_no_dotdot(self):
        form = {
            "field.actions.save": "save",
            "field.root_dir": "../distro-name",
            "field.base_url": self.BASE_URL,
            "field.copy_base_url": self.COPY_BASE_URL,
        }
        view = create_initialized_view(self.distro, name="+pubconf", form=form)
        self.assertThat(
            view.errors,
            MatchesListwise(
                [
                    MatchesStructure(
                        field_name=Equals("root_dir"),
                        errors=MatchesStructure.byEquality(
                            args=("Path would escape target directory",)
                        ),
                    )
                ]
            ),
        )


class TestDistroAddView(TestCaseWithFactory):
    """Test the +add page for a new distribution."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.owner = self.factory.makePerson()
        self.registrant = self.factory.makePerson()
        self.simple_user = self.factory.makePerson()
        self.admin = login_celebrity("admin")
        self.distributionset = getUtility(IDistributionSet)
        self.all_processors = getUtility(IProcessorSet).getAll()

    def getDefaultAddDict(self):
        return {
            "field.name": "newbuntu",
            "field.display_name": "newbuntu",
            "field.title": "newbuntu",
            "field.summary": "newbuntu",
            "field.description": "newbuntu",
            "field.domainname": "newbuntu",
            "field.members": self.simple_user.name,
            "field.require_virtualized": "",
            "field.processors": [proc.name for proc in self.all_processors],
            "field.actions.save": "Save",
        }

    def test_registrant_set_by_creation(self):
        # The registrant field should be set to the Person creating
        # the distribution.
        creation_form = self.getDefaultAddDict()
        create_initialized_view(
            self.distributionset,
            "+add",
            principal=self.admin,
            method="POST",
            form=creation_form,
        )
        distribution = self.distributionset.getByName("newbuntu")
        self.assertEqual(distribution.owner, self.admin)
        self.assertEqual(distribution.registrant, self.admin)

    def test_add_distro_default_value_require_virtualized(self):
        view = create_initialized_view(
            self.distributionset, "+add", principal=self.admin, method="GET"
        )

        widget = view.widgets["require_virtualized"]
        self.assertEqual(False, widget._getCurrentValue())

    def test_add_distro_init_value_processors(self):
        view = create_initialized_view(
            self.distributionset, "+add", principal=self.admin, method="GET"
        )

        widget = view.widgets["processors"]
        self.assertContentEqual(self.all_processors, widget._getCurrentValue())
        self.assertContentEqual(
            self.all_processors, [item.value for item in widget.vocabulary]
        )

    def test_add_distro_require_virtualized(self):
        creation_form = self.getDefaultAddDict()
        creation_form["field.require_virtualized"] = ""
        create_initialized_view(
            self.distributionset,
            "+add",
            principal=self.admin,
            method="POST",
            form=creation_form,
        )

        distribution = self.distributionset.getByName("newbuntu")
        self.assertEqual(False, distribution.main_archive.require_virtualized)

    def test_add_distro_processors(self):
        creation_form = self.getDefaultAddDict()
        creation_form["field.processors"] = []
        create_initialized_view(
            self.distributionset,
            "+add",
            principal=self.admin,
            method="POST",
            form=creation_form,
        )

        distribution = self.distributionset.getByName("newbuntu")
        self.assertContentEqual([], distribution.main_archive.processors)


class TestDistroEditView(OCIConfigHelperMixin, TestCaseWithFactory):
    """Test the +edit page for a distribution."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.admin = login_celebrity("admin")
        self.oci_admins = self.factory.makeTeam(members=[self.admin])
        self.distribution = self.factory.makeDistribution(
            oci_project_admin=self.oci_admins
        )
        self.all_processors = getUtility(IProcessorSet).getAll()
        self.distributionset = getUtility(IDistributionSet)
        self.setConfig()

    def test_edit_distro_init_value_require_virtualized(self):
        view = create_initialized_view(
            self.distribution, "+edit", principal=self.admin, method="GET"
        )

        widget = view.widgets["require_virtualized"]
        self.assertEqual(
            self.distribution.main_archive.require_virtualized,
            widget._getCurrentValue(),
        )

    def test_edit_distro_init_value_processors(self):
        self.distribution.main_archive.setProcessors(self.all_processors)
        view = create_initialized_view(
            self.distribution, "+edit", principal=self.admin, method="GET"
        )

        widget = view.widgets["processors"]
        self.assertContentEqual(self.all_processors, widget._getCurrentValue())
        self.assertContentEqual(
            self.all_processors, [item.value for item in widget.vocabulary]
        )

    def getDefaultEditDict(self):
        return {
            "field.display_name": "newbuntu",
            "field.title": "newbuntu",
            "field.summary": "newbuntu",
            "field.description": "newbuntu",
            "field.require_virtualized.used": "",
            "field.processors": [proc.name for proc in self.all_processors],
            "field.actions.change": "Change",
        }

    def test_change_require_virtualized(self):
        edit_form = self.getDefaultEditDict()
        edit_form["field.require_virtualized"] = "on"

        self.distribution.main_archive.require_virtualized = False
        create_initialized_view(
            self.distribution,
            "+edit",
            principal=self.admin,
            method="POST",
            form=edit_form,
        )
        self.assertEqual(
            True, self.distribution.main_archive.require_virtualized
        )

    def test_change_processors(self):
        edit_form = self.getDefaultEditDict()
        edit_form["field.processors"] = []

        self.distribution.main_archive.setProcessors(self.all_processors)
        create_initialized_view(
            self.distribution,
            "+edit",
            principal=self.admin,
            method="POST",
            form=edit_form,
        )

        self.assertContentEqual([], self.distribution.main_archive.processors)

    def assertArchiveProcessors(self, archive, names):
        with person_logged_in(archive.owner):
            self.assertContentEqual(
                names, [processor.name for processor in archive.processors]
            )

    def assertProcessorControls(self, processors_control, enabled, disabled):
        matchers = [
            MatchesStructure.byEquality(optionValue=name, disabled=False)
            for name in enabled
        ]
        matchers.extend(
            [
                MatchesStructure.byEquality(optionValue=name, disabled=True)
                for name in disabled
            ]
        )
        self.assertThat(processors_control.controls, MatchesSetwise(*matchers))

    def test_edit_processors_restricted(self):
        # A restricted processor is shown with a disabled (greyed out)
        # checkbox in the UI, and the processor cannot be enabled.
        self.useFixture(FakeLogger())
        self.factory.makeProcessor(
            name="riscv64", restricted=True, build_by_default=False
        )
        login_person(self.distribution.owner)
        browser = self.getUserBrowser(
            canonical_url(self.distribution) + "/+edit",
            user=self.distribution.owner,
        )
        processors = browser.getControl(name="field.processors")
        self.assertContentEqual(["386", "amd64", "hppa"], processors.value)
        self.assertProcessorControls(
            processors, ["386", "amd64", "hppa"], ["riscv64"]
        )
        # Even if the user works around the disabled checkbox and forcibly
        # enables it, they can't enable the restricted processor.
        for control in processors.controls:
            if control.optionValue == "riscv64":
                del control._control.attrs["disabled"]
        processors.value = ["386", "amd64", "riscv64"]
        self.assertRaises(
            CannotModifyArchiveProcessor,
            browser.getControl(name="field.actions.change").click,
        )

    def test_edit_processors_restricted_already_enabled(self):
        # A restricted processor that is already enabled is shown with a
        # disabled (greyed out) checkbox in the UI.  This causes form
        # submission to omit it, but the validation code fixes that up
        # behind the scenes so that we don't get
        # CannotModifyArchiveProcessor.
        proc_386 = getUtility(IProcessorSet).getByName("386")
        proc_amd64 = getUtility(IProcessorSet).getByName("amd64")
        proc_riscv64 = self.factory.makeProcessor(
            name="riscv64", restricted=True, build_by_default=False
        )
        login_person(self.distribution.owner)
        archive = self.distribution.main_archive
        archive.setProcessors([proc_386, proc_amd64, proc_riscv64])
        self.assertArchiveProcessors(archive, ["386", "amd64", "riscv64"])
        browser = self.getUserBrowser(
            canonical_url(self.distribution) + "/+edit",
            user=self.distribution.owner,
        )
        processors = browser.getControl(name="field.processors")
        # riscv64 is checked but disabled.
        self.assertContentEqual(["386", "amd64", "riscv64"], processors.value)
        self.assertProcessorControls(
            processors, ["386", "amd64", "hppa"], ["riscv64"]
        )
        processors.value = ["386"]
        browser.getControl(name="field.actions.change").click()
        self.assertArchiveProcessors(archive, ["386", "riscv64"])

    def test_package_derivatives_email(self):
        # Test that the edit form allows changing package_derivatives_email
        edit_form = self.getDefaultEditDict()
        email = "{package_name}_thing@foo.com"
        edit_form["field.package_derivatives_email"] = email

        create_initialized_view(
            self.distribution,
            "+edit",
            principal=self.distribution.owner,
            method="POST",
            form=edit_form,
        )
        self.assertEqual(self.distribution.package_derivatives_email, email)

    def test_oci_validation_username_no_url(self):
        edit_form = self.getDefaultEditDict()
        edit_form["field.oci_registry_credentials.url"] = ""
        edit_form["field.oci_registry_credentials.username"] = "username"
        edit_form["field.oci_registry_credentials.region"] = ""
        edit_form["field.oci_registry_credentials.password"] = ""
        edit_form["field.oci_registry_credentials.confirm_password"] = ""
        edit_form["field.oci_registry_credentials.delete"] = False

        view = create_initialized_view(
            self.distribution,
            "+edit",
            principal=self.admin,
            method="POST",
            form=edit_form,
        )
        self.assertEqual(
            "A URL is required.",
            view.getFieldError("oci_registry_credentials"),
        )

    def test_oci_validation_different_passwords(self):
        edit_form = self.getDefaultEditDict()
        edit_form["field.oci_registry_credentials.url"] = "http://test.example"
        edit_form["field.oci_registry_credentials.username"] = "username"
        edit_form["field.oci_registry_credentials.region"] = ""
        edit_form["field.oci_registry_credentials.password"] = "password1"
        edit_form["field.oci_registry_credentials.confirm_password"] = "2"
        edit_form["field.oci_registry_credentials.delete"] = False

        view = create_initialized_view(
            self.distribution,
            "+edit",
            principal=self.admin,
            method="POST",
            form=edit_form,
        )
        self.assertEqual(
            "Passwords must match.",
            view.getFieldError("oci_registry_credentials"),
        )

    def test_oci_validation_url_unset(self):
        edit_form = self.getDefaultEditDict()
        edit_form["field.oci_registry_credentials.url"] = ""
        edit_form["field.oci_registry_credentials.username"] = "username"
        edit_form["field.oci_registry_credentials.region"] = ""
        edit_form["field.oci_registry_credentials.password"] = "password1"
        edit_form["field.oci_registry_credentials.confirm_password"] = "2"
        edit_form["field.oci_registry_credentials.delete"] = False

        credentials = self.factory.makeOCIRegistryCredentials(
            registrant=self.distribution.owner, owner=self.distribution.owner
        )
        self.distribution.oci_registry_credentials = credentials
        transaction.commit()

        view = create_initialized_view(
            self.distribution,
            "+edit",
            principal=self.admin,
            method="POST",
            form=edit_form,
        )
        self.assertEqual(
            "A URL is required.",
            view.getFieldError("oci_registry_credentials"),
        )
        self.assertEqual(
            credentials, self.distribution.oci_registry_credentials
        )

    def test_oci_create_credentials_url_only(self):
        edit_form = self.getDefaultEditDict()
        registry_url = self.factory.getUniqueURL()
        edit_form["field.oci_registry_credentials.url"] = registry_url
        edit_form["field.oci_registry_credentials.username"] = ""
        edit_form["field.oci_registry_credentials.region"] = ""
        edit_form["field.oci_registry_credentials.password"] = ""
        edit_form["field.oci_registry_credentials.confirm_password"] = ""
        edit_form["field.oci_registry_credentials.delete"] = False

        create_initialized_view(
            self.distribution,
            "+edit",
            principal=self.admin,
            method="POST",
            form=edit_form,
        )
        self.assertEqual(
            registry_url, self.distribution.oci_registry_credentials.url
        )

    def test_oci_create_credentials(self):
        edit_form = self.getDefaultEditDict()
        registry_url = self.factory.getUniqueURL()
        username = self.factory.getUniqueUnicode()
        password = self.factory.getUniqueUnicode()
        edit_form["field.oci_registry_credentials.url"] = registry_url
        edit_form["field.oci_registry_credentials.username"] = username
        edit_form["field.oci_registry_credentials.region"] = ""
        edit_form["field.oci_registry_credentials.password"] = password
        edit_form["field.oci_registry_credentials.confirm_password"] = password
        edit_form["field.oci_registry_credentials.delete"] = False

        create_initialized_view(
            self.distribution,
            "+edit",
            principal=self.admin,
            method="POST",
            form=edit_form,
        )
        self.assertEqual(
            username, self.distribution.oci_registry_credentials.username
        )

    def test_oci_create_credentials_registrant_not_oci_admin(self):
        distro_admin = self.factory.makePerson()
        oci_admin = self.factory.makeTeam()
        distribution = self.factory.makeDistribution(
            owner=distro_admin, oci_project_admin=oci_admin
        )
        edit_form = self.getDefaultEditDict()
        registry_url = self.factory.getUniqueURL()
        username = self.factory.getUniqueUnicode()
        password = self.factory.getUniqueUnicode()
        edit_form["field.oci_registry_credentials.url"] = registry_url
        edit_form["field.oci_registry_credentials.username"] = username
        edit_form["field.oci_registry_credentials.region"] = ""
        edit_form["field.oci_registry_credentials.password"] = password
        edit_form["field.oci_registry_credentials.confirm_password"] = password
        edit_form["field.oci_registry_credentials.delete"] = False

        create_initialized_view(
            distribution,
            "+edit",
            principal=distro_admin,
            method="POST",
            form=edit_form,
        )
        self.assertEqual(
            username, distribution.oci_registry_credentials.username
        )

    def test_oci_create_credentials_change_url(self):
        edit_form = self.getDefaultEditDict()
        credentials = self.factory.makeOCIRegistryCredentials(
            registrant=self.distribution.owner, owner=self.distribution.owner
        )
        credentials_id = credentials.id
        self.distribution.oci_registry_credentials = credentials
        registry_url = self.factory.getUniqueURL()
        edit_form["field.oci_registry_credentials.url"] = registry_url
        edit_form["field.oci_registry_credentials.username"] = ""
        edit_form["field.oci_registry_credentials.region"] = ""
        edit_form["field.oci_registry_credentials.password"] = ""
        edit_form["field.oci_registry_credentials.confirm_password"] = ""
        edit_form["field.oci_registry_credentials.delete"] = False

        create_initialized_view(
            self.distribution,
            "+edit",
            principal=self.admin,
            method="POST",
            form=edit_form,
        )
        self.assertEqual(
            registry_url, self.distribution.oci_registry_credentials.url
        )
        # This should have created new records
        self.assertNotEqual(
            credentials_id, self.distribution.oci_registry_credentials.id
        )

    def test_oci_create_credentials_change_password(self):
        edit_form = self.getDefaultEditDict()
        credentials = self.factory.makeOCIRegistryCredentials(
            registrant=self.distribution.owner, owner=self.distribution.owner
        )
        url = credentials.url
        self.distribution.oci_registry_credentials = credentials
        transaction.commit()
        password = self.factory.getUniqueUnicode()
        edit_form["field.oci_registry_credentials.url"] = url
        edit_form["field.oci_registry_credentials.username"] = (
            credentials.username
        )
        edit_form["field.oci_registry_credentials.region"] = ""
        edit_form["field.oci_registry_credentials.password"] = password
        edit_form["field.oci_registry_credentials.confirm_password"] = password
        edit_form["field.oci_registry_credentials.delete"] = False

        create_initialized_view(
            self.distribution,
            "+edit",
            principal=self.admin,
            method="POST",
            form=edit_form,
        )
        distro_credentials = self.distribution.oci_registry_credentials
        unencrypted_credentials = distro_credentials.getCredentials()
        self.assertEqual(password, unencrypted_credentials["password"])
        # This should not have changed
        self.assertEqual(url, distro_credentials.url)

    def test_oci_delete_credentials(self):
        edit_form = self.getDefaultEditDict()
        credentials = self.factory.makeOCIRegistryCredentials(
            registrant=self.distribution.owner, owner=self.distribution.owner
        )
        self.distribution.oci_registry_credentials = credentials
        edit_form["field.oci_registry_credentials.url"] = ""
        edit_form["field.oci_registry_credentials.username"] = ""
        edit_form["field.oci_registry_credentials.region"] = ""
        edit_form["field.oci_registry_credentials.password"] = ""
        edit_form["field.oci_registry_credentials.confirm_password"] = ""
        edit_form["field.oci_registry_credentials.delete"] = "on"

        create_initialized_view(
            self.distribution,
            "+edit",
            principal=self.admin,
            method="POST",
            form=edit_form,
        )
        self.assertIsNone(self.distribution.oci_registry_credentials)


class TestDistributionAdminView(TestCaseWithFactory):
    """Test the +admin page for a distribution."""

    layer = DatabaseFunctionalLayer

    def test_admin(self):
        distribution = self.factory.makeDistribution()
        admin = login_celebrity("admin")
        create_initialized_view(
            distribution,
            "+admin",
            principal=admin,
            form={
                "field.official_packages": "on",
                "field.supports_ppas": "on",
                "field.supports_mirrors": "on",
                "field.default_traversal_policy": "SERIES",
                "field.redirect_default_traversal": "on",
                "field.information_type": "PUBLIC",
                "field.actions.change": "change",
            },
        )
        self.assertThat(
            distribution,
            MatchesStructure.byEquality(
                official_packages=True,
                supports_ppas=True,
                supports_mirrors=True,
                default_traversal_policy=(
                    DistributionDefaultTraversalPolicy.SERIES
                ),
                redirect_default_traversal=True,
                information_type=InformationType.PUBLIC,
            ),
        )
        create_initialized_view(
            distribution,
            "+admin",
            principal=admin,
            form={
                "field.official_packages": "",
                "field.supports_ppas": "",
                "field.supports_mirrors": "",
                "field.default_traversal_policy": "OCI_PROJECT",
                "field.redirect_default_traversal": "",
                "field.information_type": "PROPRIETARY",
                "field.actions.change": "change",
            },
        )
        self.assertThat(
            distribution,
            MatchesStructure.byEquality(
                official_packages=False,
                supports_ppas=False,
                supports_mirrors=False,
                default_traversal_policy=(
                    DistributionDefaultTraversalPolicy.OCI_PROJECT
                ),
                redirect_default_traversal=False,
                information_type=InformationType.PROPRIETARY,
            ),
        )


class TestDistroReassignView(TestCaseWithFactory):
    """Test the +reassign page for a new distribution."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.owner = self.factory.makePerson()
        self.registrant = self.factory.makePerson()
        self.simple_user = self.factory.makePerson()

    def test_reassign_distro_change_owner_not_registrant(self):
        # Reassigning a distribution should not change the registrant.
        admin = login_celebrity("admin")
        distribution = self.factory.makeDistribution(
            name="boobuntu", owner=self.owner, registrant=self.registrant
        )
        reassign_form = {
            "field.owner": self.simple_user.name,
            "field.existing": "existing",
            "field.actions.change": "Change",
        }
        create_initialized_view(
            distribution,
            "+reassign",
            principal=admin,
            method="POST",
            form=reassign_form,
        )
        self.assertEqual(distribution.owner, self.simple_user)
        self.assertEqual(distribution.registrant, self.registrant)

    def test_reassign_distro_page_title(self):
        # Reassign should say maintainer instead of owner.
        admin = login_celebrity("admin")
        distribution = self.factory.makeDistribution(
            name="boobuntu", owner=self.owner, registrant=self.registrant
        )
        view = create_initialized_view(
            distribution, "+reassign", principal=admin, method="GET"
        )
        header_match = soupmatchers.HTMLContains(
            soupmatchers.Tag(
                "Header should say maintainer (not owner)",
                "h1",
                text="Change the maintainer of Boobuntu",
            )
        )
        self.assertThat(view.render(), header_match)


class TestDistributionMirrorsViewMixin:
    """Mixin to help test a distribution mirrors view."""

    layer = DatabaseFunctionalLayer

    def test_query_count(self):
        # The number of queries required to render the mirror table is
        # constant in the number of mirrors.
        person = self.factory.makePerson()
        distro = self.factory.makeDistribution(owner=person)
        login_celebrity("admin")
        distro.supports_mirrors = True
        login_person(person)
        distro.mirror_admin = person
        countries = iter(getUtility(ICountrySet))

        def render_mirrors():
            text = create_initialized_view(
                distro, self.view, principal=person
            ).render()
            self.assertNotIn("We don't know of any", text)
            return text

        def create_mirror():
            mirror = self.factory.makeMirror(
                distro, country=next(countries), official_candidate=True
            )
            self.configureMirror(mirror)

        recorder1, recorder2 = record_two_runs(
            render_mirrors, create_mirror, 10
        )
        self.assertThat(recorder2, HasQueryCount.byEquality(recorder1))


class TestDistributionArchiveMirrorsView(
    TestDistributionMirrorsViewMixin, TestCaseWithFactory
):
    view = "+archivemirrors"

    def configureMirror(self, mirror):
        mirror.enabled = True
        mirror.status = MirrorStatus.OFFICIAL


class TestDistributionSeriesMirrorsView(
    TestDistributionMirrorsViewMixin, TestCaseWithFactory
):
    view = "+cdmirrors"

    def configureMirror(self, mirror):
        mirror.enabled = True
        mirror.content = MirrorContent.RELEASE
        mirror.status = MirrorStatus.OFFICIAL


class TestDistributionDisabledMirrorsView(
    TestDistributionMirrorsViewMixin, TestCaseWithFactory
):
    view = "+disabledmirrors"

    def configureMirror(self, mirror):
        mirror.enabled = False
        mirror.status = MirrorStatus.OFFICIAL


class TestDistributionUnofficialMirrorsView(
    TestDistributionMirrorsViewMixin, TestCaseWithFactory
):
    view = "+unofficialmirrors"

    def configureMirror(self, mirror):
        mirror.status = MirrorStatus.UNOFFICIAL


class TestDistributionPendingReviewMirrorsView(
    TestDistributionMirrorsViewMixin, TestCaseWithFactory
):
    view = "+pendingreviewmirrors"

    def configureMirror(self, mirror):
        mirror.status = MirrorStatus.PENDING_REVIEW
