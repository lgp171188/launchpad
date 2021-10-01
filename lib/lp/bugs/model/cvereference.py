# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = ['CveReference']

from storm.locals import (
    Int,
    Reference,
    Unicode,
    )
from zope.interface import implementer

from lp.bugs.interfaces.cvereference import ICveReference
from lp.services.database.stormbase import StormBase


@implementer(ICveReference)
class CveReference(StormBase):
    """A CVE reference to some other tracking system."""

    __storm_table__ = 'CveReference'

    id = Int(primary=True)

    cve_id = Int(name='cve', allow_none=False)
    cve = Reference(cve_id, 'Cve.id')
    source = Unicode(allow_none=False)
    content = Unicode(allow_none=False)
    url = Unicode(allow_none=True, default=None)

    def __init__(self, cve, source, content, url=None):
        super(CveReference, self).__init__()
        self.cve = cve
        self.source = source
        self.content = content
        self.url = url
