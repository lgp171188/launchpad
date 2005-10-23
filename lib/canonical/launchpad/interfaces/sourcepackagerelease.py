# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

"""Source package release interfaces."""

__metaclass__ = type

__all__ = [
    'ISourcePackageRelease',
    'ISourcePackageReleaseSet',
    ]

from zope.schema import TextLine
from zope.interface import Interface, Attribute

from canonical.launchpad import _
from canonical.launchpad.validators.version import valid_debian_version

from canonical.lp.dbschema import BuildStatus

class ISourcePackageRelease(Interface):
    """A source package release, e.g. apache-utils 2.0.48-3"""

    id = Attribute("SourcePackageRelease identifier")
    creator = Attribute("Person that created this release")
    maintainer = Attribute("The person in general responsible for this "
        "release")
    version = Attribute("A version string")
    dateuploaded = Attribute("Date of Upload")
    urgency = Attribute("Source Package Urgency")
    dscsigningkey = Attribute("DSC Signing Key")
    component = Attribute("Source Package Component")
    format = Attribute("The Source Package Format")
    changelog = Attribute("Source Package Change Log")
    builddepends = Attribute(
        "A comma-separated list of packages on which this package "
        "depends to build")
    builddependsindep = Attribute(
        "Same as builddepends, but the list is of arch-independent packages")
    architecturehintlist = Attribute("XXX: Kinnison?")
    dsc = Attribute("The DSC file for this SourcePackageRelease")
    section = Attribute("Section this Source package Release belongs to")
    binaries = Attribute(
        "Binary Packages generated by this SourcePackageRelease")
    builds = Attribute("Builds for this sourcepackagerelease")
    files = Attribute("IBinaryPackageFile entries for this "
        "sourcepackagerelease")
    sourcepackagename = Attribute("SourcePackageName table reference")
    uploaddistrorelease = Attribute("The distrorelease in which this package "
        "was first uploaded in Launchpad")
    manifest = Attribute("Manifest of branches imported for this release")

    # read-only properties
    name = Attribute('The sourcepackagename for this release, as text')
    title = Attribute('The title of this sourcepackagerelease')
    latest_build = Attribute("The latest build of this source package "
        "release, or None")

    productrelease = Attribute("The best guess we have as to the Launchpad "
        "ProductRelease associated with this SourcePackageRelease.")

    current_publishings = Attribute("A list of the current places where "
        "this source package is published, in the form of a list of "
        "DistroReleaseSourcePackageReleases.")

    def branches():
        """Return the list of branches in a source package release"""

    # XXX: What do the following methods and attributes do?
    #      These were missing from the interfaces, but being used
    #      in application code.
    #      -- Steve Alexander, Fri Dec 10 14:28:41 UTC 2004
    architecturesReleased = Attribute("XXX")

    def addFile(file):
        """Add the provided library file alias (file) to the list of files
        in this package.
        """

    def createBuild(distroarchrelease, processor=None,
                    status=BuildStatus.NEEDSBUILD):
        """Create a build for the given distroarchrelease and return it.

        If the processor isn't given, guess it from the distroarchrelease.
        If the status isn't given, use NEEDSBUILD.
        """


class ISourcePackageReleaseSet(Interface):

    def getByCreatorID(creatorID):
        """Return an iterator over SourcePackageReleases created by this
        person."""


