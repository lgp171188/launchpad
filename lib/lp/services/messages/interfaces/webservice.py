# Copyright 2011-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""All the interfaces that are exposed through the webservice.

There is a declaration in ZCML somewhere that looks like:
  <webservice:register module="lp.services.messages.interfaces.webservice" />

which tells `lazr.restful` that it should look for webservice exports here.
"""

__all__ = [
    "IMessage",
    "IMessageRevision",
]

from lp.bugs.interfaces.bugtask import IBugTask
from lp.registry.interfaces.person import IPerson
from lp.services.messages.interfaces.message import (
    IIndexedMessage,
    IMessage,
    IUserToUserEmail,
)
from lp.services.messages.interfaces.messagerevision import IMessageRevision
from lp.services.webservice.apihelpers import (
    patch_collection_property,
    patch_reference_property,
)

# IIndexedMessage
patch_reference_property(IIndexedMessage, "inside", IBugTask)

# IMessage
patch_reference_property(IMessage, "owner", IPerson)
patch_collection_property(IMessage, "revisions", IMessageRevision)

# IUserToUserEmail
patch_reference_property(IUserToUserEmail, "sender", IPerson)
patch_reference_property(IUserToUserEmail, "recipient", IPerson)
