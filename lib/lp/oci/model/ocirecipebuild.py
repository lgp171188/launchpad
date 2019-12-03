# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""A build record for OCI Recipes."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    'OCIRecipeBuild',
    'OCIRecipeBuildSet'
    ]


import pytz
from storm.locals import (
    Bool,
    DateTime,
    Int,
    Reference,
    Storm,
    Unicode,
    )
from zope.component import getUtility
from zope.interface import implementer

from lp.buildmaster.enums import (
    BuildFarmJobType,
    BuildStatus,
    )
from lp.buildmaster.interfaces.buildfarmjob import IBuildFarmJobSource
from lp.buildmaster.model.buildfarmjob import SpecificBuildFarmJobSourceMixin
from lp.buildmaster.model.packagebuild import PackageBuildMixin
from lp.oci.interfaces.ocirecipebuild import (
    IOCIRecipeBuild,
    IOCIRecipeBuildSet,
    )
from lp.services.database.constants import DEFAULT
from lp.services.database.enumcol import DBEnum
from lp.services.database.interfaces import IMasterStore


@implementer(IOCIRecipeBuild)
class OCIRecipeBuild(PackageBuildMixin, Storm):

    __storm_table__ = 'OCIRecipeBuild'

    job_type = BuildFarmJobType.OCIRECIPEBUILD

    id = Int(name='id', primary=True)

    build_farm_job_id = Int(name='build_farm_job', allow_none=False)
    build_farm_job = Reference(build_farm_job_id, 'BuildFarmJob.id')

    requester_id = Int(name='requester', allow_none=False)
    requester = Reference(requester_id, 'Person.id')

    recipe_id = Int(name='recipe', allow_none=False)
    recipe = Reference(recipe_id, 'OCIRecipe.id')

    channel_name = Unicode(name="channel_name", allow_none=False)

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

    def __init__(self, build_farm_job, requester, recipe, channel_name,
                 processor, virtualized, date_created):

        self.build_farm_job = build_farm_job
        self.requester = requester
        self.recipe = recipe
        self.channel_name = channel_name
        self.processor = processor
        self.virtualized = virtualized
        self.date_created = date_created
        self.status = BuildStatus.NEEDSBUILD

    def queueBuild(self):
        """See `IPackageBuild`."""
        # XXX twom 2019-11-28 Currently a no-op skeleton, to be filled in
        return


@implementer(IOCIRecipeBuildSet)
class OCIRecipeBuildSet(SpecificBuildFarmJobSourceMixin):
    """See `IOCIRecipeBuildSet`."""

    def new(self, requester, recipe, channel_name, processor, virtualized,
            date_created=DEFAULT):
        """See `IOCIRecipeBuildSet`."""
        store = IMasterStore(OCIRecipeBuild)
        build_farm_job = getUtility(IBuildFarmJobSource).new(
            OCIRecipeBuild.job_type, BuildStatus.NEEDSBUILD, date_created)
        ocirecipebuild = OCIRecipeBuild(
            build_farm_job, requester, recipe, channel_name, processor,
            virtualized, date_created)
        store.add(ocirecipebuild)
        return ocirecipebuild

    def preloadBuildsData(self, builds):
        """See `IOCIRecipeBuildSet`."""
        # XXX twom 2019-12-02 Currently a no-op skeleton, to be filled in
        return

    def getByID(self, build_id):
        """See `ISpecificBuildFarmJobSource`."""
        store = IMasterStore(OCIRecipeBuild)
        return store.get(OCIRecipeBuild, build_id)
