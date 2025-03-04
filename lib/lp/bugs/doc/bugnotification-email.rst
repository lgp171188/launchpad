Bug Notification Email
----------------------

This document describes the internal workings of how bug notification
emails are generated and how said emails are formatted. It does not
cover the various rules and semantics surrounding the notifications
themselves; for that, see bugnotifications.rst.

The reference spec associated with this document is available on the
Launchpad development wiki:

    https://web.archive.org/ \
        web/20130205083045/https://dev.launchpad.net \
        /Bugs/Specs/FormattingBugNotifications

You need to be logged in to edit bugs in Malone, so let's get started:

    >>> from lp.testing import login
    >>> login("test@canonical.com")

To avoid having one gargantuan super function that formats any kind of
object it gets passed, the formatting logic has been cut into two
pieces: get_bug_changes and generate_bug_add_email.

    >>> from lp.bugs.adapters.bugchange import get_bug_changes
    >>> from lp.bugs.mail.newbug import generate_bug_add_email

Let's demonstrate what the bugmails will look like, by going through the
various events that can happen that would cause a notification to be
sent. We'll start by importing some things we'll need for the examples
that follow:

    >>> from zope.component import getUtility
    >>> from lp.services.identity.interfaces.emailaddress import (
    ...     IEmailAddressSet,
    ... )
    >>> from lp.bugs.adapters.bugdelta import BugDelta
    >>> from lp.bugs.interfaces.bug import (
    ...     IBugDelta,
    ...     IBugSet,
    ... )
    >>> from lp.app.enums import InformationType
    >>> from lp.registry.interfaces.person import IPersonSet


Filing a bug
============

generate_bug_add_email accepts one argument: the IBug that was just
added. With that, it generates an appropriately-formatted notification
message, and returns it as a (subject, body) tuple.

So, let's pretend that we filed bug 4 just now:

    >>> bug_four = getUtility(IBugSet).get(4)
    >>> bug_four.tags = []

Let's take a look at what the notification email looks like:

    >>> subject, body = generate_bug_add_email(bug_four)
    >>> print(subject)
    [Bug 4] [NEW] Reflow problems with complex page layouts

    >>> print(body)
    Public bug reported:
    <BLANKLINE>
    Malone pages that use more complex layouts with portlets and fancy CSS
    are sometimes not getting properly reflowed after rendering.
    <BLANKLINE>
    ** Affects: firefox
         Importance: Medium
             Status: New

(In reality, the importance of a newly-reported bug would not have been
decided yet, so it would appear as Undecided.)

If the filed bug would have tags, these are included in the notification
as well.

    >>> bug_four.tags = ["foo", "bar"]

    >>> subject, body = generate_bug_add_email(bug_four)
    >>> print(subject)
    [Bug 4] [NEW] Reflow problems with complex page layouts

    >>> print(body)
    Public bug reported:
    <BLANKLINE>
    Malone pages that use more complex layouts with portlets and fancy CSS
    are sometimes not getting properly reflowed after rendering.
    <BLANKLINE>
    ** Affects: firefox
         Importance: Medium
             Status: New
    <BLANKLINE>
    ** Tags: bar foo

New security related bugs are sent with a prominent warning:

    >>> changed = bug_four.transitionToInformationType(
    ...     InformationType.PUBLICSECURITY, getUtility(ILaunchBag).user
    ... )

    >>> subject, body = generate_bug_add_email(bug_four)
    >>> print(subject)
    [Bug 4] [NEW] Reflow problems with complex page layouts

    >>> print(body)
    *** This bug is a security vulnerability ***
    <BLANKLINE>
    Public security bug reported:
    <BLANKLINE>
    ...

Security related bugs can be embargoed:

    >>> bug_four.transitionToInformationType(
    ...     InformationType.PRIVATESECURITY, getUtility(ILaunchBag).user
    ... )
    True

    >>> subject, body = generate_bug_add_email(bug_four)
    >>> print(body)
    *** This bug is a security vulnerability ***
    <BLANKLINE>
    Private security bug reported:
    <BLANKLINE>
    ...


Editing a bug
=============

get_bug_changes() accepts an object that provides IBugDelta, and
generates IBugChange objects that describe the changes to the bug.

    >>> sample_person = getUtility(IPersonSet).get(12)
    >>> edited_bug = getUtility(IBugSet).get(2)

    >>> old_title = edited_bug.title
    >>> edited_bug.title = "the new title"
    >>> old_description = edited_bug.description
    >>> edited_bug.description = (
    ...     "The Trash folder seems to have significant problems! At the"
    ...     " moment, dragging an item to the Trash results in immediate"
    ...     " deletion. The item does not appear in the Trash, it is just"
    ...     " deleted from my hard disk. There is no undo or ability to"
    ...     " recover the deleted file. Help!"
    ... )

    >>> bug_delta = BugDelta(
    ...     bug=edited_bug,
    ...     bugurl="http://www.example.com/bugs/2",
    ...     user=sample_person,
    ...     title={"new": edited_bug.title, "old": old_title},
    ...     description={
    ...         "new": edited_bug.description,
    ...         "old": old_description,
    ...     },
    ... )
    >>> IBugDelta.providedBy(bug_delta)
    True

    >>> from lp.bugs.interfaces.bugchange import IBugChange
    >>> changes = get_bug_changes(bug_delta)
    >>> for change in changes:
    ...     IBugChange.providedBy(change)
    ...
    True
    True

    >>> for change in get_bug_changes(bug_delta):
    ...     notification = change.getBugNotification()
    ...     print(notification["text"])  # doctest: -NORMALIZE_WHITESPACE
    ...     print("-----------------------------")
    ...
    ** Summary changed:
    <BLANKLINE>
    - Blackhole Trash folder
    + the new title
    -----------------------------
    ** Description changed:
    <BLANKLINE>
      The Trash folder seems to have significant problems! At the moment,
    - dragging an item to the trash results in immediate deletion. The item
    + dragging an item to the Trash results in immediate deletion. The item
      does not appear in the Trash, it is just deleted from my hard disk.
      There is no undo or ability to recover the deleted file. Help!
    -----------------------------

Another edit, this time a long description, showing that the description
is wrapped properly:

    >>> old_description = edited_bug.description
    >>> edited_bug.description = "".join(
    ...     [
    ...         "A new description that is quite long. ",
    ...         "But the nice thing is that the edit notification email ",
    ...         "generator knows how to indent and wrap descriptions, so ",
    ...         "this will appear quite nice in the actual email that gets ",
    ...         "sent.",
    ...         "\n",
    ...         "\n",
    ...         "It's also smart enough to preserve whitespace, finally!",
    ...     ]
    ... )

    >>> bug_delta = BugDelta(
    ...     bug=edited_bug,
    ...     bugurl="http://www.example.com/bugs/2",
    ...     user=sample_person,
    ...     description={
    ...         "new": edited_bug.description,
    ...         "old": old_description,
    ...     },
    ... )
    >>> for change in get_bug_changes(bug_delta):  # noqa
    ...     notification = change.getBugNotification()
    ...     print(notification["text"])  # doctest: -NORMALIZE_WHITESPACE
    ...     print("-----------------------------")
    ...
    ** Description changed:
    <BLANKLINE>
    - The Trash folder seems to have significant problems! At the moment,
    - dragging an item to the Trash results in immediate deletion. The item
    - does not appear in the Trash, it is just deleted from my hard disk.
    - There is no undo or ability to recover the deleted file. Help!
    + A new description that is quite long. But the nice thing is that the
    + edit notification email generator knows how to indent and wrap
    + descriptions, so this will appear quite nice in the actual email that
    + gets sent.
    + 
    + It's also smart enough to preserve whitespace, finally!
    -----------------------------

(Note that there's a blank line in the email that contains whitespace.  You
may see a lint warning for that.)

Let's make a bug security-related, and private (we need to switch
logins to a user that is explicitly subscribed to this bug):

    >>> login("steve.alexander@ubuntulinux.com")

    >>> edited_bug = getUtility(IBugSet).get(6)
    >>> edited_bug.transitionToInformationType(
    ...     InformationType.PRIVATESECURITY, getUtility(ILaunchBag).user
    ... )
    True
    >>> bug_delta = BugDelta(
    ...     bug=edited_bug,
    ...     bugurl="http://www.example.com/bugs/6",
    ...     user=sample_person,
    ...     information_type={
    ...         "old": InformationType.PUBLIC,
    ...         "new": InformationType.PRIVATESECURITY,
    ...     },
    ... )

    >>> for change in get_bug_changes(bug_delta):
    ...     notification = change.getBugNotification()
    ...     text_representation = notification["text"]
    ...     print(text_representation)  # doctest: -NORMALIZE_WHITESPACE
    ...     print("-----------------------------")
    ...
    ** Information type changed from Public to Private Security
    -----------------------------

Now we set the bug back to public and check if the email sent changed as well.

    >>> changed = edited_bug.transitionToInformationType(
    ...     InformationType.PUBLIC, getUtility(ILaunchBag).user
    ... )
    >>> bug_delta = BugDelta(
    ...     bug=edited_bug,
    ...     bugurl="http://www.example.com/bugs/6",
    ...     user=sample_person,
    ...     private={"old": True, "new": edited_bug.private},
    ...     information_type={
    ...         "old": InformationType.PRIVATESECURITY,
    ...         "new": InformationType.PUBLIC,
    ...     },
    ... )
    >>> for change in get_bug_changes(bug_delta):
    ...     notification = change.getBugNotification()
    ...     print(notification["text"])  # doctest: -NORMALIZE_WHITESPACE
    ...     print("-----------------------------")
    ...
    ** Information type changed from Private Security to Public
    -----------------------------

Let's add some tags to a bug:

    >>> old_tags = []
    >>> edited_bug.tags = ["foo", "bar"]
    >>> bug_delta = BugDelta(
    ...     bug=edited_bug,
    ...     bugurl="http://www.example.com/bugs/6",
    ...     user=sample_person,
    ...     tags={"old": old_tags, "new": edited_bug.tags},
    ... )
    >>> for change in get_bug_changes(bug_delta):
    ...     notification = change.getBugNotification()
    ...     print(notification["text"])  # doctest: -NORMALIZE_WHITESPACE
    ...     print("-----------------------------")
    ...
    ** Tags added: bar foo
    -----------------------------

If we change one tag, it's basically removing one and adding another:

    >>> old_tags = edited_bug.tags
    >>> edited_bug.tags = ["foo", "baz"]
    >>> bug_delta = BugDelta(
    ...     bug=edited_bug,
    ...     bugurl="http://www.example.com/bugs/2",
    ...     user=sample_person,
    ...     tags={"old": old_tags, "new": edited_bug.tags},
    ... )
    >>> for change in get_bug_changes(bug_delta):
    ...     notification = change.getBugNotification()
    ...     print(notification["text"])  # doctest: -NORMALIZE_WHITESPACE
    ...     print("-----------------------------")
    ...
    ** Tags removed: bar
    ** Tags added: baz
    -----------------------------


Editing a bug task
==================

As you might expect, get_bug_changes handles generating the text
representations of the changes when a bug task is edited.

We use a BugTaskDelta to represent changes to a BugTask.

    >>> from lp.testing import verifyObject
    >>> from lp.bugs.interfaces.bugtask import (
    ...     BugTaskStatus,
    ...     IBugTaskDelta,
    ...     IBugTaskSet,
    ... )
    >>> from lp.bugs.model.bugtask import BugTaskDelta
    >>> example_bug_task = factory.makeBugTask()
    >>> example_delta = BugTaskDelta(example_bug_task)
    >>> verifyObject(IBugTaskDelta, example_delta)
    True

    >>> edited_bugtask = getUtility(IBugTaskSet).get(15)
    >>> edited_bugtask.transitionToStatus(
    ...     BugTaskStatus.CONFIRMED, getUtility(ILaunchBag).user
    ... )
    >>> edited_bugtask.transitionToAssignee(sample_person)
    >>> bugtask_delta = BugTaskDelta(
    ...     bugtask=edited_bugtask,
    ...     status={"old": BugTaskStatus.NEW, "new": edited_bugtask.status},
    ...     assignee={"old": None, "new": edited_bugtask.assignee},
    ... )
    >>> bug_delta = BugDelta(
    ...     bug=edited_bug,
    ...     bugurl="http://www.example.com/bugs/6",
    ...     user=sample_person,
    ...     bugtask_deltas=bugtask_delta,
    ... )
    >>> for change in get_bug_changes(bug_delta):
    ...     notification = change.getBugNotification()
    ...     print(notification["text"])  # doctest: -NORMALIZE_WHITESPACE
    ...     print("-----------------------------")
    ...
    ** Changed in: firefox
           Status: New => Confirmed
    -----------------------------
    ** Changed in: firefox
         Assignee: (unassigned) => Sample Person (name12)
    -----------------------------

Let's take a look at how it looks like when a distribution task is
edited:

    >>> debian_bugtask = getUtility(IBugTaskSet).get(5)
    >>> print(debian_bugtask.bugtargetname)
    mozilla-firefox (Debian)

    >>> debian_bugtask.transitionToAssignee(None)
    >>> bugtask_delta = BugTaskDelta(
    ...     bugtask=debian_bugtask,
    ...     assignee={"old": sample_person, "new": None},
    ... )
    >>> bug_delta = BugDelta(
    ...     bug=edited_bug,
    ...     bugurl="http://www.example.com/bugs/6",
    ...     user=sample_person,
    ...     bugtask_deltas=bugtask_delta,
    ... )
    >>> for change in get_bug_changes(bug_delta):
    ...     notification = change.getBugNotification()
    ...     print(notification["text"])  # doctest: -NORMALIZE_WHITESPACE
    ...     print("-----------------------------")
    ...
    ** Changed in: mozilla-firefox (Debian)
         Assignee: Sample Person (name12) => (unassigned)
    -----------------------------


Adding attachments
==================

Adding an attachment will generate a notification that looks as follows:

    >>> attachment = factory.makeBugAttachment(
    ...     description="A screenshot of the problem",
    ...     filename="screenshot.png",
    ... )
    >>> bug_delta = BugDelta(
    ...     bug=edited_bug,
    ...     bugurl="http://www.example.com/bugs/6",
    ...     user=sample_person,
    ...     attachment={"new": attachment, "old": None},
    ... )
    >>> for change in get_bug_changes(bug_delta):
    ...     notification = change.getBugNotification()
    ...     print(notification["text"])  # doctest: -NORMALIZE_WHITESPACE
    ...     print("-----------------------------")
    ... # noqa
    ...
    ** Attachment added: "A screenshot of the problem"
       http://bugs.launchpad.test/bugs/.../+attachment/.../+files/screenshot.png
    -----------------------------

Removing an attachment generates a notification, too.

    >>> bug_delta = BugDelta(
    ...     bug=edited_bug,
    ...     bugurl="http://www.example.com/bugs/6",
    ...     user=sample_person,
    ...     attachment={"old": attachment, "new": None},
    ... )
    >>> for change in get_bug_changes(bug_delta):
    ...     notification = change.getBugNotification()
    ...     print(notification["text"])  # doctest: -NORMALIZE_WHITESPACE
    ...     print("-----------------------------")
    ... # noqa
    ...
    ** Attachment removed: "A screenshot of the problem"
       http://bugs.launchpad.test/bugs/.../+attachment/.../+files/screenshot.png
    -----------------------------

Adding an attachment and marking it as a patch generates a different
notification.

    >>> attachment = factory.makeBugAttachment(
    ...     description="A new icon for the application",
    ...     filename="new-icon.png",
    ...     is_patch=True,
    ... )
    >>> bug_delta = BugDelta(
    ...     bug=edited_bug,
    ...     bugurl="http://www.example.com/bugs/6",
    ...     user=sample_person,
    ...     attachment={"new": attachment, "old": None},
    ... )
    >>> for change in get_bug_changes(bug_delta):
    ...     notification = change.getBugNotification()
    ...     print(notification["text"])  # doctest: -NORMALIZE_WHITESPACE
    ...     print("-----------------------------")
    ...
    ** Patch added: "A new icon for the application"
       http://bugs.launchpad.test/bugs/.../+attachment/.../+files/new-icon.png
    -----------------------------

Removing a patch also generates a different notification.

    >>> bug_delta = BugDelta(
    ...     bug=edited_bug,
    ...     bugurl="http://www.example.com/bugs/6",
    ...     user=sample_person,
    ...     attachment={"old": attachment, "new": None},
    ... )
    >>> for change in get_bug_changes(bug_delta):
    ...     notification = change.getBugNotification()
    ...     print(notification["text"])  # doctest: -NORMALIZE_WHITESPACE
    ...     print("-----------------------------")
    ...
    ** Patch removed: "A new icon for the application"
       http://bugs.launchpad.test/bugs/.../+attachment/.../+files/new-icon.png
    -----------------------------


Generation of From: and Reply-To: addresses
===========================================

The Reply-To: and From: addresses used to send email are generated in a
pair of handy functions defined in mailnotification.py:

    >>> from lp.bugs.mail.bugnotificationbuilder import (
    ...     get_bugmail_from_address,
    ...     get_bugmail_replyto_address,
    ... )

The Reply-To address generation is straightforward:

    >>> print(get_bugmail_replyto_address(bug_four))
    Bug 4 <4@bugs.launchpad.net>

In order to send DMARC-compliant bug notifications, the From address generator
is also quite straightforward and uses the bug's email address for the From
address, while adjusting the friendly display name field.

This applies for all users.  For example, Stuart has four email addresses:

    >>> stub = getUtility(IPersonSet).getByName("stub")
    >>> for email in getUtility(IEmailAddressSet).getByPerson(stub):
    ...     print(email.email, email.status.name)
    ...
    stuart.bishop@canonical.com PREFERRED
    stuart@stuartbishop.net VALIDATED
    stub@fastmail.fm NEW
    zen@shangri-la.dropbear.id.au OLD

However, because of DMARC compliance, we only use the bug's email address in
the From field, with Stuart's name in the 'display name' portion of the
email address:

    >>> get_bugmail_from_address(stub, bug_four)
    'Stuart Bishop <4@bugs.launchpad.net>'

This also happens for users with hidden addresses:

    >>> private_person = factory.makePerson(
    ...     email="hidden@example.com", displayname="Ford Prefect"
    ... )
    >>> private_person.hide_email_addresses = True
    >>> get_bugmail_from_address(private_person, bug_four)
    'Ford Prefect <4@bugs.launchpad.net>'

It also behaves the same for users with no verified email addresses:

    >>> mpo = getUtility(IPersonSet).getByName("mpo")
    >>> get_bugmail_from_address(mpo, bug_four)
    '=?utf-8?b?TWF0dGkgUMO2bGzDpA==?= <4@bugs.launchpad.net>'

This also happens for the team janitor:

    >>> janitor = getUtility(IPersonSet).getByName("team-membership-janitor")
    >>> get_bugmail_from_address(janitor, bug_four)
    'Team Membership Janitor <4@bugs.launchpad.net>'

And it also applies for the Launchpad Janitor:

    >>> from lp.app.interfaces.launchpad import ILaunchpadCelebrities
    >>> lp_janitor = getUtility(ILaunchpadCelebrities).janitor
    >>> get_bugmail_from_address(lp_janitor, bug_four)
    'Launchpad Bug Tracker <4@bugs.launchpad.net>'

Construction of bug notification emails
---------------------------------------

mailnotification.py contains a class, BugNotificationBuilder, which is
used to construct bug notification emails.

    >>> from lp.bugs.mail.bugnotificationbuilder import BugNotificationBuilder

When instantiatiated it derives a list of common unchanging headers from
the bug so that they are not calculated for every recipient.

    >>> bug_four_notification_builder = BugNotificationBuilder(
    ...     bug_four, private_person
    ... )
    >>> for header in bug_four_notification_builder.common_headers:
    ...     print(": ".join(header))
    ...
    Reply-To: Bug 4 <4@bugs.launchpad.net>
    Sender: bounces@canonical.com
    X-Launchpad-Notification-Type: bug
    X-Launchpad-Bug: product=firefox; ...; assignee=None;
    X-Launchpad-Bug-Tags: bar foo
    X-Launchpad-Bug-Information-Type: Private Security
    X-Launchpad-Bug-Private: yes
    X-Launchpad-Bug-Security-Vulnerability: yes
    X-Launchpad-Bug-Commenters: name12
    X-Launchpad-Bug-Reporter: Sample Person (name12)
    X-Launchpad-Bug-Modifier: Ford Prefect (person-name...)

The build() method of a builder accepts a number of parameters and returns
an instance of email.mime.text.MIMEText. The most basic invocation of this
method requires a from address, a to person, a body, a subject and a sending
date for the mail.

    >>> from datetime import datetime
    >>> from dateutil import tz

    >>> from_address = get_bugmail_from_address(lp_janitor, bug_four)
    >>> to_person = getUtility(IPersonSet).getByEmail("foo.bar@canonical.com")
    >>> sending_date = datetime(
    ...     2008, 5, 20, 11, 5, 47, tzinfo=tz.gettz("Europe/Prague")
    ... )

    >>> notification_email = bug_four_notification_builder.build(
    ...     from_address,
    ...     to_person,
    ...     "A test body.",
    ...     "A test subject.",
    ...     sending_date,
    ... )

The fields of the generated notification email will be set according to
the parameters that were used to instantiate BugNotificationBuilder and
passed to <builder>.build().

    >>> print(notification_email["From"])
    Launchpad Bug Tracker <4@bugs.launchpad.net>

    >>> print(notification_email["To"])
    foo.bar@canonical.com

    >>> print(notification_email["Subject"])
    [Bug 4] A test subject.

    >>> print(notification_email["Date"])
    Tue, 20 May 2008 09:05:47 -0000

    >>> print(notification_email.get_payload())
    A test body.

The <builder>.build() method also accepts parameters for rationale,
references and message_id.

    >>> notification_email = bug_four_notification_builder.build(
    ...     from_address,
    ...     to_person,
    ...     "A test body.",
    ...     "A test subject.",
    ...     sending_date,
    ...     rationale="Because-I-said-so",
    ...     references=["<12345@launchpad.net>"],
    ...     message_id="<67890@launchpad.net>",
    ... )

The X-Launchpad-Message-Rationale header is set from the rationale
parameter.

    >>> print(notification_email["X-Launchpad-Message-Rationale"])
    Because-I-said-so

The X-Launchpad-Message-For header is set from the to_person (since this
notification is not for a team).

    >>> print(notification_email["X-Launchpad-Message-For"])
    name16

The references parameter sets the References header of the email.

    >>> print(notification_email["References"])
    <12345@launchpad.net>

And the message_id parameter is used to set the Message-Id header. It
will be auto-generated if it is not supplied.

    >>> print(notification_email["Message-Id"])
    <67890@launchpad.net>

The message subject will always have [Bug <bug_id>] prepended to it.

    >>> notification_email = bug_four_notification_builder.build(
    ...     from_address,
    ...     to_person,
    ...     "A test body.",
    ...     "Yet another message",
    ...     sending_date,
    ... )

    >>> print(notification_email["Subject"])
    [Bug 4] Yet another message

If the subject passed is None the email subject will be set to [Bug
<bug_id>].

    >>> notification_email = bug_four_notification_builder.build(
    ...     from_address, to_person, "A test body.", None, sending_date
    ... )

    >>> print(notification_email["Subject"])
    [Bug 4]
