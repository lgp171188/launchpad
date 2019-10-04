from storm.properties import Unicode
from storm.locals import Int
from zope.interface import implementer

from lp.services.database.stormbase import StormBase
from lp.registry.interfaces.ocirecipename import IOCIRecipeName


@implementer(IOCIRecipeName)
class OCIRecipeName(StormBase):

    __storm_table__ = "OCIRecipeName"

    id = Int(primary=True)
    name = Unicode(name="name", allow_none=False)

    def __init__(self, name):
        super(OCIRecipeName, self).__init__()
        # XXX (twom): This should validate the name (valid_name constraint)
        self.name = name
