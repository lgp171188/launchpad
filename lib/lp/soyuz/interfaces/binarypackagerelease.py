# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Binary package release interfaces."""

__all__ = [
    "BinaryPackageReleaseNameLinkageError",
    "IBinaryPackageRelease",
    "IBinaryPackageReleaseDownloadCount",
]

import http.client

from lazr.restful.declarations import (
    error_status,
    exported,
    exported_as_webservice_entry,
)
from lazr.restful.fields import Reference, ReferenceChoice
from zope.interface import Attribute, Interface
from zope.schema import Bool, Date, Datetime, Int, List, Object, Text, TextLine

from lp import _
from lp.app.validators.version import valid_debian_version
from lp.services.worlddata.interfaces.country import ICountry
from lp.soyuz.interfaces.archive import IArchive


@error_status(http.client.BAD_REQUEST)
class BinaryPackageReleaseNameLinkageError(ValueError):
    """A binary package name is inappropriate for this release's format."""


class IBinaryPackageRelease(Interface):
    id = Int(title=_("ID"), required=True)
    binarypackagename = Int(required=True)
    binarypackagename_id = Int(required=True)
    version = TextLine(required=True, constraint=valid_debian_version)
    summary = Text(required=True)
    description = Text(required=True)
    build = Reference(
        # Really IBinaryPackageBuild.
        Interface,
        required=False,
    )
    ci_build = Reference(
        # Really ICIBuild.
        Interface,
        required=False,
    )
    binpackageformat = Int(required=True)
    component = Int(required=False)
    section = Int(required=False)
    priority = Int(required=False)
    shlibdeps = TextLine(required=False)
    depends = TextLine(required=False)
    recommends = TextLine(required=False)
    suggests = TextLine(required=False)
    conflicts = TextLine(required=False)
    replaces = TextLine(required=False)
    provides = TextLine(required=False)
    pre_depends = TextLine(required=False)
    enhances = TextLine(required=False)
    breaks = TextLine(required=False)
    built_using_references = List(
        title=_("Sequence of Built-Using references."),
        # Really IBinarySourceReference.
        value_type=Reference(schema=Interface),
        required=True,
    )
    essential = Bool(required=False)
    installedsize = Int(required=False)
    architecturespecific = Bool(required=True)
    datecreated = Datetime(required=True, readonly=True)
    debug_package = Object(
        title=_("Debug package"),
        schema=Interface,
        required=False,
        description=_(
            "The corresponding package containing debug symbols "
            "for this binary."
        ),
    )
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

    files = Attribute("Related list of IBinaryPackageFile entries")

    title = TextLine(required=True, readonly=True)
    name = Attribute("Binary Package Name")
    sourcepackagename = Attribute(
        "The name of the source package from where this binary was built."
    )
    sourcepackageversion = Attribute(
        "The version of the source package from where this binary was built."
    )

    def getUserDefinedField(name):
        """Case-insensitively get a user-defined field."""

    def addFile(file, filetype=None):
        """Create a BinaryPackageFile record referencing this build
        and attach the provided library file alias (file).

        If filetype is None, then the file type is automatically detected
        based on the file name, if possible.
        """

    def override(component=None, section=None, priority=None):
        """Uniform method to override binarypackagerelease attribute.

        All arguments are optional and can be set individually. A non-passed
        argument remains untouched.
        """


@exported_as_webservice_entry(as_of="beta")
class IBinaryPackageReleaseDownloadCount(Interface):
    """Daily download count of a binary package release in an archive."""

    id = Int(title=_("ID"), required=True, readonly=True)
    archive = exported(
        Reference(
            title=_("Archive"), schema=IArchive, required=True, readonly=True
        )
    )
    binary_package_release = Reference(
        title=_("The binary package release"),
        schema=IBinaryPackageRelease,
        required=True,
        readonly=True,
    )
    binary_package_name = exported(
        TextLine(title=_("Binary package name"), required=False, readonly=True)
    )
    binary_package_version = exported(
        TextLine(
            title=_("Binary package version"), required=False, readonly=True
        )
    )
    day = exported(
        Date(title=_("Day of the downloads"), required=True, readonly=True)
    )
    count = exported(
        Int(title=_("Number of downloads"), required=True, readonly=True)
    )
    country = exported(
        ReferenceChoice(
            title=_("Country"),
            required=False,
            readonly=True,
            vocabulary="CountryName",
            schema=ICountry,
        )
    )

    country_code = TextLine(
        title=_("Country code"),
        required=True,
        readonly=True,
        description=_(
            'The ISO 3166-2 country code for this count, or "unknown".'
        ),
    )
