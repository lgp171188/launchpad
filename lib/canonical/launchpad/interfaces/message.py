# Copyright 2004-2005 Canonical Ltd.  All rights reserved.
# pylint: disable-msg=E0211,E0213

__metaclass__ = type

__all__ = [
    'DuplicateMessageId',
    'IMessage',
    'IMessageChunk',
    'IMessageSet',
    'InvalidEmailMessage',
    'MissingSubject',
    'UnknownSender',
    ]

from zope.interface import Interface, Attribute
from zope.schema import Datetime, Int, Object, Text, TextLine

from canonical.launchpad import _
from canonical.launchpad.interfaces import NotFoundError
from canonical.launchpad.interfaces.person import IPerson

from canonical.lazr.rest.declarations import (
    export_as_webservice_entry, exported)

class IMessage(Interface):
    """A message.

    This is like an email (RFC822) message, though it could be created through
    the web as well.
    """
    export_as_webservice_entry()

    id = Int(
            title=_('ID'), required=True, readonly=True,
            )
    datecreated = exported(Datetime(
            title=_('Date Created'), required=True, readonly=True))

    subject = exported(TextLine(
            title=_('Subject'), required=True, readonly=True))

    # XXX flacoste 2006-09-08: This attribute is only used for the
    # add form used by MessageAddView.
    content = Text(title=_("Message"), required=True, readonly=True)
    owner = exported(Object(
            title=_('Person'), schema=IPerson, required=False, readonly=True))

    # Schema is really IMessage, but this cannot be declared here. It's
    # fixed below after the IMessage definition is complete.
    parent = exported(Object(
            title=_('Parent'), schema=Interface, required=False,
            readonly=True))

    distribution = Int(
            title=_('Distribution'), required=False, readonly=True,
            )
    rfc822msgid = TextLine(
            title=_('RFC822 Msg ID'), required=True, readonly=True,
            )
    raw = Int(
            title=_('Original unmodified email'), required=False,
            readonly=True
            )
    bugs = Attribute(_('Bug List'))
    chunks = Attribute(_('Message pieces'))

    text_contents = exported(Text(
        title=_('All the text/plain chunks joined together as a '
                'unicode string.')),
        exported_as='content')

    followup_title = Attribute(_('Candidate title for a followup message.'))

    title = Attribute(_('The message title, usually just the subject.'))
    bugattachments = Attribute("A list of BugAttachments connected to this "
        "message.")
    has_new_title = Attribute("Whether or not the title of this message "
        "is different to that of its parent.")

    def __iter__():
        """Iterate over all the message chunks."""

# Fix for self-referential schema.
IMessage['parent'].schema = IMessage

class IMessageSet(Interface):
    """Set of IMessage"""

    def get(rfc822msgid):
        """Return a list of IMessage's with the given rfc822msgid.

        If no such messages exist, raise NotFoundError.
        """

    def fromText(subject, content, owner=None, datecreated=None,
        rfc822msgid=None):
        """Construct a Message from a text string and return it."""

    def fromEmail(email_message, owner=None, filealias=None,
            parsed_message=None, fallback_parent=None):
        """Construct a Message from an email message and return it.

        `email_message` should be the original email as a string.

        `owner` specifies the owner of the new Message. The default
        is calculated using the From: or Reply-To: headers, and will raise
        a UnknownSender error if they cannot be found.

        `filealias` is the LibraryFileAlias of the raw email if it has
        already been stuffed into the Librarian. Default is for this
        method to stuff it into the Librarian for you. It should be an
        ILibraryFileAlias.

        `parsed_message` may be an email.Message.Message instance. If given,
        it is used internally instead of building one from the raw
        email_message. This is purely an optimization step, significant
        in many places because the emails we are handling may contain huge
        attachments and we should avoid reparsing them if possible.

        'fallback_parent' can be specified if you want a parent to be
        set, if no parent could be identified.

        Callers may want to explicitly handle the following exceptions:
            * UnknownSender
            * MissingSubject
            * DuplicateMessageId
            * InvalidEmailMessage
        """

    def threadMessages(messages):
        """Return a threaded version of supplied message list.

        Return value is a recursive list structure.
        Each parent entry in the top-level list is a tuple of
        (parent, children), where children is a list of parents.  (Parents
        may be childless.)

        Example:
        [(parent, [(child1, [(grandchild1, [])]), (child2, [])])]
        """

    def flattenThreads(threaded_messages):
        """Convert threaded messages into a flat, indented form.

        Take a thread (in the form produced by threadMessages) and
        iterate through a series of (depth, message) tuples.  The ordering
        will match that implied by the input structure, with all replies
        to a message appearing after that message.
        """


class IMessageChunk(Interface):
    id = Int(title=_('ID'), required=True, readonly=True)
    message = Int(title=_('Message'), required=True, readonly=True)
    sequence = Int(title=_('Sequence order'), required=True, readonly=True)
    content = Text(title=_('Text content'), required=False, readonly=True)
    blob = Int(title=_('Binary content'), required=False, readonly=True)


class UnknownSender(NotFoundError):
    """Raised if we cannot lookup an email message's sender in the database"""


class MissingSubject(ValueError):
    """Raised if we get an email message with no Subject: header"""


class DuplicateMessageId(ValueError):
    """Raised if we attempt to store a new email with an existing Message-Id

    Indicates a broken mail client or MTA.
    """


class InvalidEmailMessage(ValueError):
    """Raised if the email message is too broken for us to deal with.

    This indicates broken mail clients or MTAs, and is raised on conditions
    such as missing Message-Id or missing From: headers.
    """
