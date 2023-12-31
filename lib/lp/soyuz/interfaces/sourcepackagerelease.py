# Copyright 2009-2017 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Source package release interfaces."""

__all__ = [
    "ISourcePackageRelease",
]


from lazr.restful.fields import Reference
from zope.interface import Attribute, Interface
from zope.schema import List, TextLine

from lp import _


class ISourcePackageRelease(Interface):
    """A source package release, e.g. apache-utils 2.0.48-3"""

    id = Attribute("SourcePackageRelease identifier")
    creator_id = Attribute("DB ID of creator")
    creator = Attribute("Person that created this release")
    maintainer_id = Attribute("DB ID of the maintainer")
    maintainer = Attribute(
        "The person in general responsible for this " "release"
    )
    version = Attribute("A version string")
    dateuploaded = Attribute("Date of Upload")
    urgency = Attribute("Source Package Urgency")
    signing_key_owner = Attribute("Signing key owner")
    signing_key_fingerprint = Attribute("Signing key fingerprint")
    component = Attribute("Source Package Component")
    format = Attribute("The Source Package Format")
    changelog = Attribute("LibraryFileAlias containing debian/changelog.")
    changelog_entry = Attribute("Source Package Change Log Entry")
    change_summary = Attribute(
        "The message on the latest change in this release. This is usually "
        "a snippet from the changelog"
    )
    buildinfo = Attribute(
        "LibraryFileAlias containing build information for this source "
        "upload, if any."
    )
    builddepends = TextLine(
        title=_("DSC build depends"),
        description=_(
            "A comma-separated list of packages on which this "
            "package depends to build"
        ),
        required=False,
    )
    builddependsindep = TextLine(
        title=_("DSC arch-independent build depends"),
        description=_(
            "Same as builddepends, but the list is of "
            "arch-independent packages"
        ),
        required=False,
    )
    build_conflicts = TextLine(
        title=_("DSC build conflicts"),
        description=_(
            "Binaries that will conflict when building this " "source."
        ),
        required=False,
    )
    build_conflicts_indep = TextLine(
        title=_("DSC arch-independent build conflicts"),
        description=_(
            "Same as build-conflicts but only lists "
            "arch-independent binaries."
        ),
        required=False,
    )
    architecturehintlist = TextLine(
        title=_("Architecture Hint List"),
        description=_(
            "Architectures where this packages is supposed to be built"
        ),
        required=True,
    )
    dsc_maintainer_rfc822 = TextLine(
        title=_("DSC maintainers identification in RFC-822"),
        description=_("Original maintainer line contained in the DSC file."),
        required=True,
    )
    dsc_standards_version = TextLine(
        title=_("DSC Standards version"),
        description=_("DSC standards version used to build this source."),
        required=True,
    )
    dsc_format = TextLine(
        title=_("DSC format"),
        description=_("DSC file format used to upload this source"),
        required=False,
    )
    dsc_binaries = TextLine(
        title=_("DSC proposed binaries"),
        description=_("Binaries claimed to be generated by this source."),
        required=True,
    )
    dsc = Attribute("The DSC file for this SourcePackageRelease")
    copyright = Attribute(
        "Copyright information for this SourcePackageRelease, if available."
    )
    section = Attribute("Section this Source Package Release belongs to")
    builds = Attribute(
        "Builds for this sourcepackagerelease excluding PPA " "archives."
    )
    files = Attribute(
        "IBinaryPackageFile entries for this " "sourcepackagerelease"
    )
    sourcepackagename = Attribute("SourcePackageName table reference")
    sourcepackagename_id = Attribute("SourcePackageName id.")
    upload_distroseries = Attribute(
        "The distroseries in which this package "
        "was first uploaded in Launchpad"
    )
    publishings = Attribute("Publishing records that link to this release")

    user_defined_fields = List(
        title=_("Sequence of user-defined fields as key-value pairs.")
    )

    homepage = TextLine(
        title=_("Homepage"),
        description=_(
            "Upstream project homepage as set in the package. This URL is not "
            "sanitized."
        ),
        required=False,
    )

    # read-only properties
    name = Attribute("The sourcepackagename for this release, as text")
    title = Attribute("The title of this sourcepackagerelease")
    age = Attribute(
        "Time passed since the source package release "
        "is present in Launchpad"
    )
    failed_builds = Attribute(
        "A (potentially empty) list of build "
        "failures that happened for this source package "
        "release, or None"
    )
    needs_building = Attribute(
        "A boolean that indicates whether this package still needs to be "
        "built (on any architecture)"
    )

    published_archives = Attribute(
        "A set of all the archives that this "
        "source package is published in."
    )
    upload_archive = Attribute(
        "The archive for which this package was first uploaded in Launchpad"
    )

    upload_changesfile = Attribute(
        "The `LibraryFileAlias` object containing the changes file which "
        "was originally uploaded with this source package release. It's "
        "'None' if it is a source imported by Gina."
    )

    package_upload = Attribute(
        "The `PackageUpload` record corresponding to original upload of "
        "this source package release. It's 'None' if it is a source "
        "imported by Gina."
    )
    uploader = Attribute("The user who uploaded the package.")

    # Really ISourcePackageRecipeBuild, patched in
    # lp.soyuz.interfaces.webservice.
    source_package_recipe_build = Reference(
        schema=Interface,
        description=_(
            "The `SourcePackageRecipeBuild` which produced this source "
            "package release, or None if it was not created from a source "
            "package recipe."
        ),
        title=_("Source package recipe build"),
        required=False,
        readonly=True,
    )
    # Really ICIBuild, patched in lp.soyuz.interfaces.webservice.
    ci_build = Reference(
        schema=Interface,
        description=_(
            "The `CIBuild` which produced this source package release, or "
            "None if it was not created from a CI build."
        ),
        title=_("CI build"),
        required=False,
        readonly=True,
    )

    def getUserDefinedField(name):
        """Case-insensitively get a user-defined field."""

    def addFile(file, filetype=None):
        """Add the provided library file alias (file) to the list of files
        in this package.
        """

    def getFileByName(filename):
        """Return the corresponding `ILibraryFileAlias` in this context.

        The following file types (and extension) can be looked up in the
        SourcePackageRelease context:

         * Source files: '.orig.tar.gz', 'tar.gz', '.diff.gz' and '.dsc'.

        :param filename: the exact filename to be looked up.

        :raises NotFoundError if no file could be found.

        :return the corresponding `ILibraryFileAlias` if the file was found.
        """

    def override(component=None, section=None, urgency=None):
        """Uniform method to override sourcepackagerelease attribute.

        All arguments are optional and can be set individually. A non-passed
        argument remains untouched.
        """

    package_diffs = Attribute(
        "All `IPackageDiff` generated from this context."
    )

    def getDiffTo(to_sourcepackagerelease):
        """Return an `IPackageDiff` to a given `ISourcePackageRelease`.

        Return None if it was not yet requested.
        """

    def requestDiffTo(requester, to_sourcepackagerelease):
        """Request a package diff from the context source to a given source.

        :param: requester: it's the diff requester, any valid `IPerson`;
        :param: to_source: it's the `ISourcePackageRelease` to diff against.
        :raise `PackageDiffAlreadyRequested`: when there is already a
            `PackageDiff` record matching the request being made.

        :return: the corresponding `IPackageDiff` record.
        """

    def getPackageSize():
        """Get the size total (in KB) of files comprising this package.

        Please note: empty packages (i.e. ones with no files or with
        files that are all empty) have a size of zero.

        :return: total size (in KB) of this package
        """

    def aggregate_changelog(since_version):
        """Get all the changelogs since the version specified.

        :param since_version: Return changelogs of all versions
            after since_version up to and including the version of the
            sourcepackagerelease for this publication.
        :return: A concatenated set of changelogs of all the required
            versions, with a blank line between each.  If there is no
            changelog, or there is an error parsing it, None is returned.
        """
