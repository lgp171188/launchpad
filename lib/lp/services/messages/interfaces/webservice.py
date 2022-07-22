# Copyright 2011-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""All the interfaces that are exposed through the webservice.

There is a declaration in ZCML somewhere that looks like:
  <webservice:register module="lp.patchwebservice" />

which tells `lazr.restful` that it should look for webservice exports here.
"""

__all__ = [
    "IMessage",
    "IMessageRevision",
]

from lp import _schema_circular_imports
from lp.services.messages.interfaces.message import IMessage
from lp.services.messages.interfaces.messagerevision import IMessageRevision

_schema_circular_imports
