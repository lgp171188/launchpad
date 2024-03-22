# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""The database implementation class for CodeReviewComment."""

__all__ = [
    "CodeReviewComment",
]

from textwrap import TextWrapper

from lazr.delegates import delegate_to
from storm.locals import Int, Reference, Store, Unicode
from zope.interface import implementer

from lp.code.enums import CodeReviewVote
from lp.code.interfaces.branchtarget import IHasBranchTarget
from lp.code.interfaces.codereviewcomment import (
    ICodeReviewComment,
    ICodeReviewCommentDeletion,
)
from lp.services.database.enumcol import DBEnum
from lp.services.database.stormbase import StormBase
from lp.services.mail.signedmessage import signed_message_from_bytes
from lp.services.messages.interfaces.message import (
    IMessageCommon,
    IMessageEdit,
)


def quote_text_as_email(text, width=80):
    """Quote the text as if it is an email response.

    Uses '> ' as a line prefix, and breaks long lines.

    Trailing whitespace is stripped.
    """
    # Empty text begets empty text.
    if text is None:
        return ""
    text = text.rstrip()
    if not text:
        return ""
    prefix = "> "
    # The TextWrapper's handling of code is somewhat suspect.
    wrapper = TextWrapper(
        initial_indent=prefix,
        subsequent_indent=prefix,
        width=width,
        replace_whitespace=False,
    )
    result = []
    # Break the string into lines, and use the TextWrapper to wrap the
    # individual lines.
    for line in text.rstrip().split("\n"):
        # TextWrapper won't do an indent of an empty string.
        if line.strip() == "":
            result.append(prefix)
        else:
            result.extend(wrapper.wrap(line))
    return "\n".join(result)


@implementer(
    ICodeReviewComment,
    ICodeReviewCommentDeletion,
    IHasBranchTarget,
    IMessageCommon,
    IMessageEdit,
)
@delegate_to(IMessageCommon, IMessageEdit, context="message")
class CodeReviewComment(StormBase):
    """A table linking branch merge proposals and messages."""

    __storm_table__ = "CodeReviewMessage"

    id = Int(primary=True)
    branch_merge_proposal_id = Int(
        name="branch_merge_proposal", allow_none=False
    )
    branch_merge_proposal = Reference(
        branch_merge_proposal_id, "BranchMergeProposal.id"
    )
    message_id = Int(name="message", allow_none=False)
    message = Reference(message_id, "Message.id")
    vote = DBEnum(name="vote", allow_none=True, enum=CodeReviewVote)
    vote_tag = Unicode(default=None)

    def __init__(
        self, branch_merge_proposal, message, vote=None, vote_tag=None
    ):
        self.branch_merge_proposal = branch_merge_proposal
        self.message = message
        self.vote = vote
        self.vote_tag = vote_tag

    @property
    def author(self):
        """Defer to the related message."""
        return self.message.owner

    @property
    def date_created(self):
        """Defer to the related message."""
        return self.message.datecreated

    @property
    def target(self):
        """See `IHasBranchTarget`."""
        return self.branch_merge_proposal.target

    @property
    def title(self):
        return "Comment on proposed merge of %(source)s into %(target)s" % {
            "source": self.branch_merge_proposal.merge_source.display_name,
            "target": self.branch_merge_proposal.merge_target.display_name,
        }

    @property
    def message_body(self):
        """See `ICodeReviewComment'."""
        return self.message.text_contents

    def getAttachments(self):
        """See `ICodeReviewComment`."""
        attachments = [
            chunk.blob
            for chunk in self.message.chunks
            if chunk.blob is not None
        ]
        # Attachments to show.
        good_mimetypes = {"text/plain", "text/x-diff", "text/x-patch"}
        display_attachments = [
            attachment
            for attachment in attachments
            if (
                (attachment.mimetype in good_mimetypes)
                or attachment.filename.endswith(".diff")
                or attachment.filename.endswith(".patch")
            )
        ]
        other_attachments = [
            attachment
            for attachment in attachments
            if attachment not in display_attachments
        ]
        return display_attachments, other_attachments

    @property
    def as_quoted_email(self):
        return quote_text_as_email(self.message_body)

    def getOriginalEmail(self):
        """See `ICodeReviewComment`."""
        if self.message.raw is None:
            return None
        return signed_message_from_bytes(self.message.raw.read())

    @property
    def visible(self):
        return self.message.visible

    def userCanSetCommentVisibility(self, user):
        """See `ICodeReviewComment`."""
        return self.branch_merge_proposal.userCanSetCommentVisibility(
            user
        ) or (user is not None and user.inTeam(self.author))

    def destroySelf(self):
        """Delete this comment."""
        Store.of(self).remove(self)
