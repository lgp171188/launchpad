from storm.locals import (
    Int,
    Reference,
    Storm,
    Text,
    )
from zope.interfaces import implementer

from lp.buildmaster.enums import BuildFarmJobType
from lp.buildmaster.model.packagebuild import PackageBuildMixin
from lp.oci.interfaces.ocirecipebuild import IOCIRecipeBuild


@implementer(IOCIRecipeBuild)
class OCIRecipeBuild(PackageBuildMixin, Storm):

    __storm_table__ = 'OCIRecipeBuild'

    job_type = BuildFarmJobType.OCIBUILD

    id = Int(name='id', primary=True)

    build_farm_job_id = Int(name='build_farm_job', allow_none=False)
    build_farm_job = Reference(build_farm_job_id, 'BuildFarmJob.id')

    requester_id = Int(name='requester', allow_none=False)
    requester = Reference(requester_id, 'Person.id')

    recipe_id = Int(name='recipe', allow_none=False)
    recipe = Reference(recipe_id, 'OCIRecipe.id')

    channel_name = Text(name="channel_name", allow_none=False)

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
