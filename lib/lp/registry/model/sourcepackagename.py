# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "SourcePackageName",
    "SourcePackageNameSet",
    "getSourcePackageDescriptions",
]

from storm.properties import Int, Unicode
from zope.interface import implementer

from lp.app.errors import NotFoundError
from lp.app.validators.name import valid_name
from lp.registry.errors import InvalidName, NoSuchSourcePackageName
from lp.registry.interfaces.sourcepackagename import (
    ISourcePackageName,
    ISourcePackageNameSet,
)
from lp.services.database.interfaces import IStore
from lp.services.database.sqlbase import cursor, sqlvalues
from lp.services.database.stormbase import StormBase


@implementer(ISourcePackageName)
class SourcePackageName(StormBase):
    __storm_table__ = "SourcePackageName"

    id = Int(primary=True)
    name = Unicode(name="name", allow_none=False)

    def __init__(self, name):
        super().__init__()
        self.name = name

    def __str__(self):
        return self.name

    def __repr__(self):
        return "<%s '%s'>" % (self.__class__.__name__, self.name)

    @classmethod
    def ensure(klass, name):
        spn = IStore(klass).find(klass, name=name).one()
        if spn is None:
            spn = klass(name=name)
        return spn


@implementer(ISourcePackageNameSet)
class SourcePackageNameSet:
    def __getitem__(self, name):
        """See `ISourcePackageNameSet`."""
        spn = self.queryByName(name)
        if spn is None:
            raise NoSuchSourcePackageName(name)
        return spn

    def get(self, sourcepackagenameid):
        """See `ISourcePackageNameSet`."""
        spn = IStore(SourcePackageName).get(
            SourcePackageName, sourcepackagenameid
        )
        if spn is None:
            raise NotFoundError(sourcepackagenameid)
        return spn

    def getAll(self):
        """See `ISourcePackageNameSet`."""
        return IStore(SourcePackageName).find(SourcePackageName)

    def queryByName(self, name):
        """See `ISourcePackageNameSet`."""
        return (
            IStore(SourcePackageName).find(SourcePackageName, name=name).one()
        )

    def new(self, name):
        if not valid_name(name):
            raise InvalidName(
                "%s is not a valid name for a source package." % name
            )
        spn = SourcePackageName(name=name)
        store = IStore(SourcePackageName)
        store.add(spn)
        store.flush()
        return spn

    def getOrCreateByName(self, name):
        try:
            return self[name]
        except NotFoundError:
            return self.new(name)


def getSourcePackageDescriptions(
    results, use_names=False, max_title_length=50
):
    """Return a dictionary with descriptions keyed on source package names.

    Takes an ISelectResults of a *PackageName query. The use_names
    flag is a hack that allows this method to work for the
    BinaryAndSourcePackageName view, which lacks IDs.

    WARNING: this function assumes that there is little overlap and much
    coherence in how package names are used, in particular across
    distributions if derivation is implemented. IOW, it does not make a
    promise to provide The Correct Description, but a pretty good guess
    at what the description should be.
    """
    # XXX: kiko, 2007-01-17:
    # Use_names could be removed if we instead added IDs to the
    # BinaryAndSourcePackageName view, but we'd still need to find
    # out how to specify the attribute, since it would be
    # sourcepackagename_id and binarypackagename_id depending on
    # whether the row represented one or both of those cases.
    if use_names:
        clause = "SourcePackageName.name in %s" % sqlvalues(
            [pn.name for pn in results]
        )
    else:
        clause = "SourcePackageName.id in %s" % sqlvalues(
            [spn.id for spn in results]
        )

    cur = cursor()
    cur.execute(
        """SELECT DISTINCT BinaryPackageName.name,
                          SourcePackageName.name
                     FROM BinaryPackageRelease, SourcePackageName,
                          BinaryPackageBuild, BinaryPackageName
                    WHERE
                       BinaryPackageName.id =
                           BinaryPackageRelease.binarypackagename AND
                       BinaryPackageRelease.build = BinaryPackageBuild.id AND
                       BinaryPackageBuild.source_package_name =
                           SourcePackageName.id AND
                       %s
                   ORDER BY BinaryPackageName.name,
                            SourcePackageName.name"""
        % clause
    )

    descriptions = {}
    for binarypackagename, sourcepackagename in cur.fetchall():
        if sourcepackagename not in descriptions:
            descriptions[sourcepackagename] = (
                "Source of: %s" % binarypackagename
            )
        else:
            if len(descriptions[sourcepackagename]) > max_title_length:
                description = "..."
            else:
                description = ", %s" % binarypackagename
            descriptions[sourcepackagename] += description
    return descriptions
