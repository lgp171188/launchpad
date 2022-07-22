# Copyright 2009-2017 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""IHasBuildRecords interface.

Implemented by any object that can have `IPackageBuild` records related to it.
"""

__all__ = [
    "IHasBuildRecords",
]

from lazr.restful.declarations import (
    REQUEST_USER,
    call_with,
    export_read_operation,
    operation_for_version,
    operation_parameters,
    operation_returns_collection_of,
    rename_parameters_as,
)
from zope.interface import Interface
from zope.schema import Choice, TextLine

from lp import _
from lp.buildmaster.enums import BuildStatus
from lp.registry.interfaces.pocket import PackagePublishingPocket


class IHasBuildRecords(Interface):
    """An Object that has build records"""

    @rename_parameters_as(name="source_name")
    @operation_parameters(
        name=TextLine(title=_("Source package name"), required=False),
        build_state=Choice(
            title=_("Build status"),
            required=False,
            description=_("The status of this build record"),
            vocabulary=BuildStatus,
        ),
        pocket=Choice(
            title=_("Pocket"),
            required=False,
            readonly=True,
            description=_("The pocket into which this entry is published"),
            vocabulary=PackagePublishingPocket,
        ),
    )
    @call_with(user=REQUEST_USER, binary_only=True)
    # Really IBinaryPackageBuild, patched in lp.soyuz.interfaces.webservice.
    @operation_returns_collection_of(Interface)
    @export_read_operation()
    @operation_for_version("beta")
    def getBuildRecords(
        build_state=None,
        name=None,
        pocket=None,
        arch_tag=None,
        user=None,
        binary_only=True,
    ):
        """Return build records in the context it is implemented.

        It excludes build records generated by Gina (imported from a external
        repository), where `IBuild.datebuilt` is null and `IBuild.buildstate`
        is `BuildStatus.FULLYBUILT`.

        The result is simply not filtered if the optional filters are omitted
        by call sites.

        :param build_state: optional `BuildStatus` value for filtering build
            records;
        :param name: optional string for filtering build source package name.
            Sub-string matching is allowed via SQL LIKE.
        :param pocket: optional `PackagePublishingPocket` value for filtering
            build records;
        :param arch_tag: optional string for filtering build source packages
            by their architecture tag;
        :param user: optional `IPerson` corresponding to the user performing
            the request. It will filter out build records for which the user
            have no 'view' permission.
        :param binary_only: optional boolean indicating whether only
            `BinaryPackageBuild` objects should be returned, or more general
            `PackageBuild` objects (which may include, for example,
            `SourcePackageRecipeBuild` objects.

        :return: a result set containing `IPackageBuild` records ordered by
            descending `IPackageBuild.date_finished` except when builds are
            filtered by `BuildStatus.NEEDSBUILD`, in this case records
            are ordered by descending `BuildQueue.lastscore`
            (dispatching order).
        """
