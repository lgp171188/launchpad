# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    'BinaryPackageRelease',
    'BinaryPackageReleaseDownloadCount',
    ]

from operator import attrgetter
import re

import simplejson
from storm.locals import (
    Date,
    Int,
    Reference,
    Store,
    Storm,
    )
from zope.component import getUtility
from zope.interface import implementer

from lp.app.validators.name import valid_name_pattern as debian_name_pattern
from lp.services.database.constants import UTC_NOW
from lp.services.database.datetimecol import UtcDateTimeCol
from lp.services.database.enumcol import DBEnum
from lp.services.database.interfaces import IStore
from lp.services.database.sqlbase import SQLBase
from lp.services.database.sqlobject import (
    BoolCol,
    ForeignKey,
    IntCol,
    StringCol,
    )
from lp.services.propertycache import (
    cachedproperty,
    get_property_cache,
    )
from lp.soyuz.enums import (
    BinaryPackageFileType,
    BinaryPackageFormat,
    BinarySourceReferenceType,
    PackagePublishingPriority,
    )
from lp.soyuz.interfaces.binarypackagerelease import (
    BinaryPackageReleaseNameLinkageError,
    IBinaryPackageRelease,
    IBinaryPackageReleaseDownloadCount,
    )
from lp.soyuz.interfaces.binarysourcereference import (
    IBinarySourceReferenceSet,
    )
from lp.soyuz.model.binarypackagename import BinaryPackageName
from lp.soyuz.model.files import BinaryPackageFile


# https://packaging.python.org/en/latest/specifications/core-metadata/#id6
wheel_name_pattern = re.compile(
    r"^([A-Z0-9]|[A-Z0-9][A-Z0-9._-]*[A-Z0-9])$", re.IGNORECASE)

# There doesn't seem to be a very useful specification for Conda's package
# name syntax:
# https://docs.conda.io/projects/conda-build/en/latest/resources/package-spec.html
# just says 'The lowercase name of the package. May contain the "-"
# character'.  conda_build.metadata.MetaData.name implements a few specific
# checks, but apparently in terms of which characters are forbidden rather
# than which characters are allowed.  For now, constrain this to something
# reasonably conservative and hope that this is OK.
conda_name_pattern = re.compile(r"^[a-z0-9][a-z0-9.+_-]*$")


def _validate_bpr_name(obj, attr, value):
    # Validate that a BinaryPackageRelease's BinaryPackageName is
    # appropriate for its format.
    if not isinstance(value, int):
        raise AssertionError(
            "Expected int for BinaryPackageName foreign key reference, got %r"
            % type(value))

    name = IStore(BinaryPackageName).get(BinaryPackageName, value).name
    if obj.binpackageformat == BinaryPackageFormat.WHL:
        if not wheel_name_pattern.match(name):
            raise BinaryPackageReleaseNameLinkageError(
                "Invalid Python wheel name '%s'; must match /%s/i"
                % (name, wheel_name_pattern.pattern))
    elif obj.binpackageformat in (
        BinaryPackageFormat.CONDA_V1,
        BinaryPackageFormat.CONDA_V2,
    ):
        if not conda_name_pattern.match(name):
            raise BinaryPackageReleaseNameLinkageError(
                "Invalid Conda name '%s'; must match /%s/"
                % (name, conda_name_pattern.pattern))
    else:
        # Fall back to Launchpad's traditional name validation, which
        # coincides with the rules for Debian-format package names.
        if not debian_name_pattern.match(name):
            raise BinaryPackageReleaseNameLinkageError(
                "Invalid package name '%s'; must match /%s/"
                % (name, debian_name_pattern.pattern))


@implementer(IBinaryPackageRelease)
class BinaryPackageRelease(SQLBase):
    _table = 'BinaryPackageRelease'
    binarypackagename = ForeignKey(dbName='binarypackagename', notNull=True,
                                   foreignKey='BinaryPackageName')
    version = StringCol(dbName='version', notNull=True)
    summary = StringCol(dbName='summary', notNull=True, default="")
    description = StringCol(dbName='description', notNull=True)
    # DB constraint: exactly one of build and ci_build is non-NULL.
    build = ForeignKey(
        dbName='build', foreignKey='BinaryPackageBuild', notNull=False)
    ci_build_id = Int(name='ci_build', allow_none=True)
    ci_build = Reference(ci_build_id, 'CIBuild.id')
    binpackageformat = DBEnum(name='binpackageformat', allow_none=False,
                              enum=BinaryPackageFormat)
    # DB constraint: non-nullable for BinaryPackageFormat.{DEB,UDEB,DDEB}.
    component = ForeignKey(dbName='component', foreignKey='Component',
                           notNull=False)
    # DB constraint: non-nullable for BinaryPackageFormat.{DEB,UDEB,DDEB}.
    section = ForeignKey(dbName='section', foreignKey='Section', notNull=False)
    # DB constraint: non-nullable for BinaryPackageFormat.{DEB,UDEB,DDEB}.
    priority = DBEnum(name='priority', allow_none=True,
                      enum=PackagePublishingPriority)
    shlibdeps = StringCol(dbName='shlibdeps')
    depends = StringCol(dbName='depends')
    recommends = StringCol(dbName='recommends')
    suggests = StringCol(dbName='suggests')
    conflicts = StringCol(dbName='conflicts')
    replaces = StringCol(dbName='replaces')
    provides = StringCol(dbName='provides')
    pre_depends = StringCol(dbName='pre_depends')
    enhances = StringCol(dbName='enhances')
    breaks = StringCol(dbName='breaks')
    essential = BoolCol(dbName='essential', default=False)
    installedsize = IntCol(dbName='installedsize')
    architecturespecific = BoolCol(dbName='architecturespecific',
                                   notNull=True)
    homepage = StringCol(dbName='homepage')
    datecreated = UtcDateTimeCol(notNull=True, default=UTC_NOW)
    debug_package = ForeignKey(dbName='debug_package',
                              foreignKey='BinaryPackageRelease')

    _user_defined_fields = StringCol(dbName='user_defined_fields')

    def __init__(self, *args, **kwargs):
        if 'user_defined_fields' in kwargs:
            kwargs['_user_defined_fields'] = simplejson.dumps(
                kwargs['user_defined_fields'])
            del kwargs['user_defined_fields']
        super().__init__(*args, **kwargs)
        # XXX cjwatson 2022-06-21: Ideally we'd set this up as a Storm
        # validator, but that's difficult to arrange with SQLBase since we
        # can't guarantee that self.binpackageformat will be set before
        # self.binarypackagename, so just call it by hand here using the
        # calling convention for validators.
        _validate_bpr_name(
            self, "binarypackagename", self.binarypackagename.id)

    @cachedproperty
    def built_using_references(self):
        reference_set = getUtility(IBinarySourceReferenceSet)
        references = reference_set.findByBinaryPackageRelease(
            self, BinarySourceReferenceType.BUILT_USING)
        # Preserving insertion order is good enough.
        return sorted(references, key=attrgetter('id'))

    @property
    def user_defined_fields(self):
        """See `IBinaryPackageRelease`."""
        if self._user_defined_fields is None:
            return []
        return simplejson.loads(self._user_defined_fields)

    @property
    def title(self):
        """See `IBinaryPackageRelease`."""
        return '%s-%s' % (self.binarypackagename.name, self.version)

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
            Store.of(self).find(BinaryPackageFile, binarypackagerelease=self))

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
                    'Unsupported file type: %s' % file.filename)

        del get_property_cache(self).files
        return BinaryPackageFile(binarypackagerelease=self,
                                 filetype=filetype,
                                 libraryfile=file)

    def override(self, component=None, section=None, priority=None):
        """See `IBinaryPackageRelease`."""
        if component is not None:
            self.component = component
        if section is not None:
            self.section = section
        if priority is not None:
            self.priority = priority


@implementer(IBinaryPackageReleaseDownloadCount)
class BinaryPackageReleaseDownloadCount(Storm):
    """See `IBinaryPackageReleaseDownloadCount`."""

    __storm_table__ = 'BinaryPackageReleaseDownloadCount'

    id = Int(primary=True)
    archive_id = Int(name='archive', allow_none=False)
    archive = Reference(archive_id, 'Archive.id')
    binary_package_release_id = Int(
        name='binary_package_release', allow_none=False)
    binary_package_release = Reference(
        binary_package_release_id, 'BinaryPackageRelease.id')
    day = Date(allow_none=False)
    country_id = Int(name='country', allow_none=True)
    country = Reference(country_id, 'Country.id')
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
