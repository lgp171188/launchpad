# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Bug attachment interfaces."""

__all__ = [
    "BugAttachmentType",
    "IBugAttachment",
    "IBugAttachmentSet",
    "IBugAttachmentEditForm",
    "IBugAttachmentIsPatchConfirmationForm",
]

from lazr.enum import DBEnumeratedType, DBItem
from lazr.restful.declarations import (
    REQUEST_USER,
    call_with,
    export_write_operation,
    exported,
    exported_as_webservice_entry,
    operation_for_version,
)
from lazr.restful.fields import Reference
from zope.interface import Interface
from zope.schema import URI, Bool, Bytes, Choice, Int, List, TextLine

from lp import _
from lp.bugs.interfaces.hasbug import IHasBug
from lp.services.fields import Title
from lp.services.messages.interfaces.message import IMessage
from lp.services.webservice.apihelpers import patch_collection_property


class BugAttachmentType(DBEnumeratedType):
    """Bug Attachment Type.

    An attachment to a bug can be of different types, since for example
    a patch is more important than a screenshot. This schema describes the
    different types.
    """

    PATCH = DBItem(
        1,
        """
        Patch

        A patch that potentially fixes the bug.
        """,
    )

    UNSPECIFIED = DBItem(
        2,
        """
        Unspecified

        Any attachment other than a patch. For example: a screenshot,
        a log file, a core dump, or anything else that adds more information
        to the bug.
        """,
    )


class IBugAttachmentView(IHasBug):
    """Interface for BugAttachment that requires launchpad.View permission."""

    id = Int(title=_("ID"), required=True, readonly=True)
    bug = exported(
        Reference(Interface, title=_("The bug the attachment belongs to."))
    )
    type = exported(
        Choice(
            title=_("Attachment Type"),
            description=_(
                "The type of the attachment, for example Patch or "
                "Unspecified."
            ),
            vocabulary=BugAttachmentType,
            default=BugAttachmentType.UNSPECIFIED,
            required=True,
        )
    )
    title = exported(
        Title(
            title=_("Title"),
            description=_(
                "A short and descriptive description of the attachment"
            ),
            required=True,
        )
    )
    libraryfile = exported(
        Bytes(
            title=_("The attachment content."), required=False, readonly=True
        ),
        exported_as="data",
    )
    url = exported(
        URI(title=_("Attachment URL"), required=False, readonly=True)
    )
    _message_id = Int(title=_("Message ID"))
    message = exported(
        Reference(
            IMessage,
            title=_(
                "The message that was created when we "
                "added this attachment."
            ),
        )
    )
    is_patch = Bool(
        title=_("Patch?"),
        description=_("Is this attachment a patch?"),
        readonly=True,
    )
    displayed_url = URI(
        title=_(
            "Download URL of the files or the external URL of the attachment"
        ),
        readonly=True,
    )
    vulnerability_patches = List(
        title=_("Vulnerability patches"), readonly=True
    )

    def getFileByName(filename):
        """Return the `ILibraryFileAlias` for the given file name.

        NotFoundError is raised if the given filename does not match
        data.filename.
        """


class IBugAttachmentEdit(Interface):
    """Interface for BugAttachment that requires launchpad.Edit permission."""

    def destroySelf():
        """Delete this record.

        The library file content for this attachment is set to None.
        """

    @call_with(user=REQUEST_USER)
    @export_write_operation()
    @operation_for_version("beta")
    def removeFromBug(user):
        """Remove the attachment from the bug."""


@exported_as_webservice_entry(as_of="beta")
class IBugAttachment(IBugAttachmentView, IBugAttachmentEdit):
    """A file attachment to an IBug.

    Launchpadlib example of accessing content of an attachment::

        for attachment in bug.attachments:
            buffer = attachment.data.open()
            for line in buffer:
                print(line)
            buffer.close()

    Launchpadlib example of accessing metadata about an attachment::

        attachment = bug.attachments[0]
        print("title:", attachment.title)
        print("ispatch:", attachment.type)

    For information about the file-like object returned by
    attachment.data.open() see lazr.restfulclient's documentation of the
    HostedFile object.

    Details about the message associated with an attachment can be found on
    the "message" attribute::

        message = attachment.message
        print("subject:", message.subject)
        print("owner:", message.owner.display_name)
        print("created:", message.date_created)
    """


# Need to do this here because of circular imports.
patch_collection_property(IMessage, "bugattachments", IBugAttachment)


class IBugAttachmentSet(Interface):
    """A set for IBugAttachment objects."""

    def create(
        bug,
        filealias,
        url,
        title,
        message,
        type=IBugAttachment["type"].default,
        send_notifications=False,
    ):
        """Create a new attachment and return it.

        :param bug: The `IBug` to which the new attachment belongs.
        :param filealias: The `ILibraryFileAlias` containing
            the data (optional).
        :param url: External URL of the attachment (optional).
        :param message: The `IMessage` to which this attachment belongs.
        :param type: The type of attachment. See `BugAttachmentType`.
        :param send_notifications: If True, a notification is sent to
            subscribers of the bug.
        """

    def __getitem__(id):
        """Get an IAttachment by its id.

        Return NotFoundError if no such id exists.
        """


class IBugAttachmentEditForm(Interface):
    """Schema used to build the edit form for bug attachments."""

    title = IBugAttachment["title"]
    contenttype = TextLine(
        title="Content Type",
        description=(
            "The content type is only settable if the attachment isn't "
            "a patch. If it's a patch, the content type will be set to "
            "text/plain"
        ),
        required=True,
    )
    patch = Bool(
        title="This attachment contains a solution (patch) for this bug",
        required=True,
        default=False,
    )


class IBugAttachmentIsPatchConfirmationForm(Interface):
    """Schema used to confirm the setting of the "patch" flag."""

    patch = Bool(title="Is this file a patch", required=True, default=False)
