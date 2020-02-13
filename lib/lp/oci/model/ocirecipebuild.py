# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""A build record for OCI Recipes."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    'OCIFile',
    'OCIRecipeBuild',
    'OCIRecipeBuildSet',
    ]

from datetime import timedelta

import pytz
from storm.locals import (
    Bool,
    DateTime,
    Desc,
    Int,
    Reference,
    Store,
    Storm,
    Unicode,
    )
from storm.store import EmptyResultSet
from zope.component import getUtility
from zope.interface import implementer

from lp.app.errors import NotFoundError
from lp.buildmaster.enums import (
    BuildFarmJobType,
    BuildStatus,
    )
from lp.buildmaster.interfaces.buildfarmjob import IBuildFarmJobSource
from lp.buildmaster.model.buildfarmjob import SpecificBuildFarmJobSourceMixin
from lp.buildmaster.model.packagebuild import PackageBuildMixin
from lp.oci.interfaces.ocirecipe import IOCIRecipeSet
from lp.oci.interfaces.ocirecipebuild import (
    IOCIFile,
    IOCIRecipeBuild,
    IOCIRecipeBuildSet,
    )
from lp.registry.model.person import Person
from lp.services.database.bulk import load_related
from lp.services.database.constants import DEFAULT
from lp.services.database.decoratedresultset import DecoratedResultSet
from lp.services.database.enumcol import DBEnum
from lp.services.database.interfaces import (
    IMasterStore,
    IStore,
    )
from lp.services.librarian.model import (
    LibraryFileAlias,
    LibraryFileContent,
    )


@implementer(IOCIFile)
class OCIFile(Storm):

    __storm_table__ = 'OCIFile'

    id = Int(name='id', primary=True)

    build_id = Int(name='build', allow_none=False)
    build = Reference(build_id, 'OCIRecipeBuild.id')

    library_file_id = Int(name='library_file', allow_none=False)
    library_file = Reference(library_file_id, 'LibraryFileAlias.id')

    layer_file_digest = Unicode(name='layer_file_digest', allow_none=True)

    def __init__(self, build, library_file, layer_file_digest=None):
        """Construct a `OCIFile`."""
        super(OCIFile, self).__init__()
        self.build = build
        self.library_file = library_file
        self.layer_file_digest = layer_file_digest


@implementer(IOCIRecipeBuild)
class OCIRecipeBuild(PackageBuildMixin, Storm):

    __storm_table__ = 'OCIRecipeBuild'

    job_type = BuildFarmJobType.OCIRECIPEBUILD

    id = Int(name='id', primary=True)

    requester_id = Int(name='requester', allow_none=False)
    requester = Reference(requester_id, 'Person.id')

    recipe_id = Int(name='recipe', allow_none=False)
    recipe = Reference(recipe_id, 'OCIRecipe.id')

    processor_id = Int(name='processor', allow_none=False)
    processor = Reference(processor_id, 'Processor.id')

    virtualized = Bool(name='virtualized')

    date_created = DateTime(
        name='date_created', tzinfo=pytz.UTC, allow_none=False)
    date_started = DateTime(name='date_started', tzinfo=pytz.UTC)
    date_finished = DateTime(name='date_finished', tzinfo=pytz.UTC)
    date_first_dispatched = DateTime(
        name='date_first_dispatched', tzinfo=pytz.UTC)

    builder_id = Int(name='builder')
    builder = Reference(builder_id, 'Builder.id')

    status = DBEnum(name='status', enum=BuildStatus, allow_none=False)

    log_id = Int(name='log')
    log = Reference(log_id, 'LibraryFileAlias.id')

    upload_log_id = Int(name='upload_log')
    upload_log = Reference(upload_log_id, 'LibraryFileAlias.id')

    dependencies = Unicode(name='dependencies')

    failure_count = Int(name='failure_count', allow_none=False)

    build_farm_job_id = Int(name='build_farm_job', allow_none=False)
    build_farm_job = Reference(build_farm_job_id, 'BuildFarmJob.id')

    # Stub attributes to match the IPackageBuild interface that we
    # are not using in this implementation at this time.
    pocket = None
    distro_series = None

    def __init__(self, build_farm_job, requester, recipe,
                 processor, virtualized, date_created):

        self.requester = requester
        self.recipe = recipe
        self.processor = processor
        self.virtualized = virtualized
        self.date_created = date_created
        self.status = BuildStatus.NEEDSBUILD
        self.build_farm_job = build_farm_job

    def calculateScore(self):
        # XXX twom 2020-02-11 - This might need an addition?
        return 2510

    def estimateDuration(self):
        """See `IBuildFarmJob`."""
        median = self.getMedianBuildDuration()
        if median is not None:
            return median
        return timedelta(minutes=30)

    def getMedianBuildDuration(self):
        """Return the median duration of our successful builds."""
        store = IStore(self)
        result = store.find(
            (OCIRecipeBuild.date_started, OCIRecipeBuild.date_finished),
            OCIRecipeBuild.recipe == self.recipe_id,
            OCIRecipeBuild.processor == self.processor_id,
            OCIRecipeBuild.status == BuildStatus.FULLYBUILT)
        result.order_by(Desc(OCIRecipeBuild.date_finished))
        durations = [row[1] - row[0] for row in result[:9]]
        if len(durations) == 0:
            return None
        durations.sort()
        return durations[len(durations) // 2]

    def getByFileName(self, filename):
        result = Store.of(self).find(
            (OCIFile, LibraryFileAlias, LibraryFileContent),
            OCIFile.build == self.id,
            LibraryFileAlias.id == OCIFile.libraryfile_id,
            LibraryFileContent.id == LibraryFileAlias.contentID,
            LibraryFileAlias.filename == filename)
        return result.one()

    def getLayerFileByDigest(self, layer_file_digest):
        file_object = Store.of(self).find(
            (OCIFile, LibraryFileAlias, LibraryFileContent),
            OCIFile.build == self.id,
            LibraryFileAlias.id == OCIFile.libraryfile_id,
            LibraryFileContent.id == LibraryFileAlias.contentID,
            OCIFile.layer_file_digest == layer_file_digest).one()
        if file_object is not None:
            return file_object
        raise NotFoundError(layer_file_digest)

    def addFile(self, lfa, layer_file_digest=None):
        oci_file = OCIFile(
            build=self, library_file=lfa, layer_file_digest=layer_file_digest)
        IMasterStore(OCIFile).add(oci_file)
        return oci_file

    @property
    def archive(self):
        # XXX twom 2019-12-05 This may need to change when an OCIProject
        # pillar isn't just a distribution
        return self.recipe.oci_project.distribution.main_archive

    @property
    def distribution(self):
        # XXX twom 2019-12-05 This may need to change when an OCIProject
        # pillar isn't just a distribution
        return self.recipe.oci_project.distribution


@implementer(IOCIRecipeBuildSet)
class OCIRecipeBuildSet(SpecificBuildFarmJobSourceMixin):
    """See `IOCIRecipeBuildSet`."""

    def new(self, requester, recipe, distro_arch_series,
            date_created=DEFAULT):
        """See `IOCIRecipeBuildSet`."""

        virtualized = (
            not distro_arch_series.processor.supports_nonvirtualized
            or recipe.require_virtualized)

        store = IMasterStore(OCIRecipeBuild)
        build_farm_job = getUtility(IBuildFarmJobSource).new(
            OCIRecipeBuild.job_type, BuildStatus.NEEDSBUILD, date_created)
        ocirecipebuild = OCIRecipeBuild(
            build_farm_job, requester, recipe, distro_arch_series.processor,
            virtualized, date_created)
        store.add(ocirecipebuild)
        return ocirecipebuild

    def preloadBuildsData(self, builds):
        """See `IOCIRecipeBuildSet`."""
        # Circular import.
        from lp.oci.model.ocirecipe import OCIRecipe
        load_related(Person, builds, ["requester_id"])
        lfas = load_related(LibraryFileAlias, builds, ["log_id"])
        load_related(LibraryFileContent, lfas, ["contentID"])
        recipes = load_related(OCIRecipe, builds, ["recipe_id"])
        getUtility(IOCIRecipeSet).preloadDataForOCIRecipes(recipes)
        # XXX twom 2019-12-05 This needs to be extended to include
        # OCIRecipeBuildJob when that exists.
        return

    def getByID(self, build_id):
        """See `ISpecificBuildFarmJobSource`."""
        store = IMasterStore(OCIRecipeBuild)
        return store.get(OCIRecipeBuild, build_id)

    def getByBuildFarmJob(self, build_farm_job):
        """See `ISpecificBuildFarmJobSource`."""
        return Store.of(build_farm_job).find(
            OCIRecipeBuild, build_farm_job_id=build_farm_job.id).one()

    def getByBuildFarmJobs(self, build_farm_jobs):
        """See `ISpecificBuildFarmJobSource`."""
        if len(build_farm_jobs) == 0:
            return EmptyResultSet()
        rows = Store.of(build_farm_jobs[0]).find(
            OCIRecipeBuild, OCIRecipeBuild.build_farm_job_id.is_in(
                bfj.id for bfj in build_farm_jobs))
        return DecoratedResultSet(rows, pre_iter_hook=self.preloadBuildsData)
