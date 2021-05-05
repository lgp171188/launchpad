# Copyright 2009-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Message related view classes."""

__metaclass__ = type

from zope.interface import implementer

from lp.bugs.interfaces.bugmessage import IBugMessage
from lp.services.messages.interfaces.message import IIndexedMessage
from lp.services.webapp.interfaces import ICanonicalUrlData


@implementer(ICanonicalUrlData)
class QuestionMessageCanonicalUrlData:
    """Question messages have a canonical_url within the question."""
    rootsite = 'answers'

    def __init__(self, question, message):
        self.inside = question
        self.path = "messages/%d" % message.display_index


@implementer(ICanonicalUrlData)
class BugMessageCanonicalUrlData:
    """Bug messages have a canonical_url within the primary bugtask."""
    rootsite = 'bugs'

    def __init__(self, bug, message):
        self.inside = bug.default_bugtask
        if IBugMessage.providedBy(message):
            # bug.messages is a list of Message objects, not BugMessage.
            message = message.message
        self.path = "comments/%d" % list(bug.messages).index(message)


@implementer(ICanonicalUrlData)
class IndexedBugMessageCanonicalUrlData:
    """An optimized bug message canonical_url implementation.

    This implementation relies on the message being decorated with
    its index and context.
    """
    rootsite = 'bugs'

    def __init__(self, message):
        self.inside = message.inside
        self.path = "comments/%d" % message.index


@implementer(ICanonicalUrlData)
class CodeReviewCommentCanonicalUrlData:
    """An optimized bug message canonical_url implementation.
    """
    rootsite = 'code'

    def __init__(self, message):
        self.inside = message.branch_merge_proposal
        self.path = "comments/%d" % message.id


def message_to_canonical_url_data(message):
    """This factory creates `ICanonicalUrlData` for Message."""
    # Circular imports
    from lp.answers.interfaces.questionmessage import IQuestionMessage
    from lp.code.interfaces.codereviewcomment import ICodeReviewComment
    if IIndexedMessage.providedBy(message):
        return IndexedBugMessageCanonicalUrlData(message)
    elif IQuestionMessage.providedBy(message):
        return QuestionMessageCanonicalUrlData(message.question, message)
    elif ICodeReviewComment.providedBy(message):
        return CodeReviewCommentCanonicalUrlData(message)
    else:
        if message.bugs.count() == 0:
        # Will result in a ComponentLookupError
            return None
        return BugMessageCanonicalUrlData(message.bugs[0], message)
