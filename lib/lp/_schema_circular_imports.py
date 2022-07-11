# Copyright 2009-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Update the interface schema values due to circular imports.

There are situations where there would normally be circular imports to define
the necessary schema values in some interface fields.  To avoid this the
schema is initially set to `Interface`, but this needs to be updated once the
types are defined.
"""

__all__ = []


from lazr.restful.fields import Reference

from lp.bugs.interfaces.bugtask import IBugTask
from lp.bugs.interfaces.vulnerability import IVulnerability
from lp.buildmaster.interfaces.builder import IBuilder
from lp.buildmaster.interfaces.buildfarmjob import IBuildFarmJob
from lp.buildmaster.interfaces.buildqueue import IBuildQueue
from lp.code.interfaces.branch import IBranch
from lp.code.interfaces.cibuild import ICIBuild
from lp.code.interfaces.gitrepository import IGitRepository
from lp.code.interfaces.sourcepackagerecipe import ISourcePackageRecipe
from lp.code.interfaces.sourcepackagerecipebuild import (
    ISourcePackageRecipeBuild,
    )
from lp.registry.interfaces.commercialsubscription import (
    ICommercialSubscription,
    )
from lp.registry.interfaces.distribution import IDistribution
from lp.registry.interfaces.distributionmirror import IDistributionMirror
from lp.registry.interfaces.distributionsourcepackage import (
    IDistributionSourcePackage,
    )
from lp.registry.interfaces.distroseries import IDistroSeries
from lp.registry.interfaces.distroseriesdifference import (
    IDistroSeriesDifference,
    )
from lp.registry.interfaces.distroseriesdifferencecomment import (
    IDistroSeriesDifferenceComment,
    )
from lp.registry.interfaces.ociproject import IOCIProject
from lp.registry.interfaces.person import (
    IPerson,
    IPersonEditRestricted,
    IPersonLimitedView,
    IPersonViewRestricted,
    )
from lp.registry.interfaces.product import IProduct
from lp.registry.interfaces.productseries import IProductSeries
from lp.registry.interfaces.sourcepackage import (
    ISourcePackage,
    ISourcePackageEdit,
    ISourcePackagePublic,
    )
from lp.services.auth.interfaces import IAccessToken
from lp.services.comments.interfaces.conversation import IComment
from lp.services.messages.interfaces.message import (
    IIndexedMessage,
    IMessage,
    IUserToUserEmail,
    )
from lp.services.messages.interfaces.messagerevision import IMessageRevision
from lp.services.webservice.apihelpers import (
    patch_collection_property,
    patch_collection_return_type,
    patch_entry_return_type,
    patch_list_parameter_type,
    patch_plain_parameter_type,
    patch_reference_property,
    )
from lp.snappy.interfaces.snapbase import ISnapBase
from lp.soyuz.interfaces.archive import IArchive
from lp.soyuz.interfaces.archivedependency import IArchiveDependency
from lp.soyuz.interfaces.archivepermission import IArchivePermission
from lp.soyuz.interfaces.archivesubscriber import IArchiveSubscriber
from lp.soyuz.interfaces.binarypackagebuild import IBinaryPackageBuild
from lp.soyuz.interfaces.buildrecords import IHasBuildRecords
from lp.soyuz.interfaces.distroarchseries import IDistroArchSeries
from lp.soyuz.interfaces.distroarchseriesfilter import IDistroArchSeriesFilter
from lp.soyuz.interfaces.livefs import ILiveFSView
from lp.soyuz.interfaces.livefsbuild import (
    ILiveFSBuild,
    ILiveFSFile,
    )
from lp.soyuz.interfaces.packageset import IPackageset
from lp.soyuz.interfaces.publishing import (
    IBinaryPackagePublishingHistory,
    IBinaryPackagePublishingHistoryEdit,
    ISourcePackagePublishingHistory,
    ISourcePackagePublishingHistoryEdit,
    ISourcePackagePublishingHistoryPublic,
    )
from lp.soyuz.interfaces.queue import IPackageUpload
from lp.soyuz.interfaces.sourcepackagerelease import ISourcePackageRelease


# IBuilder
patch_reference_property(IBuilder, 'current_build', IBuildFarmJob)

patch_reference_property(IPersonViewRestricted, 'archive', IArchive)
patch_collection_property(IPersonViewRestricted, 'ppas', IArchive)
patch_plain_parameter_type(
    IPersonLimitedView, 'getPPAByName', 'distribution', IDistribution)
patch_entry_return_type(IPersonLimitedView, 'getPPAByName', IArchive)
patch_plain_parameter_type(
    IPersonEditRestricted, 'createPPA', 'distribution', IDistribution)
patch_entry_return_type(IPersonEditRestricted, 'createPPA', IArchive)

patch_collection_return_type(
    IHasBuildRecords, 'getBuildRecords', IBinaryPackageBuild)

patch_reference_property(ISourcePackagePublic, 'distroseries', IDistroSeries)
patch_reference_property(ISourcePackagePublic, 'productseries', IProductSeries)
patch_entry_return_type(ISourcePackagePublic, 'getBranch', IBranch)
patch_plain_parameter_type(ISourcePackageEdit, 'setBranch', 'branch', IBranch)
patch_reference_property(ISourcePackage, 'distribution', IDistribution)

# IPerson
patch_entry_return_type(IPerson, 'createRecipe', ISourcePackageRecipe)
patch_list_parameter_type(IPerson, 'createRecipe', 'distroseries',
                          Reference(schema=IDistroSeries))
patch_plain_parameter_type(IPerson, 'createRecipe', 'daily_build_archive',
                           IArchive)
patch_plain_parameter_type(IPerson, 'getArchiveSubscriptionURL', 'archive',
                           IArchive)
patch_collection_return_type(
    IPerson, 'getArchiveSubscriptions', IArchiveSubscriber)
patch_entry_return_type(IPerson, 'getRecipe', ISourcePackageRecipe)
patch_collection_return_type(IPerson, 'getOwnedProjects', IProduct)

# publishing.py
patch_collection_return_type(
    ISourcePackagePublishingHistoryPublic, 'getBuilds', IBinaryPackageBuild)
patch_collection_return_type(
    ISourcePackagePublishingHistoryPublic, 'getPublishedBinaries',
    IBinaryPackagePublishingHistory)
patch_reference_property(
    IBinaryPackagePublishingHistory, 'distroarchseries',
    IDistroArchSeries)
patch_reference_property(
    IBinaryPackagePublishingHistory, 'build', IBinaryPackageBuild)
patch_reference_property(
    IBinaryPackagePublishingHistory, 'archive', IArchive)
patch_reference_property(
    ISourcePackagePublishingHistory, 'archive', IArchive)
patch_reference_property(
    IBinaryPackagePublishingHistory, 'copied_from_archive', IArchive)
patch_reference_property(
    ISourcePackagePublishingHistory, 'copied_from_archive', IArchive)
patch_reference_property(
    ISourcePackagePublishingHistory, 'ancestor',
    ISourcePackagePublishingHistory)
patch_reference_property(
    ISourcePackagePublishingHistory, 'packageupload', IPackageUpload)
patch_entry_return_type(
    ISourcePackagePublishingHistoryEdit, 'changeOverride',
    ISourcePackagePublishingHistory)
patch_entry_return_type(
    IBinaryPackagePublishingHistoryEdit, 'changeOverride',
    IBinaryPackagePublishingHistory)

# IArchive apocalypse.
patch_reference_property(IArchive, 'distribution', IDistribution)
patch_collection_property(IArchive, 'dependencies', IArchiveDependency)
patch_collection_return_type(IArchive, 'getAllPermissions', IArchivePermission)
patch_collection_return_type(
    IArchive, 'getPermissionsForPerson', IArchivePermission)
patch_collection_return_type(
    IArchive, 'getUploadersForPackage', IArchivePermission)
patch_collection_return_type(
    IArchive, 'getUploadersForPackageset', IArchivePermission)
patch_collection_return_type(
    IArchive, 'getPackagesetsForUploader', IArchivePermission)
patch_collection_return_type(
    IArchive, 'getPackagesetsForSourceUploader', IArchivePermission)
patch_collection_return_type(
    IArchive, 'getPackagesetsForSource', IArchivePermission)
patch_collection_return_type(
    IArchive, 'getUploadersForComponent', IArchivePermission)
patch_collection_return_type(
    IArchive, 'getQueueAdminsForComponent', IArchivePermission)
patch_collection_return_type(
    IArchive, 'getComponentsForQueueAdmin', IArchivePermission)
patch_collection_return_type(
    IArchive, 'getQueueAdminsForPocket', IArchivePermission)
patch_collection_return_type(
    IArchive, 'getPocketsForQueueAdmin', IArchivePermission)
patch_collection_return_type(
    IArchive, 'getPocketsForUploader', IArchivePermission)
patch_collection_return_type(
    IArchive, 'getUploadersForPocket', IArchivePermission)
patch_entry_return_type(IArchive, 'newPackageUploader', IArchivePermission)
patch_entry_return_type(IArchive, 'newPackagesetUploader', IArchivePermission)
patch_entry_return_type(IArchive, 'newComponentUploader', IArchivePermission)
patch_entry_return_type(IArchive, 'newPocketUploader', IArchivePermission)
patch_entry_return_type(IArchive, 'newQueueAdmin', IArchivePermission)
patch_entry_return_type(IArchive, 'newPocketQueueAdmin', IArchivePermission)
patch_plain_parameter_type(IArchive, 'syncSources', 'from_archive', IArchive)
patch_plain_parameter_type(IArchive, 'syncSource', 'from_archive', IArchive)
patch_plain_parameter_type(IArchive, 'copyPackage', 'from_archive', IArchive)
patch_plain_parameter_type(
    IArchive, 'copyPackages', 'from_archive', IArchive)
patch_plain_parameter_type(IArchive, 'uploadCIBuild', 'ci_build', ICIBuild)
patch_entry_return_type(IArchive, 'newSubscription', IArchiveSubscriber)
patch_plain_parameter_type(
    IArchive, 'getArchiveDependency', 'dependency', IArchive)
patch_entry_return_type(IArchive, 'getArchiveDependency', IArchiveDependency)
patch_collection_return_type(
    IArchive, 'api_getPublishedSources', ISourcePackagePublishingHistory)
patch_plain_parameter_type(
    IArchive, 'getAllPublishedBinaries', 'distroarchseries',
    IDistroArchSeries)
patch_collection_return_type(
    IArchive, 'getAllPublishedBinaries', IBinaryPackagePublishingHistory)
patch_plain_parameter_type(
    IArchive, 'newPackagesetUploader', 'packageset', IPackageset)
patch_plain_parameter_type(
    IArchive, 'getUploadersForPackageset', 'packageset', IPackageset)
patch_plain_parameter_type(
    IArchive, 'deletePackagesetUploader', 'packageset', IPackageset)
patch_plain_parameter_type(
    IArchive, 'removeArchiveDependency', 'dependency', IArchive)
patch_plain_parameter_type(
    IArchive, '_addArchiveDependency', 'dependency', IArchive)
patch_entry_return_type(
    IArchive, '_addArchiveDependency', IArchiveDependency)

# IArchiveDependency
patch_reference_property(IArchiveDependency, 'snap_base', ISnapBase)

# IBuildFarmJob
patch_reference_property(IBuildFarmJob, 'buildqueue_record', IBuildQueue)

# IComment
patch_reference_property(IComment, 'comment_author', IPerson)

# ICommercialSubscription
patch_reference_property(ICommercialSubscription, 'product', IProduct)
patch_reference_property(
    ICommercialSubscription, 'distribution', IDistribution)

# IDistribution
patch_collection_property(IDistribution, 'series', IDistroSeries)
patch_collection_property(IDistribution, 'derivatives', IDistroSeries)
patch_reference_property(IDistribution, 'currentseries', IDistroSeries)
patch_entry_return_type(IDistribution, 'getArchive', IArchive)
patch_entry_return_type(IDistribution, 'getSeries', IDistroSeries)
patch_collection_return_type(
    IDistribution, 'getDevelopmentSeries', IDistroSeries)
patch_entry_return_type(
    IDistribution, 'getSourcePackage', IDistributionSourcePackage)
patch_entry_return_type(IDistribution, 'getOCIProject', IOCIProject)
patch_collection_return_type(
    IDistribution, 'searchSourcePackages', IDistributionSourcePackage)
patch_reference_property(IDistribution, 'main_archive', IArchive)
patch_collection_property(IDistribution, 'all_distro_archives', IArchive)
patch_entry_return_type(IDistribution, 'newOCIProject', IOCIProject)
patch_collection_return_type(
    IDistribution, 'searchOCIProjects', IOCIProject)
patch_collection_property(IDistribution, 'vulnerabilities', IVulnerability)


# IDistributionMirror
patch_reference_property(IDistributionMirror, 'distribution', IDistribution)


# IDistroSeries
patch_entry_return_type(
    IDistroSeries, 'getDistroArchSeries', IDistroArchSeries)
patch_reference_property(IDistroSeries, 'main_archive', IArchive)
patch_collection_property(
    IDistroSeries, 'enabled_architectures', IDistroArchSeries)
patch_reference_property(IDistroSeries, 'distribution', IDistribution)
patch_plain_parameter_type(
    IDistroSeries, 'getPackageUploads', 'archive', IArchive)
patch_collection_return_type(
    IDistroSeries, 'getPackageUploads', IPackageUpload)
patch_reference_property(IDistroSeries, 'previous_series', IDistroSeries)
patch_reference_property(
    IDistroSeries, 'nominatedarchindep', IDistroArchSeries)
patch_collection_return_type(IDistroSeries, 'getDerivedSeries', IDistroSeries)
patch_collection_return_type(IDistroSeries, 'getParentSeries', IDistroSeries)
patch_plain_parameter_type(
    IDistroSeries, 'getDifferencesTo', 'parent_series', IDistroSeries)
patch_collection_return_type(
    IDistroSeries, 'getDifferencesTo', IDistroSeriesDifference)
patch_collection_return_type(
    IDistroSeries, 'getDifferenceComments', IDistroSeriesDifferenceComment)


# IDistroSeriesDifference
patch_reference_property(
    IDistroSeriesDifference, 'latest_comment', IDistroSeriesDifferenceComment)

# IDistroSeriesDifferenceComment
patch_reference_property(
    IDistroSeriesDifferenceComment, 'comment_author', IPerson)

# IDistroArchSeries
patch_reference_property(IDistroArchSeries, 'main_archive', IArchive)
patch_plain_parameter_type(
    IDistroArchSeries, 'setChrootFromBuild', 'livefsbuild', ILiveFSBuild)
patch_entry_return_type(
    IDistroArchSeries, 'getSourceFilter', IDistroArchSeriesFilter)
patch_plain_parameter_type(
    IDistroArchSeries, 'setSourceFilter', 'packageset', IPackageset)

# ILiveFSFile
patch_reference_property(ILiveFSFile, 'livefsbuild', ILiveFSBuild)

# ILiveFSView
patch_entry_return_type(ILiveFSView, 'requestBuild', ILiveFSBuild)
patch_collection_property(ILiveFSView, 'builds', ILiveFSBuild)
patch_collection_property(ILiveFSView, 'completed_builds', ILiveFSBuild)
patch_collection_property(ILiveFSView, 'pending_builds', ILiveFSBuild)

# IPackageset
patch_collection_return_type(IPackageset, 'setsIncluded', IPackageset)
patch_collection_return_type(IPackageset, 'setsIncludedBy', IPackageset)
patch_plain_parameter_type(
    IPackageset, 'getSourcesSharedBy', 'other_package_set', IPackageset)
patch_plain_parameter_type(
    IPackageset, 'getSourcesNotSharedBy', 'other_package_set', IPackageset)
patch_collection_return_type(IPackageset, 'relatedSets', IPackageset)

# IPackageUpload
patch_reference_property(IPackageUpload, 'distroseries', IDistroSeries)
patch_reference_property(IPackageUpload, 'archive', IArchive)
patch_reference_property(IPackageUpload, 'copy_source_archive', IArchive)

# ISourcePackageRelease
patch_reference_property(
    ISourcePackageRelease, 'source_package_recipe_build',
    ISourcePackageRecipeBuild)

# IIndexedMessage
patch_reference_property(IIndexedMessage, 'inside', IBugTask)

# IMessage
patch_reference_property(IMessage, 'owner', IPerson)
patch_collection_property(IMessage, 'revisions', IMessageRevision)

# IUserToUserEmail
patch_reference_property(IUserToUserEmail, 'sender', IPerson)
patch_reference_property(IUserToUserEmail, 'recipient', IPerson)

# IPerson
patch_collection_return_type(
    IPerson, 'getBugSubscriberPackages', IDistributionSourcePackage)

# IProductSeries
patch_reference_property(IProductSeries, 'product', IProduct)

# IAccessToken
patch_reference_property(IAccessToken, 'git_repository', IGitRepository)
