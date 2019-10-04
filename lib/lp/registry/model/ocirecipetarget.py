from datetime import datetime
import pytz
from storm.locals import (
    Bool,
    DateTime,
    Int,
    Reference,
    Unicode,
    )
from zope.interface import implementer

from lp.services.database.stormbase import StormBase
from lp.registry.interfaces.ocirecipetarget import IOCIRecipeTarget


@implementer(IOCIRecipeTarget)
class OCIRecipeTarget(StormBase):

    __storm_table__ = "OCIRecipeTarget"

    id = Int(primary=True)
    date_created = DateTime(
        name="date_created", tzinfo=pytz.UTC, allow_none=False)
    date_last_modified = DateTime(
        name="date_last_modified", tzinfo=pytz.UTC, allow_none=False)

    registrant_id = Int(name='registrant', allow_none=False)
    registrant = Reference(registrant_id, "Person.id")

    project_id = Int(name="project", allow_none=True)
    project = Reference(project_id, "Product.id")

    distribution_id = Int(name="distribution", allow_none=True)
    distribution = Reference(distribution_id, "Distribution.id")

    ocirecipename_id = Int(name="ocirecipename", allow_none=False)
    ocirecipename = Reference(ocirecipename_id, "OCIRecipeName.id")

    description = Unicode(name="description")

    bug_supervisor_id = Int(name="bug_supervisor", allow_none=True)
    bug_supervisor = Reference(bug_supervisor_id, "Person.id")

    bug_reporting_guidelines = Unicode(name="bug_reporting_guidelines")
    bug_reported_acknowledgement = Unicode(name="bug_reported_acknowledgement")
    enable_bugfiling_duplicate_search = Bool(
        name="enable_bugfiling_duplicate_search")

    def __init__(self, registrant, project, distribution, ocirecipename,
                 date_created=None, description=None, bug_supervisor=None,
                 bug_reporting_guidelines=None,
                 bug_reported_acknowledgement=None,
                 bugfiling_duplicate_search=False):
        super(OCIRecipeTarget, self).__init__()
        if not date_created:
            created_date = datetime.now(pytz.timezone('UTC'))
            self.date_created = created_date
            self.date_last_modified = created_date
        self.registrant = registrant
        self.project = project
        self.distribution = distribution
        self.ocirecipename = ocirecipename
        self.description = description
        self.bug_supervisor = bug_supervisor,
        self.bug_reporting_guidelines = bug_reporting_guidelines
        self.enable_bugfiling_duplicate_search = bugfiling_duplicate_search
