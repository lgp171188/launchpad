# Copyright 2009-2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Interfaces including and related to IDistroSeries."""

__all__ = [
    "DerivationError",
    "DistroSeriesNameField",
    "DistroSeriesTranslationTemplateStatistics",
    "IDistroSeries",
    "IDistroSeriesEditRestricted",
    "IDistroSeriesPublic",
    "IDistroSeriesSet",
]

import http.client
import typing
from datetime import datetime

from lazr.lifecycle.snapshot import doNotSnapshot
from lazr.restful.declarations import (
    REQUEST_USER,
    call_with,
    error_status,
    export_factory_operation,
    export_read_operation,
    export_write_operation,
    exported,
    exported_as_webservice_entry,
    operation_for_version,
    operation_parameters,
    operation_returns_collection_of,
    operation_returns_entry,
    rename_parameters_as,
)
from lazr.restful.fields import CollectionField, Reference, ReferenceChoice
from zope.component import getUtility
from zope.interface import Attribute, Interface
from zope.schema import Bool, Choice, Datetime, List, Object, TextLine

from lp import _
from lp.app.interfaces.launchpad import IServiceUsage
from lp.app.validators import LaunchpadValidationError
from lp.app.validators.email import email_validator
from lp.app.validators.name import name_validator
from lp.app.validators.version import sane_version
from lp.blueprints.interfaces.specificationtarget import ISpecificationGoal
from lp.bugs.interfaces.bugtarget import (
    IBugTarget,
    IHasBugs,
    IHasExpirableBugs,
    IHasOfficialBugTags,
)
from lp.bugs.interfaces.structuralsubscription import (
    IStructuralSubscriptionTarget,
)
from lp.registry.enums import (
    DistroSeriesDifferenceStatus,
    DistroSeriesDifferenceType,
)
from lp.registry.errors import NoSuchDistroSeries
from lp.registry.interfaces.milestone import IHasMilestones, IMilestone
from lp.registry.interfaces.person import IPerson
from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.registry.interfaces.role import IHasAppointedDriver, IHasOwner
from lp.registry.interfaces.series import ISeriesMixin, SeriesStatus
from lp.registry.interfaces.sourcepackage import ISourcePackage
from lp.services.fields import (
    ContentNameField,
    Description,
    PublicPersonChoice,
    Title,
    UniqueField,
)
from lp.services.webservice.apihelpers import (
    patch_collection_return_type,
    patch_plain_parameter_type,
    patch_reference_property,
)
from lp.soyuz.enums import (
    IndexCompressionType,
    PackageUploadCustomFormat,
    PackageUploadStatus,
)
from lp.soyuz.interfaces.buildrecords import IHasBuildRecords
from lp.translations.interfaces.hastranslationimports import (
    IHasTranslationImports,
)
from lp.translations.interfaces.hastranslationtemplates import (
    IHasTranslationTemplates,
)
from lp.translations.interfaces.languagepack import ILanguagePack


class DistroSeriesNameField(ContentNameField):
    """A class to ensure `IDistroSeries` has unique names."""

    errormessage = _("%s is already in use by another series.")

    @property
    def _content_iface(self):
        """See `IField`."""
        return IDistroSeries

    def _getByName(self, name):
        """See `IField`."""
        try:
            if self._content_iface.providedBy(self.context):
                return self.context.distribution.getSeries(name)
            else:
                return self.context.getSeries(name)
        except NoSuchDistroSeries:
            # The name is available for the new series.
            return None


class DistroSeriesVersionField(UniqueField):
    """A class to ensure `IDistroSeries` has unique versions."""

    errormessage = _(
        "%s is already in use by another version in this distribution."
    )
    attribute = "version"

    @property
    def _content_iface(self):
        return IDistroSeries

    @property
    def _distribution(self):
        if self._content_iface.providedBy(self.context):
            return self.context.distribution
        else:
            return self.context

    def _getByName(self, version):
        """Return the `IDistroSeries` for the specified distribution version.

        The distribution is the context's distribution (which may
        the context itself); A version is unique to a distribution.
        """
        existing = getUtility(IDistroSeriesSet).queryByVersion(
            self._distribution, version
        )
        if existing != self.context:
            return existing

    def _getByAttribute(self, version):
        """Return the content object with the given attribute."""
        return self._getByName(version)

    def _validate(self, version):
        """See `UniqueField`."""
        super()._validate(version)
        if not sane_version(version):
            raise LaunchpadValidationError(
                "%s is not a valid version" % version
            )
        # Avoid circular import hell.
        from lp.archivepublisher.debversion import Version, VersionError

        try:
            # XXX sinzui 2009-07-25 bug=404613: DistributionMirror and buildd
            # have stricter version rules than the schema. The version must
            # be a debversion.
            Version(version)
        except VersionError as error:
            raise LaunchpadValidationError("'%s': %s" % (version, error))


class DistroSeriesTranslationTemplateStatistics(typing.TypedDict):
    # The name of the source package that uses the template.
    sourcepackage: str
    # The translation domain for the template.
    translation_domain: str
    # The name of the template.
    template_name: str
    # The number of translation messages for the template.
    total: int
    # Whether the template is active.
    enabled: bool
    # Whether the template is part of a language pack.
    languagepack: bool
    # A number that describes how important this template is; templates
    # with higher priorities should be translated first.
    priority: int
    # When the template was last updated.
    date_last_updated: datetime


class IDistroSeriesPublic(
    ISeriesMixin,
    IHasAppointedDriver,
    IHasOwner,
    IBugTarget,
    ISpecificationGoal,
    IHasMilestones,
    IHasOfficialBugTags,
    IHasBuildRecords,
    IHasTranslationImports,
    IHasTranslationTemplates,
    IServiceUsage,
    IHasExpirableBugs,
):
    """Public IDistroSeries properties."""

    id = Attribute("The distroseries's unique number.")
    name = exported(
        DistroSeriesNameField(
            title=_("Name"),
            required=True,
            description=_("The name of this series."),
            constraint=name_validator,
        )
    )
    display_name = exported(
        TextLine(
            title=_("Display name"),
            required=True,
            description=_("The series displayname."),
        ),
        exported_as="displayname",
    )
    displayname = Attribute("Display name (deprecated)")
    fullseriesname = exported(
        TextLine(
            title=_("Series full name"),
            required=False,
            description=_("The series full name, e.g. Ubuntu Warty"),
        )
    )
    title = exported(
        Title(
            title=_("Title"),
            required=True,
            description=_(
                "The title of this series. It should be distinctive "
                "and designed to look good at the top of a page."
            ),
        )
    )
    description = exported(
        Description(
            title=_("Description"),
            required=True,
            description=_(
                "A detailed description of this series, with "
                "information on the architectures covered, the "
                "availability of security updates and any other "
                "relevant information."
            ),
        )
    )
    version = exported(
        DistroSeriesVersionField(
            title=_("Version"),
            required=True,
            description=_("The version string for this series."),
        )
    )
    distribution = exported(
        Reference(
            # Really IDistribution, patched in
            # lp.registry.interfaces.webservice.
            Interface,
            title=_("Distribution"),
            required=True,
            description=_("The distribution for which this is a series."),
        )
    )
    distribution_id = Attribute("The distribution ID.")
    named_version = Attribute("The combined display name and version.")
    parent = Attribute("The structural parent of this series - the distro")
    components = Attribute("The series components.")
    # IComponent is not exported on the api.
    component_names = exported(
        List(
            value_type=TextLine(),
            title=_("The series component names"),
            readonly=True,
        )
    )
    upload_components = Attribute(
        "The series components that can be " "uploaded to."
    )
    suite_names = exported(
        List(
            value_type=TextLine(),
            title=_("The series pocket names"),
            readonly=True,
        )
    )
    sections = Attribute("The series sections.")
    status = exported(
        Choice(title=_("Status"), required=True, vocabulary=SeriesStatus)
    )
    datereleased = exported(Datetime(title=_("Date released")))
    previous_series = exported(
        ReferenceChoice(
            title=_("Parent series"),
            description=_("The series from which this one was branched."),
            required=True,
            # Really IDistroSeries, patched below.
            schema=Interface,
            vocabulary="DistroSeries",
        ),
        ("devel", dict(exported_as="previous_series")),
        ("1.0", dict(exported_as="parent_series")),
        ("beta", dict(exported_as="parent_series")),
        readonly=True,
    )
    registrant = exported(
        PublicPersonChoice(
            title=_("Registrant"), vocabulary="ValidPersonOrTeam"
        )
    )
    owner = exported(
        Reference(
            IPerson,
            title=_("Owning team of the derived series"),
            readonly=True,
            description=_(
                "This attribute mirrors the owner of the distribution."
            ),
        )
    )
    date_created = exported(
        Datetime(title=_("The date this series was registered."))
    )
    driver = exported(
        ReferenceChoice(
            title=_("Driver"),
            description=_(
                "The person or team responsible for decisions about features "
                "and bugs that will be targeted to this series of the "
                "distribution."
            ),
            required=False,
            vocabulary="ValidPersonOrTeam",
            schema=IPerson,
        )
    )
    changeslist = exported(
        TextLine(
            title=_("Email changes to"),
            required=True,
            description=_(
                "The mailing list or other email address that "
                "Launchpad should notify about new uploads."
            ),
            constraint=email_validator,
        )
    )
    sourcecount = Attribute("Source Packages Counter")
    defer_translation_imports = Bool(
        title=_("Defer translation imports"),
        description=_("Suspends any translation imports for this series"),
        default=True,
        required=True,
    )
    binarycount = Attribute("Binary Packages Counter")

    architecturecount = Attribute(
        "The number of architectures in this " "series."
    )
    nominatedarchindep = exported(
        Reference(
            # Really IDistroArchSeries, patched in
            # lp.registry.interfaces.webservice.
            Interface,
            title=_(
                "DistroArchSeries designed to build "
                "architecture-independent packages within this "
                "distroseries context."
            ),
            default=None,
            required=False,
        )
    )
    messagecount = Attribute(
        "The total number of translatable items in " "this series."
    )
    distroserieslanguages = Attribute(
        "The set of dr-languages in this " "series."
    )

    hide_all_translations = Bool(
        title="Hide translations for this release",
        required=True,
        description=(
            "You may hide all translation for this distribution series so"
            " that only Launchpad administrators will be able to see them."
            " For example, you should hide these translations while they are"
            " being imported from a previous series so that translators"
            " will not be confused by imports that are in progress."
        ),
        default=True,
    )

    language_pack_base = Choice(
        title=_("Language pack base"),
        required=False,
        description=_(
            """
            Language pack with the export of all translations
            available for this distribution series when it was generated. The
            subsequent update exports will be generated based on this one.
            """
        ),
        vocabulary="FilteredFullLanguagePack",
    )

    language_pack_delta = Choice(
        title=_("Language pack update"),
        required=False,
        description=_(
            """
            Language pack with the export of all translation updates
            available for this distribution series since the language pack
            base was generated.
            """
        ),
        vocabulary="FilteredDeltaLanguagePack",
    )

    language_pack_proposed = Choice(
        title=_("Proposed language pack update"),
        required=False,
        description=_(
            """
            Base or update language pack export that is being tested and
            proposed to be used as the new language pack base or
            language pack update for this distribution series.
            """
        ),
        vocabulary="FilteredLanguagePack",
    )

    language_pack_full_export_requested = exported(
        Bool(
            title=_("Request a full language pack export"),
            required=True,
            description=_(
                """
            Whether next language pack generation will be a full export. This
            information is useful when update packs are too big and want to
            merge all those changes in the base pack.
            """
            ),
        )
    )

    last_full_language_pack_exported = Object(
        title=_("Latest exported language pack with all translation files."),
        required=False,
        readonly=True,
        schema=ILanguagePack,
    )

    last_delta_language_pack_exported = Object(
        title=_(
            "Latest exported language pack with updated translation files."
        ),
        required=False,
        readonly=True,
        schema=ILanguagePack,
    )

    # related joins
    packagings = Attribute(
        "All of the Packaging entries for this " "distroseries."
    )
    specifications = Attribute(
        "The specifications targeted to this " "series."
    )

    language_packs = Attribute(
        "All language packs associated with this distribution series."
    )

    backports_not_automatic = exported(
        Bool(
            title=_("Don't upgrade to backports automatically"),
            required=True,
            description=_(
                """
            Set NotAutomatic: yes and ButAutomaticUpgrades: yes in Release
            files generated for the backports pocket. This tells apt to
            automatically upgrade within backports, but not into it.
            """
            ),
        )
    )

    proposed_not_automatic = exported(
        Bool(
            title=_("Don't upgrade to proposed updates automatically"),
            required=True,
            description=_(
                """
            Set NotAutomatic: yes and ButAutomaticUpgrades: yes in Release
            files generated for the proposed pocket. This tells apt to
            automatically upgrade within proposed, but not into it.
            """
            ),
        )
    )

    include_long_descriptions = exported(
        Bool(
            title=_(
                "Include long descriptions in Packages rather than in "
                "Translation-en"
            ),
            default=True,
            required=True,
            description=_(
                """
                If True, write long descriptions to the per-architecture
                Packages files; if False, write them to a Translation-en
                file common across architectures instead. Using a common
                file reduces the bandwidth footprint of enabling multiarch
                on clients, which requires downloading Packages files for
                multiple architectures."""
            ),
        )
    )

    index_compressors = exported(
        List(
            value_type=Choice(vocabulary=IndexCompressionType),
            title=_("Compression types to use for published index files"),
            required=True,
            description=_(
                """
            A list of compression types to use for published index files
            (Packages, Sources, etc.)."""
            ),
        )
    )

    publish_by_hash = exported(
        Bool(
            title=_("Publish by-hash directories"),
            required=True,
            description=_(
                """
            Publish archive index files in by-hash directories so that apt
            can retrieve them based on their hash, avoiding race conditions
            between InRelease and other files during mirror updates."""
            ),
        )
    )

    advertise_by_hash = exported(
        Bool(
            title=_("Advertise by-hash directories"),
            required=True,
            description=_(
                """
            Advertise by-hash directories with a flag in the Release file so
            that apt uses them by default.  Only effective if
            publish_by_hash is also set."""
            ),
        )
    )

    strict_supported_component_dependencies = exported(
        Bool(
            title=_("Strict dependencies of supported components"),
            required=True,
            description=_(
                """
            If True, packages in supported components (main and restricted)
            may not build-depend on packages in unsupported components.  Do
            not rely on the name of this attribute, even for reading; it is
            currently subject to change."""
            ),
        ),
        as_of="devel",
    )

    publish_i18n_index = exported(
        Bool(
            title=_("Publish I18n index"),
            required=True,
            description=_(
                """
            Publish archive i18n/Index file, which is believed to be unused."""
            ),
        )
    )

    inherit_overrides_from_parents = Bool(
        title=_("Inherit overrides from parents"),
        readonly=False,
        required=True,
    )

    main_archive = exported(
        Reference(
            # Really IArchive, patched in lp.registry.interfaces.webservice.
            Interface,
            title=_("Distribution Main Archive"),
        )
    )

    supported = exported(
        Bool(
            title=_("Supported"),
            description=_(
                "Whether or not this series is currently supported."
            ),
        )
    )

    def isUnstable():
        """Whether or not a distroseries is unstable.

        The distribution is "unstable" until it is released; after that
        point, all development on the Release pocket is stopped and
        development moves on to the other pockets.
        """

    def getLatestUploads():
        """Return the latest five source uploads for this DistroSeries.

        It returns a list containing up to five elements as
        IDistributionSourcePackageRelease instances
        """

    # DistroArchSeries lookup properties/methods.
    architectures = Attribute("All architectures in this series.")

    enabled_architectures = exported(
        doNotSnapshot(
            CollectionField(
                title=_("Enabled architectures"),
                description=_(
                    "All architectures in this series with the "
                    "'enabled' flag set."
                ),
                # Really IDistroArchSeries, patched in
                # lp.registry.interfaces.webservice.
                value_type=Reference(schema=Interface),
                readonly=True,
            )
        ),
        exported_as="architectures",
    )

    virtualized_architectures = Attribute(
        "All architectures in this series where PPA is supported."
    )

    buildable_architectures = Attribute(
        "All architectures in this series with available chroot tarball."
    )

    def __getitem__(archtag):
        """Return the distroarchseries for this distroseries with the
        given architecturetag.
        """

    def __str__():
        """Return the name of the distroseries."""

    def getDistroArchSeriesByProcessor(processor):
        """Return the distroarchseries for this distroseries with the
        given architecturetag from a `IProcessor`.

        :param processor: An `IProcessor`
        :return: An `IDistroArchSeries` or None when none was found.
        """

    @operation_parameters(
        archtag=TextLine(title=_("The architecture tag"), required=True)
    )
    # Really IDistroArchSeries, patched in
    # lp.registry.interfaces.webservice.
    @operation_returns_entry(Interface)
    @export_read_operation()
    @operation_for_version("beta")
    def getDistroArchSeries(archtag):
        """Return the distroarchseries for this distroseries with the
        given architecturetag.
        """

    # End of DistroArchSeries lookup methods.

    def updateStatistics(ztm):
        """Update all the Rosetta stats for this distro series."""

    def updatePackageCount():
        """Update the binary and source package counts for this distro
        series."""

    @operation_parameters(
        name=TextLine(title=_("The name of the source package"), required=True)
    )
    @operation_returns_entry(ISourcePackage)
    @export_read_operation()
    @operation_for_version("beta")
    def getSourcePackage(name):
        """Return a source package in this distro series by name.

        The name given may be a string or an ISourcePackageName-providing
        object. The source package may not be published in the distro series.
        """

    def getTranslatableSourcePackages():
        """Return a list of Source packages in this distribution series
        that can be translated.
        """

    def getPrioritizedUnlinkedSourcePackages():
        """Return a list of package summaries that need packaging links.

        A summary is a dict of package (`ISourcePackage`), total_bugs,
        and total_messages (translatable messages).
        """

    def getPrioritizedPackagings():
        """Return a list of packagings that need more upstream information."""

    def getMostRecentlyLinkedPackagings():
        """Return a list of packagings that are the most recently linked.

        At most five packages are returned of those most recently linked to an
        upstream.
        """

    @operation_parameters(
        created_since_date=Datetime(
            title=_("Created Since Timestamp"),
            description=_(
                "Return items that are more recent than this timestamp."
            ),
            required=False,
        ),
        status=Choice(
            vocabulary=PackageUploadStatus,
            title=_("Package Upload Status"),
            description=_("Return only items that have this status."),
            required=False,
        ),
        archive=Reference(
            # Really IArchive, patched in lp.registry.interfaces.webservice.
            schema=Interface,
            title=_("Archive"),
            description=_("Return only items for this archive."),
            required=False,
        ),
        pocket=Choice(
            vocabulary=PackagePublishingPocket,
            title=_("Pocket"),
            description=_("Return only items targeted to this pocket"),
            required=False,
        ),
        custom_type=Choice(
            vocabulary=PackageUploadCustomFormat,
            title=_("Custom Type"),
            description=_(
                "Return only items with custom files of this " "type."
            ),
            required=False,
        ),
        name=TextLine(title=_("Package or file name"), required=False),
        version=TextLine(title=_("Package version"), required=False),
        exact_match=Bool(
            title=_("Exact match"),
            description=_(
                "Whether to filter name and version by exact " "matching."
            ),
            required=False,
        ),
    )
    # Really IPackageUpload, patched in lp.registry.interfaces.webservice.
    @operation_returns_collection_of(Interface)
    @export_read_operation()
    @operation_for_version("beta")
    def getPackageUploads(
        status=None,
        created_since_date=None,
        archive=None,
        pocket=None,
        custom_type=None,
        name=None,
        version=None,
        exact_match=False,
    ):
        """Get package upload records for this distribution series.

        :param status: Filter results by this `PackageUploadStatus`, or list
            of statuses.
        :param created_since_date: If specified, only returns items uploaded
            since the timestamp supplied.
        :param archive: Filter results for this `IArchive`.
        :param pocket: Filter results by this `PackagePublishingPocket` or a
            list of `PackagePublishingPocket`.
        :param custom_type: Filter results by this
            `PackageUploadCustomFormat`.
        :param name: Filter results by this file name or package name.
        :param version: Filter results by this version number string.
        :param exact_match: If True, look for exact string matches on the
            `name` and `version` filters.  If False, look for a substring
            match so that e.g. a package "kspreadsheetplusplus" would match
            the search string "spreadsheet".  Defaults to False.
        :return: A result set containing `IPackageUpload`.
        """

    def getUnlinkedTranslatableSourcePackages():
        """Return a list of source packages that can be translated in
        this distribution series but which lack Packaging links.
        """

    def getBinaryPackage(name):
        """Return a DistroSeriesBinaryPackage for this name.

        The name given may be an IBinaryPackageName or a string.  The
        binary package may not be published in the distro series.
        """

    def getCurrentSourceReleases(source_package_names):
        """Get the current release of a list of source packages.

        :param source_package_names: a list of `ISourcePackageName`
            instances.

        :return: a dict where the key is a `ISourcePackage`
            and the value is a `IDistributionSourcePackageRelease`.
        """

    def getAllPublishedSources():
        """Return all currently published sources for the distroseries.

        Return publications in the main archives only.
        """

    def getAllUncondemnedSources():
        """Return all uncondemned sources for the distroseries.

        An uncondemned publication is one without scheduleddeletiondate set.

        Return publications in the main archives only.
        """

    def getAllPublishedBinaries():
        """Return all currently published binaries for the distroseries.

        Return publications in the main archives only.
        """

    def getAllUncondemnedBinaries():
        """Return all uncondemned binaries for the distroseries.

        An uncondemned publication is one without scheduleddeletiondate set.

        Return publications in the main archives only.
        """

    def getDistroSeriesLanguage(language):
        """Return the DistroSeriesLanguage for this distroseries and the
        given language, or None if there's no DistroSeriesLanguage for this
        distribution and the given language.
        """

    def getDistroSeriesLanguageOrEmpty(language):
        """Return the DistroSeriesLanguage for this distroseries and the
        given language, or an EmptyDistroSeriesLanguage.
        """

    def createUploadedSourcePackageRelease(
        sourcepackagename,
        version,
        format,
        architecturehintlist,
        creator,
        archive,
        maintainer=None,
        component=None,
        section=None,
        urgency=None,
        dscsigningkey=None,
        dsc=None,
        copyright=None,
        changelog=None,
        changelog_entry=None,
        builddepends=None,
        builddependsindep=None,
        build_conflicts=None,
        build_conflicts_indep=None,
        dsc_maintainer_rfc822=None,
        dsc_standards_version=None,
        dsc_format=None,
        dsc_binaries=None,
        dateuploaded=None,
        source_package_recipe_build=None,
        ci_build=None,
        user_defined_fields=None,
        homepage=None,
        buildinfo=None,
    ):
        """Create an uploaded `SourcePackageRelease`.

        Set this distroseries to be the `upload_distroseries`.

        Arguments are extracted/built when processing an uploaded source
        package:

        :param sourcepackagename: `ISourcePackageName`
        :param version: string, a valid Debian version
        :param format: `SourcePackageType`
        :param architecturehintlist: string, DSC architectures
        :param creator: `IPerson`, package uploader
        :param archive: `IArchive` to where the upload was targeted
        :param maintainer: `IPerson` designated as package maintainer
        :param component: `IComponent`
        :param section: `ISection`
        :param urgency: `SourcePackageUrgency`
        :param dscsigningkey: `IGPGKey` used to sign the DSC file
        :param dsc: string, original content of the dsc file
        :param copyright: string, the original debian/copyright content
        :param changelog: LFA ID of the debian/changelog file in librarian
        :param changelog_entry: string, changelog extracted from the
                                changesfile
        :param builddepends: string, DSC build dependencies
        :param builddependsindep: string, DSC architecture independent build
                                  dependencies
        :param build_conflicts: string, DSC Build-Conflicts content
        :param build_conflicts_indep: string, DSC Build-Conflicts-Indep
                                      content
        :param dsc_maintainer_rfc822: string, DSC maintainer field
        :param dsc_standards_version: string, DSC standards version field
        :param dsc_format: string, DSC format version field
        :param dsc_binaries: string, DSC binaries field
        :param dateuploaded: optional datetime, if omitted assumed `UTC_NOW`
        :param source_package_recipe_build: optional `SourcePackageRecipeBuild`
        :param ci_build: optional `CIBuild`
        :param user_defined_fields: optional sequence of key-value pairs with
                                    user defined fields
        :param homepage: optional string with (unchecked) upstream homepage
                         URL
        :param buildinfo: optional LFA with build information file
        :return: the new `SourcePackageRelease`
        """

    def getComponentByName(name):
        """Get the named component.

        Raise NotFoundError if the component is not in the permitted component
        list for this distroseries.
        """

    def searchPackages(text):
        """Search through the package cache for this distroseries and return
        DistroSeriesBinaryPackage objects that match the given text.
        """

    def createQueueEntry(
        pocket,
        archive,
        changesfilename=None,
        changesfilecontent=None,
        changes_file_alias=None,
        signingkey=None,
        package_copy_job=None,
    ):
        """Create a queue item attached to this distroseries.

        Create a new `PackageUpload` to the given pocket and archive.

        The default state is NEW.  Any further state changes go through
        the Queue state-machine.

        :param pocket: The `PackagePublishingPocket` to upload to.
        :param archive: The `Archive` to upload to.  Must be for the same
            `Distribution` as this series.
        :param changesfilename: Name for the upload's .changes file.  You may
            specify a changes file by passing both `changesfilename` and
            `changesfilecontent`, or by passing `changes_file_alias`.
        :param changesfilecontent: Bytes for the changes file.  It will be
            signed and stored in the Librarian.  Must be passed together with
            `changesfilename`; alternatively, you may provide a
            `changes_file_alias` to replace both of these.
        :param changes_file_alias: A `LibraryFileAlias` containing the
            .changes file.  Security warning: unless the file has already
            been checked, this may open us up to replay attacks as per bugs
            159304 and 451396.  Use `changes_file_alias` only if you know
            this can't happen.
        :param signingkey: `IGPGKey` used to sign the changes file, or None if
            it is unsigned.
        :return: A new `PackageUpload`.
        """

    def newArch(architecturetag, processor, official, owner, enabled=True):
        """Create a new port or DistroArchSeries for this DistroSeries."""

    def getPOFileContributorsByLanguage(language):
        """People who translated strings to the given language.

        The people that translated only IPOTemplate objects that are not
        current will not appear in the returned list.
        """

    def getSuite(pocket):
        """Return the suite for this distro series and the given pocket.

        :param pocket: A `DBItem` of `PackagePublishingPocket`.
        :return: A string.
        """

    def isSourcePackageFormatPermitted(format):
        """Check if the specified source format is allowed in this series.

        :param format: The SourcePackageFormat to check.
        """

    # Really IDistroSeries, patched below.
    @operation_returns_collection_of(Interface)
    @export_read_operation()
    @operation_for_version("beta")
    def getDerivedSeries():
        """Get all `DistroSeries` derived from this one."""

    # Really IDistroSeries, patched below.
    @operation_returns_collection_of(Interface)
    @export_read_operation()
    @operation_for_version("beta")
    def getParentSeries():
        """Get all parent `DistroSeries`."""

    @operation_parameters(
        parent_series=Reference(
            # Really IDistroSeries, patched below.
            schema=Interface,
            title=_("The parent series to consider."),
            required=False,
        ),
        difference_type=Choice(
            vocabulary=DistroSeriesDifferenceType,
            title=_("Only return differences of this type."),
            required=False,
        ),
        source_package_name_filter=TextLine(
            title=_(
                "Only return differences for packages matching this " "name."
            ),
            required=False,
        ),
        status=Choice(
            vocabulary=DistroSeriesDifferenceStatus,
            title=_("Only return differences of this status."),
            required=False,
        ),
        child_version_higher=Bool(
            title=_(
                "Only return differences for which the child's version "
                "is higher than the parent's."
            ),
            required=False,
        ),
    )
    # Really IDistroSeriesDifference, patched in
    # lp.registry.interfaces.webservice.
    @operation_returns_collection_of(Interface)
    @export_read_operation()
    @operation_for_version("devel")
    def getDifferencesTo(
        parent_series,
        difference_type,
        source_package_name_filter,
        status,
        child_version_higher,
    ):
        """Return the differences between this series and the specified
        parent_series (or all the parent series if parent_series is None).

        :param parent_series: The parent series for which the differences
            should be returned. All parents are considered if this is None.
        :param difference_type: The type of the differences to return.
        :param source_package_name_filter: A package name to use as a filter
            for the differences.
        :param status: The status of the differences to return.
        :param child_version_higher: Only return differences for which the
            child's version is higher than the parent's version.
        """

    def isDerivedSeries():
        """Is this series a derived series?

        A derived series has one or more parent series.
        """

    def isInitializing():
        """Is this series initializing?"""

    def isInitialized():
        """Has this series been initialized?"""

    def getInitializationJob():
        """Get the last `IInitializeDistroSeriesJob` for this series.

        :return: `None` if no job is found or an `IInitializeDistroSeriesJob`.
        """

    @operation_parameters(
        since=Datetime(
            title=_("Minimum creation timestamp"),
            description=_("Ignore comments that are older than this."),
            required=False,
        ),
        source_package_name=TextLine(
            title=_("Name of source package"),
            description=_("Only return comments for this source package."),
            required=False,
        ),
    )
    # Really IDistroSeriesDifferenceComment, patched in
    # lp.registry.interfaces.webservice.
    @operation_returns_collection_of(Interface)
    @export_read_operation()
    @operation_for_version("devel")
    def getDifferenceComments(since=None, source_package_name=None):
        """Get `IDistroSeriesDifferenceComment` items.

        :param since: Ignore comments older than this timestamp.
        :param source_package_name: Return only comments for a source package
            with this name.
        :return: A Storm result set of `IDistroSeriesDifferenceComment`
            objects for this distroseries, ordered from oldest to newest
            comment.
        """

    @export_read_operation()
    @operation_for_version("devel")
    def getTranslationTemplateStatistics() -> (
        typing.List[DistroSeriesTranslationTemplateStatistics]
    ):
        """Return statistics for translation templates in this series.

        The return value is a list of dicts for each template in the series,
        each of which has this form::

            {
                "sourcepackage": ...,
                "translation_domain": ...,
                "name": ...,
                "total": ...,
                "enabled": ...,
                "languagepack": ...,
                "priority": ...,
                "date_last_updated": ...,
            }
        """


class IDistroSeriesEditRestricted(Interface):
    """IDistroSeries properties which require launchpad.Edit."""

    @rename_parameters_as(dateexpected="date_targeted")
    @export_factory_operation(
        IMilestone, ["name", "dateexpected", "summary", "code_name"]
    )
    @operation_for_version("beta")
    def newMilestone(name, dateexpected=None, summary=None, code_name=None):
        """Create a new milestone for this DistroSeries."""

    @operation_parameters(
        parents=List(
            title=_("The list of parents to derive from."),
            value_type=TextLine(),
            required=True,
        ),
        architectures=List(
            title=_(
                "The list of architectures to copy to the derived "
                "distroseries."
            ),
            value_type=TextLine(),
            required=False,
        ),
        archindep_archtag=TextLine(
            title=_(
                "Architecture tag to build architecture-independent "
                "packages."
            ),
            required=False,
        ),
        packagesets=List(
            title=_(
                "The list of packagesets to copy to the derived "
                "distroseries"
            ),
            value_type=TextLine(),
            required=False,
        ),
        rebuild=Bool(
            title=_(
                "If binaries will be copied to the derived " "distroseries."
            ),
            required=True,
        ),
        overlays=List(
            title=_(
                "The list of booleans indicating, for each parent, if "
                "the parent/child relationship should be an overlay."
            ),
            value_type=Bool(),
            required=False,
        ),
        overlay_pockets=List(
            title=_("The list of overlay pockets."),
            value_type=TextLine(),
            required=False,
        ),
        overlay_components=List(
            title=_("The list of overlay components."),
            value_type=TextLine(),
            required=False,
        ),
    )
    @call_with(user=REQUEST_USER)
    @export_write_operation()
    @operation_for_version("beta")
    def initDerivedDistroSeries(
        user,
        parents,
        architectures=[],
        archindep_archtag=None,
        packagesets=[],
        rebuild=False,
        overlays=[],
        overlay_pockets=[],
        overlay_components=[],
    ):
        """Initialize this series from parents.

        This method performs checks and then creates a job to populate
        the new distroseries.

        :param parents: The list of parent ids this series will derive
            from.
        :param architectures: The architectures to copy to the derived
            series. If not specified, all of the architectures are copied.
        :param archindep_archtag: The architecture tag used to build
            architecture-independent packages. If not specified, one from
            the parents' will be used.
        :param packagesets: The packagesets to copy to the derived series.
            If not specified, all of the packagesets are copied.
        :param rebuild: Whether binaries will be copied to the derived
            series. If it's true, they will not be, and if it's false, they
            will be.
        :param overlays: A list of booleans indicating, for each parent, if
            the parent/child relationship should be an overlay.
        :param overlay_pockets: The list of pockets names to use for overlay
            relationships.
        :param overlay_components: The list of components names to use for
            overlay relationships.
        """


@exported_as_webservice_entry(as_of="beta")
class IDistroSeries(
    IDistroSeriesEditRestricted,
    IDistroSeriesPublic,
    IStructuralSubscriptionTarget,
):
    """A series of an operating system distribution."""


patch_reference_property(IDistroSeries, "previous_series", IDistroSeries)
patch_collection_return_type(IDistroSeries, "getDerivedSeries", IDistroSeries)
patch_collection_return_type(IDistroSeries, "getParentSeries", IDistroSeries)
patch_plain_parameter_type(
    IDistroSeries, "getDifferencesTo", "parent_series", IDistroSeries
)

# We assign the schema for an `IHasBugs` method argument here
# in order to avoid circular dependencies.
patch_plain_parameter_type(
    IHasBugs, "searchTasks", "nominated_for", IDistroSeries
)


class IDistroSeriesSet(Interface):
    """The set of distro seriess."""

    def get(distroseriesid):
        """Retrieve the distro series with the given distroseriesid."""

    def translatables():
        """Return a set of distroseriess that can be translated in
        rosetta."""

    def queryByName(distribution, name, follow_aliases=False):
        """Query a DistroSeries by name.

        :distribution: An IDistribution.
        :name: A string.
        :follow_aliases: If True, follow series aliases.

        Returns the matching DistroSeries, or None if not found.
        """

    def queryByVersion(distribution, version):
        """Query a DistroSeries by version.

        :distribution: An IDistribution.
        :name: A string.

        Returns the matching DistroSeries, or None if not found.
        """

    def fromSuite(distribution, suite):
        """Return the distroseries and pocket for 'suite' of 'distribution'.

        :param distribution: An `IDistribution`.
        :param suite: A string that forms the name of a suite.
        :return: (`IDistroSeries`, `DBItem`) where the item is from
            `PackagePublishingPocket`.
        """

    def getCurrentSourceReleases(distro_series_source_packagenames):
        """Lookup many distroseries source package releases.

        :param distro_series_to_source_packagenames: A dictionary with
            its keys being `IDistroSeries` and its values a list of
            `ISourcePackageName`.
        :return: A dict as per `IDistroSeries.getCurrentSourceReleases`
        """

    def search(distribution=None, released=None, orderBy=None):
        """Search the set of distro seriess.

        released == True will filter results to only include
        IDistroSeries with status CURRENT or SUPPORTED.

        released == False will filter results to only include
        IDistroSeriess with status EXPERIMENTAL, DEVELOPMENT,
        FROZEN.

        released == None will do no filtering on status.
        """


@error_status(http.client.BAD_REQUEST)
class DerivationError(Exception):
    """Raised when there is a problem deriving a distroseries."""

    _message_prefix = "Error deriving distro series"
