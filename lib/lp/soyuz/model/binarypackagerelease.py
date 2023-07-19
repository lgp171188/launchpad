# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "BinaryPackageRelease",
    "BinaryPackageReleaseDownloadCount",
]

import json
import re
from datetime import timezone
from operator import attrgetter

from storm.locals import Bool, Date, DateTime, Int, Reference, Store, Unicode
from zope.component import getUtility
from zope.interface import implementer

from lp.app.validators.name import valid_name_pattern as debian_name_pattern
from lp.services.database.constants import UTC_NOW
from lp.services.database.enumcol import DBEnum
from lp.services.database.stormbase import StormBase
from lp.services.propertycache import cachedproperty, get_property_cache
from lp.soyuz.enums import (
    BinaryPackageFileType,
    BinaryPackageFormat,
    BinarySourceReferenceType,
    PackagePublishingPriority,
)
from lp.soyuz.interfaces.binarypackagename import IBinaryPackageName
from lp.soyuz.interfaces.binarypackagerelease import (
    BinaryPackageReleaseNameLinkageError,
    IBinaryPackageRelease,
    IBinaryPackageReleaseDownloadCount,
)
from lp.soyuz.interfaces.binarysourcereference import IBinarySourceReferenceSet
from lp.soyuz.model.files import BinaryPackageFile

# https://packaging.python.org/en/latest/specifications/core-metadata/#id6
wheel_name_pattern = re.compile(
    r"^([A-Z0-9]|[A-Z0-9][A-Z0-9._-]*[A-Z0-9])$", re.IGNORECASE
)

# There doesn't seem to be a very useful specification for Conda's package
# name syntax:
# https://docs.conda.io/projects/conda-build/en/latest/resources/package-spec.html
# just says 'The lowercase name of the package. May contain the "-"
# character'.  conda_build.metadata.MetaData.name implements a few specific
# checks, but apparently in terms of which characters are forbidden rather
# than which characters are allowed.  For now, constrain this to something
# reasonably conservative and hope that this is OK.
conda_name_pattern = re.compile(r"^[a-z0-9_][a-z0-9.+_-]*$")


def _validate_bpr_name(bpr: IBinaryPackageRelease, bpn: IBinaryPackageName):
    """Validate that a BPR's BinaryPackageName is appropriate for its format.

    The constraints that apply to binary package names vary depending on the
    package format, so we enforce them when creating a
    `BinaryPackageRelease` since at that point we know the format.

    :param bpr: The context `IBinaryPackageRelease`.
    :param bpn: The `IBinaryPackageName` being set.
    """
    if bpr.binpackageformat == BinaryPackageFormat.WHL:
        if not wheel_name_pattern.match(bpn.name):
            raise BinaryPackageReleaseNameLinkageError(
                "Invalid Python wheel name '%s'; must match /%s/i"
                % (bpn.name, wheel_name_pattern.pattern)
            )
    elif bpr.binpackageformat in (
        BinaryPackageFormat.CONDA_V1,
        BinaryPackageFormat.CONDA_V2,
    ):
        if not conda_name_pattern.match(bpn.name):
            raise BinaryPackageReleaseNameLinkageError(
                "Invalid Conda package name '%s'; must match /%s/"
                % (bpn.name, conda_name_pattern.pattern)
            )
    else:
        # Fall back to Launchpad's traditional name validation, which
        # coincides with the rules for Debian-format package names.
        if not debian_name_pattern.match(bpn.name):
            raise BinaryPackageReleaseNameLinkageError(
                "Invalid package name '%s'; must match /%s/"
                % (bpn.name, debian_name_pattern.pattern)
            )


@implementer(IBinaryPackageRelease)
class BinaryPackageRelease(StormBase):
    __storm_table__ = "BinaryPackageRelease"

    id = Int(primary=True)
    binarypackagename_id = Int(name="binarypackagename", allow_none=False)
    binarypackagename = Reference(binarypackagename_id, "BinaryPackageName.id")
    version = Unicode(name="version", allow_none=False)
    summary = Unicode(name="summary", allow_none=False, default="")
    description = Unicode(name="description", allow_none=False)
    # DB constraint: exactly one of build and ci_build is non-NULL.
    build_id = Int(name="build", allow_none=True)
    build = Reference(build_id, "BinaryPackageBuild.id")
    ci_build_id = Int(name="ci_build", allow_none=True)
    ci_build = Reference(ci_build_id, "CIBuild.id")
    binpackageformat = DBEnum(
        name="binpackageformat", allow_none=False, enum=BinaryPackageFormat
    )
    # DB constraint: non-nullable for BinaryPackageFormat.{DEB,UDEB,DDEB}.
    component_id = Int(name="component", allow_none=True)
    component = Reference(component_id, "Component.id")
    # DB constraint: non-nullable for BinaryPackageFormat.{DEB,UDEB,DDEB}.
    section_id = Int(name="section", allow_none=True)
    section = Reference(section_id, "Section.id")
    # DB constraint: non-nullable for BinaryPackageFormat.{DEB,UDEB,DDEB}.
    priority = DBEnum(
        name="priority", allow_none=True, enum=PackagePublishingPriority
    )
    shlibdeps = Unicode(name="shlibdeps")
    depends = Unicode(name="depends")
    recommends = Unicode(name="recommends")
    suggests = Unicode(name="suggests")
    conflicts = Unicode(name="conflicts")
    replaces = Unicode(name="replaces")
    provides = Unicode(name="provides")
    pre_depends = Unicode(name="pre_depends")
    enhances = Unicode(name="enhances")
    breaks = Unicode(name="breaks")
    essential = Bool(name="essential", default=False)
    installedsize = Int(name="installedsize")
    architecturespecific = Bool(name="architecturespecific", allow_none=False)
    homepage = Unicode(name="homepage")
    datecreated = DateTime(
        allow_none=False, default=UTC_NOW, tzinfo=timezone.utc
    )
    debug_package_id = Int(name="debug_package")
    debug_package = Reference(debug_package_id, "BinaryPackageRelease.id")

    _user_defined_fields = Unicode(name="user_defined_fields")

    def __init__(
        self,
        binarypackagename,
        version,
        binpackageformat,
        description,
        architecturespecific,
        summary="",
        build=None,
        ci_build=None,
        component=None,
        section=None,
        priority=None,
        shlibdeps=None,
        depends=None,
        recommends=None,
        suggests=None,
        conflicts=None,
        replaces=None,
        provides=None,
        pre_depends=None,
        enhances=None,
        breaks=None,
        essential=False,
        installedsize=None,
        homepage=None,
        debug_package=None,
        user_defined_fields=None,
    ):
        super().__init__()
        self.binarypackagename = binarypackagename
        self.version = version
        self.binpackageformat = binpackageformat
        self.description = description
        self.architecturespecific = architecturespecific
        self.summary = summary
        self.build = build
        self.ci_build = ci_build
        self.component = component
        self.section = section
        self.priority = priority
        self.shlibdeps = shlibdeps
        self.depends = depends
        self.recommends = recommends
        self.suggests = suggests
        self.conflicts = conflicts
        self.replaces = replaces
        self.provides = provides
        self.pre_depends = pre_depends
        self.enhances = enhances
        self.breaks = breaks
        self.essential = essential
        self.installedsize = installedsize
        self.homepage = homepage
        self.debug_package = debug_package
        if user_defined_fields is not None:
            self._user_defined_fields = json.dumps(user_defined_fields)

        # Validate the package name.  We can't use Storm's validator
        # mechanism for this, because we need to validate the combination of
        # binpackageformat and binarypackagename, and the way validators
        # work for references mean that the validator would have to make a
        # database query while the row is in an incomplete state of
        # construction.
        _validate_bpr_name(self, self.binarypackagename)

    @cachedproperty
    def built_using_references(self):
        reference_set = getUtility(IBinarySourceReferenceSet)
        references = reference_set.findByBinaryPackageRelease(
            self, BinarySourceReferenceType.BUILT_USING
        )
        # Preserving insertion order is good enough.
        return sorted(references, key=attrgetter("id"))

    @property
    def user_defined_fields(self):
        """See `IBinaryPackageRelease`."""
        if self._user_defined_fields is None:
            return []
        user_defined_fields = json.loads(self._user_defined_fields)
        if user_defined_fields is None:
            return []
        return user_defined_fields

    def getUserDefinedField(self, name):
        for k, v in self.user_defined_fields:
            if k.lower() == name.lower():
                return v

    @property
    def title(self):
        """See `IBinaryPackageRelease`."""
        return "%s-%s" % (self.binarypackagename.name, self.version)

    @property
    def name(self):
        """See `IBinaryPackageRelease`."""
        return self.binarypackagename.name

    @property
    def sourcepackagename(self):
        """See `IBinaryPackageRelease`."""
        if self.build is not None:
            return self.build.source_package_release.sourcepackagename.name
        else:
            return None

    @property
    def sourcepackageversion(self):
        """See `IBinaryPackageRelease`."""
        if self.build is not None:
            return self.build.source_package_release.version
        else:
            return None

    @cachedproperty
    def files(self):
        return list(
            Store.of(self).find(BinaryPackageFile, binarypackagerelease=self)
        )

    def addFile(self, file, filetype=None):
        """See `IBinaryPackageRelease`."""
        if filetype is None:
            if file.filename.endswith(".deb"):
                filetype = BinaryPackageFileType.DEB
            elif file.filename.endswith(".rpm"):
                filetype = BinaryPackageFileType.RPM
            elif file.filename.endswith(".udeb"):
                filetype = BinaryPackageFileType.UDEB
            elif file.filename.endswith(".ddeb"):
                filetype = BinaryPackageFileType.DDEB
            elif file.filename.endswith(".whl"):
                filetype = BinaryPackageFileType.WHL
            else:
                raise AssertionError(
                    "Unsupported file type: %s" % file.filename
                )

        del get_property_cache(self).files
        return BinaryPackageFile(
            binarypackagerelease=self, filetype=filetype, libraryfile=file
        )

    def override(self, component=None, section=None, priority=None):
        """See `IBinaryPackageRelease`."""
        if component is not None:
            self.component = component
        if section is not None:
            self.section = section
        if priority is not None:
            self.priority = priority


@implementer(IBinaryPackageReleaseDownloadCount)
class BinaryPackageReleaseDownloadCount(StormBase):
    """See `IBinaryPackageReleaseDownloadCount`."""

    __storm_table__ = "BinaryPackageReleaseDownloadCount"

    id = Int(primary=True)
    archive_id = Int(name="archive", allow_none=False)
    archive = Reference(archive_id, "Archive.id")
    binary_package_release_id = Int(
        name="binary_package_release", allow_none=False
    )
    binary_package_release = Reference(
        binary_package_release_id, "BinaryPackageRelease.id"
    )
    day = Date(allow_none=False)
    country_id = Int(name="country", allow_none=True)
    country = Reference(country_id, "Country.id")
    count = Int(allow_none=False)

    def __init__(self, archive, binary_package_release, day, country, count):
        super().__init__()
        self.archive = archive
        self.binary_package_release = binary_package_release
        self.day = day
        self.country = country
        self.count = count

    @property
    def binary_package_name(self):
        """See `IBinaryPackageReleaseDownloadCount`."""
        return self.binary_package_release.name

    @property
    def binary_package_version(self):
        """See `IBinaryPackageReleaseDownloadCount`."""
        return self.binary_package_release.version

    @property
    def country_code(self):
        """See `IBinaryPackageReleaseDownloadCount`."""
        if self.country is not None:
            return self.country.iso3166code2
        else:
            return "unknown"
