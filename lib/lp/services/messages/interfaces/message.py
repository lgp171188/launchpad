# Copyright 2009-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "IDirectEmailAuthorization",
    "IIndexedMessage",
    "IMessage",
    "IMessageChunk",
    "IMessageCommon",
    "IMessageEdit",
    "IMessageSet",
    "IMessageView",
    "IUserToUserEmail",
    "IndexedMessage",
    "InvalidEmailMessage",
    "QuotaReachedError",
    "UnknownSender",
]


from lazr.delegates import delegate_to
from lazr.restful.declarations import (
    accessor_for,
    export_read_operation,
    export_write_operation,
    exported,
    exported_as_webservice_entry,
    operation_for_version,
    operation_parameters,
)
from lazr.restful.fields import CollectionField, Reference
from zope.interface import Attribute, Interface, implementer
from zope.schema import Bool, Datetime, Int, Object, Text, TextLine

from lp import _
from lp.app.errors import NotFoundError
from lp.services.librarian.interfaces import ILibraryFileAlias
from lp.services.webservice.apihelpers import patch_reference_property


class IMessageEdit(Interface):
    @export_write_operation()
    @operation_parameters(
        new_content=Text(
            title=_("Message content"),
            description=_("The new message content string"),
            required=True,
        )
    )
    @operation_for_version("devel")
    def editContent(new_content):
        """Edit the content of this message, generating a new message
        revision with the old content.
        """

    @export_write_operation()
    @operation_for_version("devel")
    def deleteContent():
        """Deletes this message content."""


class IMessageCommon(Interface):
    """Common public attributes for every IMessage implementation."""

    id = Int(title=_("ID"), required=True, readonly=True)

    chunks = Attribute(_("Message pieces"))
    text_contents = exported(
        Text(
            title=_(
                "All the text/plain chunks joined together as a "
                "unicode string."
            ),
            readonly=True,
        ),
        exported_as="content",
    )
    owner = exported(
        Reference(
            title=_("Person"),
            # Really IPerson, patched in
            # lp.services.messages.interfaces.webservice.
            schema=Interface,
            required=False,
            readonly=True,
        )
    )

    revisions = exported(
        CollectionField(
            title=_("Message revision history"),
            description=_(
                "Revision history of this message, sorted in ascending order."
            ),
            # Really IMessageRevision, patched in
            # lp.services.messages.interfaces.webservice.
            value_type=Reference(schema=Interface),
            required=False,
            readonly=True,
        ),
        as_of="devel",
    )

    datecreated = exported(
        Datetime(title=_("Date Created"), required=True, readonly=True),
        exported_as="date_created",
    )
    date_last_edited = exported(
        Datetime(
            title=_("When this message was last edited"),
            required=False,
            readonly=True,
        )
    )
    date_deleted = exported(
        Datetime(
            title=_("When this message was deleted"),
            required=False,
            readonly=True,
        )
    )

    def getRevisionByNumber(revision_number):
        """Returns the revision with the given number."""


class IMessageView(IMessageCommon):
    """Public attributes for message.

    This is like an email (RFC822) message, though it could be created through
    the web as well.
    """

    subject = exported(
        TextLine(title=_("Subject"), required=True, readonly=True)
    )

    content = Text(title=_("Message"), required=True, readonly=True)

    # Schema is really IMessage, but this cannot be declared here. It's
    # fixed below after the IMessage definition is complete.
    parent = exported(
        Reference(
            title=_("Parent"), schema=Interface, required=False, readonly=True
        )
    )

    rfc822msgid = TextLine(
        title=_("RFC822 Msg ID"), required=True, readonly=True
    )
    raw = Reference(
        title=_("Original unmodified email"),
        schema=ILibraryFileAlias,
        required=False,
        readonly=True,
    )
    bugs = CollectionField(
        title=_("Bug List"), value_type=Reference(schema=Interface)
    )  # Redefined in bug.py

    title = TextLine(
        title=_("The message title, usually just the subject."), readonly=True
    )
    visible = exported(
        Bool(
            title=_("Message visibility."),
            description=_("Whether or not the message is visible."),
            readonly=True,
            default=True,
        ),
        as_of="devel",
    )

    bugattachments = exported(
        CollectionField(
            title=_("A list of BugAttachments connected to this " "message."),
            value_type=Reference(Interface),
        ),
        exported_as="bug_attachments",
    )

    def __iter__():
        """Iterate over all the message chunks."""

    @accessor_for(parent)
    @export_read_operation()
    @operation_for_version("beta")
    def getAPIParent():
        """Return None because messages are not threaded over the API."""


@exported_as_webservice_entry("message", as_of="beta")
class IMessage(IMessageEdit, IMessageView):
    """A Message."""


# Fix for self-referential schema.
patch_reference_property(IMessage, "parent", IMessage)


class IMessageSet(Interface):
    """Set of IMessage"""

    def get(rfc822msgid):
        """Return a list of IMessage's with the given rfc822msgid.

        If no such messages exist, raise NotFoundError.
        """

    def fromText(
        subject, content, owner=None, datecreated=None, rfc822msgid=None
    ):
        """Construct a Message from a text string and return it."""

    def fromEmail(
        email_message,
        owner=None,
        filealias=None,
        parsed_message=None,
        fallback_parent=None,
        date_created=None,
        restricted=False,
    ):
        """Construct a Message from an email message and return it.

        :param email_message: The original email as a byte string.
        :param owner: Specifies the owner of the new Message. The default
            is calculated using the From: or Reply-To: headers, and will raise
            a UnknownSender error if they cannot be found.
        :param filealias: The `LibraryFileAlias` of the raw email if it has
            already been uploaded to the Librarian.
        :param parsed_message: An email.message.Message instance. If given,
            it is used internally instead of building one from the raw
            email_message. This is purely an optimization step, significant
            in many places because the emails we are handling may contain huge
            attachments and we should avoid reparsing them if possible.
        :param fallback_parent: The parent message if it could not be
            identified.
        :param date_created: Force a created date for the message. If
            specified, the value in the Date field in the passed message will
            be ignored.
        :param restricted: If set, the `LibraryFileAlias` will be uploaded to
            the restricted librarian.

        Callers may want to explicitly handle the following exceptions:
            * UnknownSender
            * InvalidEmailMessage
        """


class IIndexedMessage(Interface):
    """An `IMessage` decorated with its index and context."""

    inside = Reference(
        title=_("Inside"),
        # Really IBugTask, patched in
        # lp.services.messages.interfaces.webservice.
        schema=Interface,
        description=_("The bug task which is the context for this message."),
        required=True,
        readonly=True,
    )
    index = Int(
        title=_("Index"),
        description=_(
            "The index of this message in the list "
            "of messages in its context."
        ),
    )


@delegate_to(IMessage)
@implementer(IIndexedMessage)
class IndexedMessage:
    """Adds the `inside` and `index` attributes to an IMessage."""

    def __init__(self, context, inside, index, parent=None):
        self.context = context
        self.inside = inside
        self.index = index
        self._parent = parent

    @property
    def parent(self):
        return self._parent


class IMessageChunk(Interface):
    id = Int(title=_("ID"), required=True, readonly=True)
    message = Int(title=_("Message"), required=True, readonly=True)
    sequence = Int(title=_("Sequence order"), required=True, readonly=True)
    content = Text(title=_("Text content"), required=False, readonly=True)
    blob = Int(title=_("Binary content"), required=False, readonly=True)


class QuotaReachedError(Exception):
    """The user-to-user contact email quota has been reached for today."""

    def __init__(self, sender, authorization):
        Exception.__init__(self)
        self.sender = sender
        self.authorization = authorization


class IUserToUserEmail(Interface):
    """User to user direct email communications."""

    sender = Object(
        # Really IPerson, patched in
        # lp.services.messages.interfaces.webservice.
        schema=Interface,
        title=_("The message sender"),
        required=True,
        readonly=True,
    )

    recipient = Object(
        # Really IPerson, patched in
        # lp.services.messages.interfaces.webservice.
        schema=Interface,
        title=_("The message recipient"),
        required=True,
        readonly=True,
    )

    date_sent = Datetime(
        title=_("Date sent"),
        description=_(
            "The date this message was sent from sender to recipient."
        ),
        required=True,
        readonly=True,
    )

    subject = TextLine(title=_("Subject"), required=True, readonly=True)

    message_id = TextLine(
        title=_("RFC 2822 Message-ID"), required=True, readonly=True
    )


class IDirectEmailAuthorization(Interface):
    """Can a Launchpad user contact another Launchpad user?"""

    is_allowed = Bool(
        title=_(
            "Is the sender allowed to send a message to a Launchpad user?"
        ),
        description=_(
            "True if the sender allowed to send a message to another "
            "Launchpad user."
        ),
        readonly=True,
    )

    throttle_date = Datetime(
        title=_("The earliest date used to throttle senders."),
        readonly=True,
    )

    message_quota = Int(
        title=_("The maximum number of messages allowed per quota period"),
        readonly=True,
    )

    def record(message):
        """Record that the message was sent.

        :param message: The email message that was sent.
        :type message: `email.message.Message`
        """


class UnknownSender(NotFoundError):
    """Raised if we cannot lookup an email message's sender in the database"""


class InvalidEmailMessage(ValueError):
    """Raised if the email message is too broken for us to deal with.

    This indicates broken mail clients or MTAs, and is raised on conditions
    such as missing Message-Id or missing From: headers.
    """
