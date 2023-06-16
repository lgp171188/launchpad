Bug Attachments
===============

Files can be attached to bugs. There are two types of attachment, Patch
and Unspecified. Patch means a proposed fix to the bug, Unspecified
means a file files that relates to the bug in some other way, like a log
file or a screenshot.

Let's look at a bug that has no attachments:
    >>> from lp.testing import login
    >>> login("foo.bar@canonical.com")

    >>> from lp.services.messages.interfaces.message import IMessageSet
    >>> from lp.bugs.interfaces.bug import IBugSet
    >>> from lp.bugs.interfaces.bugattachment import IBugAttachment
    >>> from lp.registry.interfaces.person import IPersonSet
    >>> bugset = getUtility(IBugSet)
    >>> bug_four = bugset.get(4)
    >>> bug_four.attachments.count()
    0


Creating attachments
--------------------

To create an attachment, call IBug.addAttachment. It will emit an
ObjectCreatedEvent in order to trigger email notifications:

    >>> from io import BytesIO

    >>> from lazr.lifecycle.event import IObjectCreatedEvent
    >>> from lp.testing.fixture import ZopeEventHandlerFixture
    >>> def attachment_added(attachment, event):
    ...     print("Attachment added: '%s'" % attachment.libraryfile.filename)
    ...
    >>> event_listener = ZopeEventHandlerFixture(
    ...     attachment_added, (IBugAttachment, IObjectCreatedEvent)
    ... )
    >>> event_listener.setUp()

    >>> filecontent = b"Some useful information."
    >>> data = BytesIO(filecontent)

    >>> foobar = getUtility(IPersonSet).getByName("name16")

    >>> message = getUtility(IMessageSet).fromText(
    ...     subject="test subject",
    ...     content="a comment for the attachment",
    ...     owner=foobar,
    ... )

    >>> bug_four.addAttachment(
    ...     owner=foobar,
    ...     data=data,
    ...     filename="foo.bar",
    ...     url=None,
    ...     description="this fixes the bug",
    ...     comment=message,
    ...     is_patch=False,
    ... )
    Attachment added: 'foo.bar'
    <BugAttachment ...>

    >>> import transaction
    >>> transaction.commit()

    >>> bug_four.attachments.count()
    1
    >>> attachment = bug_four.attachments[0]
    >>> attachment.type.title
    'Unspecified'

IBug.addAttachment's comment parameter can also be a string. The data
passed in is often a file-like object, but can be bytes too.

    >>> data = filecontent
    >>> attachment_from_strings = bug_four.addAttachment(
    ...     owner=foobar,
    ...     data=data,
    ...     filename="foo.baz",
    ...     url=None,
    ...     description="this fixes the bug",
    ...     comment="a string comment",
    ...     is_patch=False,
    ... )
    Attachment added: 'foo.baz'

    >>> print(attachment_from_strings.message.text_contents)
    a string comment

If no description is given, the title is set to the filename.

    >>> data = BytesIO(filecontent)
    >>> screenshot = bug_four.addAttachment(
    ...     owner=foobar,
    ...     data=data,
    ...     url=None,
    ...     filename="screenshot.jpg",
    ...     comment="a string comment",
    ...     is_patch=False,
    ... )
    Attachment added: 'screenshot.jpg'
    >>> print(screenshot.title)
    screenshot.jpg

The content type is guessed based on the information provided.

    >>> print(screenshot.libraryfile.mimetype)
    image/jpeg

    >>> data = BytesIO(b"</something-htmlish>")
    >>> debdiff = bug_four.addAttachment(
    ...     owner=foobar,
    ...     data=data,
    ...     filename="something.debdiff",
    ...     url=None,
    ...     comment="something debdiffish",
    ...     is_patch=False,
    ... )
    Attachment added: 'something.debdiff'
    >>> print(debdiff.title)
    something.debdiff
    >>> print(debdiff.libraryfile.filename)
    something.debdiff
    >>> print(debdiff.libraryfile.mimetype)
    text/plain

The librarian won't allow empty files, so the view that creates the
attachment needs to handle that:

    >>> from zope.component import getMultiAdapter
    >>> from lp.services.webapp.servers import LaunchpadTestRequest

    >>> login("test@canonical.com")
    >>> filecontent = BytesIO(b"")
    >>> filecontent.filename = "foo.bar"
    >>> add_request = LaunchpadTestRequest(
    ...     method="POST",
    ...     form={
    ...         "field.subject": "Title",
    ...         "field.comment": "Some comment.",
    ...         "field.filecontent": filecontent,
    ...         "field.patch": "",
    ...         "field.actions.save": "Save Changes",
    ...     },
    ... )

Note that the +addcomment-form view is actually registered on a "bug in
context", i.e. an IBugTask, so let's grab the first bugtask on bug_four
and work with that:

    >>> bugtask = bug_four.bugtasks[0]

    >>> add_comment_view = getMultiAdapter(
    ...     (bugtask, add_request), name="+addcomment-form"
    ... )
    >>> add_comment_view.initialize()
    >>> len(add_comment_view.errors)
    1
    >>> add_comment_view.error_count
    'There is 1 error.'
    >>> print(add_comment_view.getFieldError("filecontent"))
    Cannot upload empty file.

It's possible to limit the maximum size of the attachments by setting
max_attachment_size in launchpad-lazr.conf. The default value for the
testrunner is 1024, so let's create a file larger than that and try to
upload it:

    >>> filecontent = BytesIO(b"x" * 1025)
    >>> filecontent.filename = "foo.txt"
    >>> add_request = LaunchpadTestRequest(
    ...     method="POST",
    ...     form={
    ...         "field.subject": "Title",
    ...         "field.comment": "Some comment.",
    ...         "field.include_attachment": "on",
    ...         "field.filecontent": filecontent,
    ...         "field.attachment_description": "blah",
    ...         "field.patch": "",
    ...         "field.actions.save": "Save Changes",
    ...     },
    ... )
    >>> add_comment_view = getMultiAdapter(
    ...     (bugtask, add_request), name="+addcomment-form"
    ... )
    >>> add_comment_view.initialize()
    >>> len(add_comment_view.errors)
    1
    >>> for error in add_comment_view.errors:
    ...     print(error.doc())
    ...
    Cannot upload files larger than 1024 bytes

If we set the limit to 0 we can upload it, though, since a value of 0
means no limit:

    >>> from lp.services.config import config
    >>> max_attachment_size = """
    ...     [launchpad]
    ...     max_attachment_size: 0
    ...     """
    >>> config.push("max_attachment_size", max_attachment_size)
    >>> add_request = LaunchpadTestRequest(
    ...     method="POST",
    ...     form={
    ...         "field.subject": "Title",
    ...         "field.comment": "Some comment.",
    ...         "field.include_attachment": "on",
    ...         "field.filecontent": filecontent,
    ...         "field.attachment_description": "blah",
    ...         "field.patch": "",
    ...         "field.actions.save": "Save Changes",
    ...     },
    ... )
    >>> add_comment_view = getMultiAdapter(
    ...     (bugtask, add_request), name="+addcomment-form"
    ... )
    >>> add_comment_view.initialize()
    Attachment added: 'foo.txt'
    >>> len(add_comment_view.errors)
    0

The request must contain either a comment or an attachment or both, but it
must have at least one.

    >>> add_request = LaunchpadTestRequest(
    ...     method="POST",
    ...     form={
    ...         "field.subject": "Title",
    ...         "field.patch": "",
    ...         "field.actions.save": "Save Changes",
    ...     },
    ... )
    >>> add_comment_view = getMultiAdapter(
    ...     (bugtask, add_request), name="+addcomment-form"
    ... )
    >>> add_comment_view.initialize()
    >>> len(add_comment_view.errors)
    1
    >>> for error in add_comment_view.errors:
    ...     print(error)
    ...
    Either a comment or attachment must be provided.

If the request contains no attachment description the filename should be used.

    >>> filecontent = BytesIO(
    ...     b"No, sir. That's one bonehead name, but that ain't me any more."
    ... )
    >>> filecontent.filename = "RA.txt"
    >>> add_request = LaunchpadTestRequest(
    ...     method="POST",
    ...     form={
    ...         "field.subject": "Title",
    ...         "field.comment": "Some comment.",
    ...         "field.filecontent": filecontent,
    ...         "field.patch": "",
    ...         "field.actions.save": "Save Changes",
    ...     },
    ... )
    >>> add_comment_view = getMultiAdapter(
    ...     (bugtask, add_request), name="+addcomment-form"
    ... )
    >>> add_comment_view.initialize()
    Attachment added: 'RA.txt'
    >>> len(add_comment_view.errors)
    0
    >>> print(bug_four.attachments[bug_four.attachments.count() - 1].title)
    RA.txt

Since the ObjectCreatedEvent was generated, a notification about the
attachment was added.

    >>> from lp.bugs.model.bugnotification import BugNotification
    >>> from lp.services.database.interfaces import IStore
    >>> latest_notification = (
    ...     IStore(BugNotification)
    ...     .find(BugNotification)
    ...     .order_by(BugNotification.id)
    ...     .last()
    ... )
    >>> print(latest_notification.message.text_contents)
    ** Attachment added: "RA.txt"
       http://.../RA.txt

Let's try uploading a file with some weird characters in them:

    >>> filecontent.filename = "foö bar"
    >>> add_request = LaunchpadTestRequest(
    ...     method="POST",
    ...     form={
    ...         "field.subject": "Title",
    ...         "field.comment": "Some comment.",
    ...         "field.include_attachment": "on",
    ...         "field.filecontent": filecontent,
    ...         "field.attachment_description": "blah",
    ...         "field.patch": "",
    ...         "field.actions.save": "Save Changes",
    ...     },
    ... )
    >>> add_comment_view = getMultiAdapter(
    ...     (bugtask, add_request), name="+addcomment-form"
    ... )
    >>> len(add_comment_view.errors)
    0
    >>> add_comment_view.initialize()
    Attachment added: 'foö bar'
    >>> len(add_comment_view.errors)
    0
    >>> attachments = bug_four.attachments
    >>> print(
    ...     attachments[bug_four.attachments.count() - 1].libraryfile.filename
    ... )
    foö bar
    >>> attachments[bug_four.attachments.count() - 1].libraryfile.http_url
    'http://.../fo%C3%B6%20bar'

If a filename contains a slash, it will be converted to a dash instead.
We do this since otherwise it won't be possible to download the file
from the librarian.

    >>> filecontent.filename = "foo/bar/baz"
    >>> add_request = LaunchpadTestRequest(
    ...     method="POST",
    ...     form={
    ...         "field.subject": "Title",
    ...         "field.comment": "Some comment.",
    ...         "field.include_attachment": "on",
    ...         "field.filecontent": filecontent,
    ...         "field.attachment_description": "blah",
    ...         "field.patch": "",
    ...         "field.actions.save": "Save Changes",
    ...     },
    ... )
    >>> add_comment_view = getMultiAdapter(
    ...     (bugtask, add_request), name="+addcomment-form"
    ... )
    >>> add_comment_view.initialize()
    Attachment added: 'foo-bar-baz'
    >>> len(add_comment_view.errors)
    0
    >>> print(
    ...     attachments[bug_four.attachments.count() - 1].libraryfile.filename
    ... )
    foo-bar-baz
    >>> attachments[bug_four.attachments.count() - 1].libraryfile.http_url
    'http://.../foo-bar-baz'

    >>> config_data = config.pop("max_attachment_size")
    >>> event_listener.cleanUp()


Security
--------

If a user can view/edit the bug the attachment is attached to, they can
also view/edit the attachment. At the moment the bug_four is public, so
anonymous can read the attachment's attributes, but they can't set them:

    >>> login(ANONYMOUS)
    >>> print(attachment.title)
    this fixes the bug
    >>> attachment.title = "Better Title"
    Traceback (most recent call last):
    ...
    zope.security.interfaces.Unauthorized: (..., 'title',...

    >>> import transaction
    >>> transaction.abort()

Attachment owner can access and set the attributes, though:

    >>> login("foo.bar@canonical.com")
    >>> print(attachment.title)
    this fixes the bug
    >>> attachment.title = "Even Better Title"

Now let's make the bug private instead:

    >>> bug_four.setPrivate(True, getUtility(ILaunchBag).user)
    True
    >>> logout()

Foo Bar isn't explicitly subscribed to the bug, BUT they are an admin, so
they can access the attachment's attributes:

    >>> login("test@canonical.com")
    >>> print(attachment.title)
    Even Better Title

Mr. No Privs, who is not subscribed to bug_four, cannot access or set the
attachments attributes:

    >>> login("no-priv@canonical.com")

    >>> attachment.title
    Traceback (most recent call last):
    ...
    zope.security.interfaces.Unauthorized: (..., 'title',...
    >>> attachment.title = "Better Title"
    Traceback (most recent call last):
    ...
    zope.security.interfaces.Unauthorized: (..., 'title',...

Of course, anonymous is also not allowed to access or set them:

    >>> login(ANONYMOUS)
    >>> attachment.title
    Traceback (most recent call last):
    ...
    zope.security.interfaces.Unauthorized: (..., 'title',...
    >>> attachment.title = "Some info."
    Traceback (most recent call last):
    ...
    zope.security.interfaces.Unauthorized: (..., 'title',...

Sample Person is explicitly subscribed, so they can access the attributes:

    >>> login("test@canonical.com")
    >>> print(attachment.title)
    Even Better Title


Let's make the bug public again:

    >>> bug_four.setPrivate(False, getUtility(ILaunchBag).user)
    True


Search for attachments
----------------------

We can search for attachment of a specific types:

    >>> from lp.bugs.interfaces.bugattachment import BugAttachmentType
    >>> from lp.bugs.interfaces.bugtask import IBugTaskSet
    >>> from lp.bugs.interfaces.bugtasksearch import BugTaskSearchParams
    >>> bugtaskset = getUtility(IBugTaskSet)
    >>> attachmenttype = BugAttachmentType.UNSPECIFIED
    >>> params = BugTaskSearchParams(attachmenttype=attachmenttype, user=None)
    >>> bugtasks = bugtaskset.search(params)
    >>> bugs = set([bugtask.bug for bugtask in bugtasks])
    >>> bugs = list(bugs)
    >>> len(bugs)
    1
    >>> bugs[0].id
    4

    >>> from lp.services.searchbuilder import any
    >>> attachmenttype = any(*BugAttachmentType.items)
    >>> params = BugTaskSearchParams(attachmenttype=attachmenttype, user=None)
    >>> bugtasks = bugtaskset.search(params)
    >>> bugs = set([bugtask.bug for bugtask in bugtasks])
    >>> bugs = list(bugs)
    >>> len(bugs)
    1
    >>> bugs[0].id
    4

There are no patches attached to any bugs:

    >>> attachmenttype = BugAttachmentType.PATCH
    >>> params = BugTaskSearchParams(attachmenttype=attachmenttype, user=None)
    >>> bugtasks = bugtaskset.search(params)
    >>> bugs = set([bugtask.bug for bugtask in bugtasks])
    >>> bugs = list(bugs)
    >>> len(bugs)
    0

Let's make our attachment a patch and search again:

    >>> from lp.services.database.sqlbase import flush_database_updates
    >>> login("foo.bar@canonical.com")
    >>> attachment.type = BugAttachmentType.PATCH
    >>> flush_database_updates()
    >>> attachmenttype = BugAttachmentType.PATCH
    >>> params = BugTaskSearchParams(attachmenttype=attachmenttype, user=None)
    >>> bugtasks = bugtaskset.search(params)
    >>> bugs = set([bugtask.bug for bugtask in bugtasks])
    >>> bugs = list(bugs)
    >>> len(bugs)
    1
    >>> bugs[0].id
    4

An easy way to determine whether an attachment is a patch is to read its
`is_patch` attribute.

    >>> attachment.type = BugAttachmentType.PATCH
    >>> attachment.is_patch
    True

    >>> attachment.type = BugAttachmentType.UNSPECIFIED
    >>> attachment.is_patch
    False


Deleting attachments
--------------------

It's also possible to delete attachments.

    >>> data = BytesIO(filecontent.getvalue())
    >>> bug_two = getUtility(IBugSet).get(2)
    >>> attachment = bug_two.addAttachment(
    ...     owner=foobar,
    ...     data=data,
    ...     filename="foo.baz",
    ...     url=None,
    ...     description="Attachment to be deleted",
    ...     comment="a string comment",
    ...     is_patch=False,
    ... )
    >>> for attachment in bug_two.attachments:
    ...     print(attachment.title)
    ...
    Attachment to be deleted

    >>> libraryfile = attachment.libraryfile
    >>> libraryfile.deleted
    False
    >>> attachment.removeFromBug(user=foobar)
    >>> bug_two.attachments.count()
    0

The libraryfile of this bug attachment is marked as "deleted".

    >>> libraryfile.deleted
    True

Deleting an attachment causes a notification to be sent. It's worth
noting that the notification still includes the URL to the attachment.

    >>> latest_notification = (
    ...     IStore(BugNotification)
    ...     .find(BugNotification)
    ...     .order_by(BugNotification.id)
    ...     .last()
    ... )
    >>> latest_notification.is_comment
    False
    >>> print(latest_notification.message.text_contents)
    ** Attachment removed: "Attachment to be deleted"
       http://.../foo.baz


Bugs with patches
-----------------

A bug that has patch attachments associated with it has its `has_patches`
property returning True.

    >>> bug_two.attachments.count()
    0
    >>> attachment = bug_two.addAttachment(
    ...     owner=foobar,
    ...     data=BytesIO(filecontent.getvalue()),
    ...     filename="foo.baz",
    ...     url=None,
    ...     description="A non-patch attachment",
    ...     comment="a string comment",
    ...     is_patch=False,
    ... )
    >>> bug_two.attachments.count()
    1
    >>> bug_two.has_patches
    False
    >>> attachment = bug_two.addAttachment(
    ...     owner=foobar,
    ...     data=BytesIO(filecontent.getvalue()),
    ...     filename="foo.baz",
    ...     url=None,
    ...     description="A patch attachment",
    ...     comment="a string comment",
    ...     is_patch=True,
    ... )
    >>> bug_two.attachments.count()
    2
    >>> transaction.commit()
    >>> bug_two = getUtility(IBugSet).get(2)
    >>> bug_two.has_patches
    True


Linking existing LibraryFileAliases as attachments
--------------------------------------------------

It's possible to link an existing LibraryFileAliases to a bug as an
attachment by calling the bug's linkAttachment() method. Please note
that this method must not be used to reference the same LibraryFileAlias
record more than once. Doing this could cause inconsistencies between
LibraryFileAlias.restricted and Bug.private. See also the section
"Adding bug attachments to private bugs" below.


    >>> from lp.services.librarian.interfaces import ILibraryFileAliasSet

    >>> file_content = b"Hello, world"
    >>> content_type = "text/plain"
    >>> file_alias = getUtility(ILibraryFileAliasSet).create(
    ...     name="foobar",
    ...     size=len(file_content),
    ...     file=BytesIO(file_content),
    ...     contentType=content_type,
    ... )
    >>> transaction.commit()

    >>> bug = factory.makeBug()
    >>> bug.linkAttachment(
    ...     owner=bug.owner,
    ...     file_alias=file_alias,
    ...     url=None,
    ...     comment="Some attachment",
    ... )
    <BugAttachment ...>

    >>> bug.attachments.count()
    1
    >>> attachment = bug.attachments[0]
    >>> print(attachment.title)
    foobar

The attachment will have a type of BugAttachmentType.UNSPECIFIED, since
we didn't specify that it was a patch.

    >>> print(attachment.type.title)
    Unspecified

We can specify that the attachment is a patch and give it a more
meaningful description.

    >>> file_alias = getUtility(ILibraryFileAliasSet).create(
    ...     name="anotherfoobar",
    ...     size=len(file_content),
    ...     file=BytesIO(file_content),
    ...     contentType=content_type,
    ... )
    >>> transaction.commit()

    >>> bug.linkAttachment(
    ...     owner=bug.owner,
    ...     file_alias=file_alias,
    ...     url=None,
    ...     comment="Some attachment",
    ...     is_patch=True,
    ...     description="An attachment of some sort",
    ... )
    <BugAttachment ...>

    >>> bug.attachments.count()
    2
    >>> attachment = bug.attachments[1]
    >>> print(attachment.title)
    An attachment of some sort

    >>> print(attachment.type.title)
    Patch


Attachments without library files
---------------------------------

It can happen that the LibraryFileContent record of a bug attachment is
deleted, for example. because an admin deleted a privacy sensitive file.
These attachments are not included in Bug.attachments. Our test bug has
at present two attachments.

    >>> for attachment in bug.attachments:
    ...     print(attachment.title)
    ...
    foobar
    An attachment of some sort

If we remove the content record from one attachment, it is no longer
returned by Bug.attachments.

    >>> from zope.security.proxy import removeSecurityProxy
    >>> removeSecurityProxy(attachment.libraryfile).content = None
    >>> for attachment in bug.attachments:
    ...     print(attachment.title)
    ...
    foobar


Adding bug attachments to private bugs
--------------------------------------

If an attachment is added to a private bug, the "restricted" flag of
its Librarian file is set.

    >>> from lp.app.enums import InformationType
    >>> private_bug_owner = factory.makePerson()
    >>> ignored = login_person(private_bug_owner)
    >>> private_bug = factory.makeBug(
    ...     information_type=InformationType.USERDATA, owner=private_bug_owner
    ... )
    >>> private_attachment = private_bug.addAttachment(
    ...     owner=private_bug_owner,
    ...     data=b"secret",
    ...     filename="baz.txt",
    ...     url=None,
    ...     comment="Some attachment",
    ... )
    >>> private_attachment.libraryfile.restricted
    True

But the "restricted" flag of Librarian files belonging to bug attachments
of public bugs is not set.

    >>> attachment.libraryfile.restricted
    False

If a private bug becomes public, the restricted flag of the related
Librarian files are no longer set.

    >>> changed = private_bug.setPrivate(False, private_bug.owner)
    >>> private_attachment.libraryfile.restricted
    False

Similarly, if a public bug becomes private, the "restricted" flag of
its Librarian files are set.

    >>> changed = bug.setPrivate(True, bug.owner)
    >>> attachment.libraryfile.restricted
    True


Miscellaneous
-------------

The method IBugAttachment.getFileByName() returns the Librarian file.

    >>> print(attachment.libraryfile.filename)
    foobar
    >>> attachment.getFileByName("foobar")
    <LibraryFileAlias object>

A NotFoundError is raised if the file name passed to getFileByName()
does not match the file name of the Librarian file.

    >>> attachment.getFileByName("nonsense")
    Traceback (most recent call last):
    ...
    lp.app.errors.NotFoundError: ...'nonsense'
