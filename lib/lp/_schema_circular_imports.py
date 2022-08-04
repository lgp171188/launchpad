# Copyright 2009-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Update the interface schema values due to circular imports.

There are situations where there would normally be circular imports to define
the necessary schema values in some interface fields.  To avoid this the
schema is initially set to `Interface`, but this needs to be updated once the
types are defined.
"""

__all__ = []

from lp.bugs.interfaces.bugtask import IBugTask
from lp.buildmaster.interfaces.builder import IBuilder
from lp.buildmaster.interfaces.buildfarmjob import IBuildFarmJob
from lp.buildmaster.interfaces.buildqueue import IBuildQueue
from lp.code.interfaces.gitrepository import IGitRepository
from lp.registry.interfaces.person import IPerson
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
    patch_reference_property,
)

# IBuilder
patch_reference_property(IBuilder, "current_build", IBuildFarmJob)

# IBuildFarmJob
patch_reference_property(IBuildFarmJob, "buildqueue_record", IBuildQueue)

# IComment
patch_reference_property(IComment, "comment_author", IPerson)

# IIndexedMessage
patch_reference_property(IIndexedMessage, "inside", IBugTask)

# IMessage
patch_reference_property(IMessage, "owner", IPerson)
patch_collection_property(IMessage, "revisions", IMessageRevision)

# IUserToUserEmail
patch_reference_property(IUserToUserEmail, "sender", IPerson)
patch_reference_property(IUserToUserEmail, "recipient", IPerson)

# IAccessToken
patch_reference_property(IAccessToken, "git_repository", IGitRepository)
