Launchpad Bugs email interface
==============================

Launchpad's bugtracker has an email interface, with which you may report new
bugs, add comments, and change the details of existing bug reports. Commands
can be interleaved within a comment, so to distinguish them from the comment,
they must be indented with at least one space or tab character.

Submit a new bug
----------------

To report a bug, you send an OpenPGP-signed email message to
new@bugs.launchpad-domain. You must have registered your key in
Launchpad as well. The subject of the email will be used as the summary
of the bug, and the body will be used as the description. In the body of
the email you have tell on what you file a bug, either a product or a
distribution. You do so by issuing an 'affects' command. The simplest
case is either:

    affects $product_name

to file a bug on a product, or:

    affects $distribution_name

to file a bug on a distribution. And if you want to file a bug on a
specific source package in a distribution:

    affects $distribution_name/$sourcepackage_name

You can also file bugs on specific distribution series:

    affects $distribution_name/$series_name
    affects $distribution_name/$series_name/$sourcepackage_name

But if you want you can use any of the available commands as well.

Let's take an example where we file a bug on Firefox:

    >>> submit_mail = b"""From: Foo Bar <foo.bar@canonical.com>
    ... To: new@bugs.launchpad.ubuntu.com
    ... Date: Fri Jun 17 10:20:23 BST 2005
    ... Subject: A bug in Firefox
    ...
    ... There is a bug in Firefox.
    ...
    ...  affects firefox"""

Now, in order to really submit the bug, this email would have to be PGP
signed, so that the system can verify the sender. But to avoid having
to sign each email, we'll create a class which fakes a signed email:

    >>> from lp.testing import sampledata

    >>> import email.message
    >>> class MockSignedMessage(email.message.Message):
    ...     def __init__(self, *args, **kws):
    ...         email.message.Message.__init__(self, *args, **kws)
    ...         self.signature = "fake"
    ...
    ...     @property
    ...     def signedMessage(self):
    ...         return self
    ...

And since we'll pass the email directly to the correct handler,
we'll have to authenticate the user manually:

    >>> from lp.testing import login
    >>> login("foo.bar@canonical.com")

Now if we pass the message to the Malone handler, we can see that the
bug got submitted correctly:

    >>> import email
    >>> from lp.bugs.mail.handler import MaloneHandler
    >>> handler = MaloneHandler()
    >>> def construct_email(raw_mail):
    ...     msg = email.message_from_bytes(raw_mail, _class=MockSignedMessage)
    ...     if "Message-Id" not in msg:
    ...         msg["Message-Id"] = factory.makeUniqueRFC822MsgId()
    ...     return msg
    ...

    >>> def process_email(raw_mail):
    ...     msg = construct_email(raw_mail)
    ...     handler.process(
    ...         msg,
    ...         msg["To"],
    ...     )
    ...

    >>> process_email(submit_mail)

    >>> from lp.bugs.interfaces.bug import IBugSet
    >>> from lp.services.mail import stub
    >>> bugset = getUtility(IBugSet)
    >>> from lp.bugs.model.bugnotification import BugNotification
    >>> from lp.services.database.interfaces import IStore
    >>> def get_latest_added_bug():
    ...     latest_notification = (
    ...         IStore(BugNotification)
    ...         .find(BugNotification)
    ...         .order_by(BugNotification.id)
    ...         .last()
    ...     )
    ...     return latest_notification.bug
    ...
    >>> bug = get_latest_added_bug()

    >>> print(bug.title)
    A bug in Firefox
    >>> print(bug.description)
    There is a bug in Firefox.
    <BLANKLINE>
     affects firefox

Also, an upstream bug task was added to it:

    >>> len(bug.bugtasks)
    1
    >>> upstream_task = bug.bugtasks[0]
    >>> print(upstream_task.product.name)
    firefox

And the entire body of the email was added as a comment:

    >>> bug.messages.count()
    1
    >>> comment = bug.messages[0]
    >>> print(comment.title)
    A bug in Firefox
    >>> print(comment.text_contents)
    There is a bug in Firefox.
    <BLANKLINE>
     affects firefox

The owner of the bug was set to the submitter:

    >>> print(bug.owner.displayname)
    Foo Bar

A notification was added:

    >>> bug_notification = (
    ...     IStore(BugNotification)
    ...     .find(BugNotification)
    ...     .order_by(BugNotification.id)
    ...     .last()
    ... )
    >>> print(bug_notification.message.owner.displayname)
    Foo Bar

    >>> bug_notification.message == bug.initial_message
    True

We define a helper to pretty-print the notification recipients:

    >>> def getSubscribers(bug):
    ...     recipients = bug.getBugNotificationRecipients()
    ...     return recipients.getEmails()
    ...

Foo Bar got subscribed to the bug.

    >>> added_bug = bug_notification.bug
    >>> getSubscribers(added_bug)
    ['foo.bar@canonical.com']

If we would file a bug on Ubuntu instead, we would submit a mail like
this:

    >>> login(sampledata.USER_EMAIL)
    >>> submit_mail = b"""From: Sample Person <test@canonical.com>
    ... To: new@bugs.canonical.com
    ... Date: Fri Jun 17 10:20:23 BST 2005
    ... Subject: A bug in Ubuntu's Mozilla package
    ...
    ... There's a bug in Ubuntu.
    ...  affects ubuntu/mozilla-firefox
    ... """
    >>> process_email(submit_mail)
    >>> bug = get_latest_added_bug()

    >>> print(bug.title)
    A bug in Ubuntu's Mozilla package

    >>> distrotask = bug.bugtasks[0]
    >>> print(distrotask.distribution.name)
    ubuntu
    >>> print(distrotask.sourcepackagename.name)
    mozilla-firefox

A notification was added:

    >>> bug_notification = (
    ...     IStore(BugNotification)
    ...     .find(BugNotification)
    ...     .order_by(BugNotification.id)
    ...     .last()
    ... )
    >>> print(bug_notification.message.owner.displayname)
    Sample Person

    >>> bug_notification.message == bug.initial_message
    True

Foo Bar got subscribed to the bug.

    >>> getSubscribers(added_bug)
    ['foo.bar@canonical.com']

It's possible to file a bug on more than product/package at once:

    # Make sane data to play this test.
    >>> from zope.component import getUtility
    >>> from lp.registry.interfaces.distribution import IDistributionSet
    >>> from lp.testing.dbuser import lp_dbuser

    >>> with lp_dbuser():
    ...     debian = getUtility(IDistributionSet).getByName("debian")
    ...     evolution_dsp = debian.getSourcePackage("evolution")
    ...     ignore = factory.makeSourcePackagePublishingHistory(
    ...         distroseries=debian.currentseries,
    ...         sourcepackagename=evolution_dsp.sourcepackagename,
    ...     )
    ...

    >>> submit_mail = b"""From: Sample Person <test@canonical.com>
    ... To: new@bugs.canonical.com
    ... Date: Fri Jun 17 10:20:23 BST 2005
    ... Subject: Affects many packages
    ...
    ... A widespread bug.
    ...  affects debian/evolution
    ...  affects debian/mozilla-firefox
    ...  affects evolution
    ...  affects firefox
    ... """
    >>> process_email(submit_mail)
    >>> bug = get_latest_added_bug()

    >>> print(bug.title)
    Affects many packages

    >>> for bugtask in bug.bugtasks:
    ...     print(bugtask.bugtargetname)
    ...
    evolution
    firefox
    evolution (Debian)
    mozilla-firefox (Debian)

If the subject is folded (i.e spans more than one line), it will be
unfolded before the bug subject is assigned.

    >>> submit_mail = b"""From: Sample Person <test@canonical.com>
    ... To: new@bugs.canonical.com
    ... Date: Fri Jun 17 10:20:43 BST 2005
    ... Subject: A folded
    ...  email subject
    ...
    ...  affects firefox
    ... """
    >>> process_email(submit_mail)
    >>> bug = get_latest_added_bug()

    >>> print(bug.title)
    A folded email subject


Add a comment
-------------

After a bug has been submitted a notification is sent out. The reply-to
address is set to the bug address, $bugid@malone-domain. We can send
emails to this address in order to add new comments to the bug. Note
that we can interleave commands in the comment as well. If the comment
includes commands, the email has to be OpenPGP-signed.

    >>> comment_mail = b"""From: test@canonical.com
    ... To: 1@malone-domain
    ... Date: Fri Jun 17 10:20:23 BST 2005
    ... Message-Id: <yada-yada-test1>
    ... Subject: New comment to bug 1
    ...
    ... Adding a comment via the email system. Let's change the summary
    ... as well:
    ...     summary "Better summary"
    ...
    ... /Sample Person
    ... """

    >>> process_email(comment_mail)
    >>> transaction.commit()

    >>> from lp.services.messages.interfaces.message import IMessageSet
    >>> bug_one = bugset.get(1)
    >>> added_message = getUtility(IMessageSet).get("<yada-yada-test1>")[0]

We use set() here because the DecoratedResultSet used by Bug.messages
doesn't currently support __contains__.

    >>> added_message in set(bug_one.messages)
    True
    >>> print(bug_one.title)
    Better summary

If the message doesn't have a Reference or In-Reply-To header, the
parent will be set to the bug's initial message.

    >>> added_message.parent == bug_one.initial_message
    True


Edit bugs
---------

Sometimes you may want to simply edit a bug, without adding a comment.
For that you can send mails to edit@malone-domain.

    >>> bug_four = bugset.get(4)
    >>> bug_five = bugset.get(5)
    >>> bug_four_comments = bug_four.messages.count()
    >>> bug_five_comments = bug_five.messages.count()
    >>> edit_mail = b"""From: test@canonical.com
    ... To: edit@malone-domain
    ... Date: Fri Jun 17 10:10:23 BST 2005
    ... Subject: Not important
    ...
    ...     bug 4
    ...     summary "Changed summary"
    ...
    ... It won't break if we write some stuff here.
    ...
    ...     bug 5
    ...     summary "Nicer summary"
    ... """

    >>> process_email(edit_mail)
    >>> transaction.commit()

No comments were added to the bugs:

    >>> bug_four.messages.count() == bug_four_comments
    True
    >>> bug_five.messages.count() == bug_five_comments
    True

And the summaries were changed:

    >>> print(bug_four.title)
    Changed summary
    >>> print(bug_five.title)
    Nicer summary

The email handler requires that a bug be specified to be changed. If no
bug is specified, no edits occur and a message is sent to the user telling
them what happened.

    >>> edit_mail = b"""From: test@canonical.com
    ... To: edit@malone-domain
    ... Date: Fri Jun 17 10:10:23 BST 2005
    ... Subject: Not important
    ...
    ...     summary "Even nicer summary"
    ... """

    >>> process_email(edit_mail)
    >>> transaction.commit()

This time, neither bug four or five were updated.

    >>> print(bug_four.title)
    Changed summary
    >>> print(bug_five.title)
    Nicer summary

And the person sending the email has received an error message.

    >>> def print_latest_email():
    ...     transaction.commit()
    ...     if not stub.test_emails:
    ...         raise AssertionError("No emails queued!")
    ...     from_addr, to_addrs, raw_message = stub.test_emails[-1]
    ...     sent_msg = email.message_from_bytes(raw_message)
    ...     error_mail, original_mail = sent_msg.get_payload()
    ...     print("Subject: %s" % sent_msg["Subject"])
    ...     print("To: %s" % ", ".join(to_addrs))
    ...     print()
    ...     print(error_mail.get_payload(decode=True).decode("UTF-8"))
    ...

    >>> print_latest_email()
    Subject: Submit Request Failure
    To: test@canonical.com
    <BLANKLINE>
    ...
    The message you sent included commands to modify a bug,
    but no bug was specified. Please supply a bug before the command
    to modify it.
    <BLANKLINE>
    ...

GPG signing and adding comments
-------------------------------

In order to include commands in the comment, the email has to be GPG
signed. The key used to sign the email has to be associated with the
authenticated person in Launchpad. It happens quite often, though, that
people who haven't registered their key in Launchpad sign their emails
even though the only want to add a comment. These comments should of
course not be rejected just because their key wasn't registered in
Launchpad.

To make a difference between if an email was signed with a key
registered in Launchpad or not, we can look at which interfaces the
currently authenticated principal provides. If the email used for
authentication was unsigned or signed with a key, which isn't
associated with the authenticated Person in Launchpad, the principal
will provide IWeaklyAuthenticatedPrincipal. Let's mark the current
principal with that.

    >>> from lp.services.mail.interfaces import (
    ...     IWeaklyAuthenticatedPrincipal,
    ... )
    >>> from zope.interface import directlyProvides, directlyProvidedBy
    >>> from zope.security.management import queryInteraction

    >>> def simulate_receiving_untrusted_mail():
    ...     participations = queryInteraction().participations
    ...     assert len(participations) == 1
    ...     current_principal = participations[0].principal
    ...     directlyProvides(
    ...         current_principal,
    ...         directlyProvidedBy(current_principal),
    ...         IWeaklyAuthenticatedPrincipal,
    ...     )
    ...
    >>> simulate_receiving_untrusted_mail()

Now we send a comment containing commands.

    >>> comment_mail = b"""From: test@canonical.com
    ... To: 1@malone-domain
    ... Date: Fri Dec 17 10:20:23 BST 2005
    ... Message-Id: <yada-yada-test2>
    ... Subject: Change the summary
    ...
    ... Adding a comment via the email system. Let's change the summary
    ... as well:
    ...     summary "New summary"
    ...
    ... /Sample Person
    ... """
    >>> process_email(comment_mail)
    >>> transaction.commit()

The Malone handler saw that this email was signed, but since
IWeaklyAuthenticatedPrincipal was provided by the current principal, no
changes was made to the bug, and the comment wasn't added.

    >>> added_message = getUtility(IMessageSet).get("<yada-yada-test2>")[0]
    Traceback (most recent call last):
    ...
    lp.app.errors.NotFoundError: ...

    >>> bug_one = bugset.get(1)
    >>> print(bug_one.title)
    Better summary

And an error message was sent to the Sample Person, telling them what's
wrong.

    >>> print_latest_email()
    Subject: Submit Request Failure
    To: test@canonical.com
    <BLANKLINE>
    ...
    The message you sent included commands to modify the bug report, but
    your OpenPGP key isn't imported into Launchpad. Please go to
    http://launchpad.test/~name12/+editpgpkeys to import your key.
    ...

The same will happen if we send the same email without signing it:

    >>> class MockUnsignedMessage(email.message.Message):
    ...     signedMessage = None
    ...     signature = None
    ...
    >>> msg = email.message_from_bytes(
    ...     comment_mail, _class=MockUnsignedMessage
    ... )
    >>> handler.process(
    ...     msg,
    ...     msg["To"],
    ... )
    True
    >>> transaction.commit()

    >>> added_message = getUtility(IMessageSet).get("<yada-yada-test2>")[0]
    Traceback (most recent call last):
    ...
    lp.app.errors.NotFoundError: ...

    >>> bug_one = bugset.get(1)
    >>> print(bug_one.title)
    Better summary


If we don't include any commands in the comment, it will be added
to the bug:

    >>> comment_mail = b"""From: test@canonical.com
    ... To: 1@malone-domain
    ... Date: Fri Dec 17 10:20:23 BST 2005
    ... Message-Id: <yada-yada-test3>
    ... Subject: Change the summary
    ...
    ... Adding a comment via the email system.
    ...
    ... /Sample Person
    ... """
    >>> process_email(comment_mail)
    >>> transaction.commit()

    >>> added_message = getUtility(IMessageSet).get("<yada-yada-test3>")[0]
    >>> bug_one = bugset.get(1)
    >>> added_message in set(bug_one.messages)
    True

In these tests, every time we log in, we're fully trusted again:

    >>> login(sampledata.USER_EMAIL)


Commands
--------

Now let's take a closer look at all the commands that are available for
us to play with. First we define a function to easily submit commands
to edit bug 4:

    >>> def construct_command_email(bug, *commands):
    ...     edit_mail = (
    ...         b"From: test@canonical.com\n"
    ...         b"To: edit@malone-domain\n"
    ...         b"Date: Fri Jun 17 10:10:23 BST 2005\n"
    ...         b"Subject: Not important\n"
    ...         b"\n"
    ...         b" bug %d\n" % bug.id
    ...     )
    ...     edit_mail += b" " + b"\n ".join(
    ...         six.ensure_binary(command) for command in commands
    ...     )
    ...     return construct_email(edit_mail)
    ...

    >>> def submit_command_email(msg):
    ...     handler.process(
    ...         msg,
    ...         msg["To"],
    ...     )
    ...     transaction.commit()
    ...

    >>> def submit_commands(bug, *commands):
    ...     msg = construct_command_email(bug, *commands)
    ...     submit_command_email(msg)
    ...


bug $bugid
~~~~~~~~~~

Switches what bug you want to edit. Example:

    bug 42

If we specify a bug number that doesn't exist, an error message is
returned:

    >>> submit_commands(bug_four, "bug 42")
    >>> print_latest_email()
    Subject: Submit Request Failure
    To: test@canonical.com
    <BLANKLINE>
    ...
    Failing command:
        bug 42
    ...
    There is no such bug in Launchpad: 42
    ...

And if we specify neither 'new' or an integer:

    >>> submit_commands(bug_four, "bug foo")
    >>> print_latest_email()
    Subject: Submit Request Failure
    To: test@canonical.com
    <BLANKLINE>
    ...
    Failing command:
        bug foo
    ...
    The 'bug' command expects either 'new' or a bug id.
    <BLANKLINE>
    For example, to create a new bug:
    <BLANKLINE>
        bug new
    <BLANKLINE>
    To edit or comment on an existing bug:
    <BLANKLINE>
        bug 1
    ...


summary "$summary"
~~~~~~~~~~~~~~~~~~

Changes the summary of the bug. The title has to be enclosed in
quotes. Example:

    >>> submit_commands(bug_four, 'summary "New summary"')
    >>> print(bug_four.title)
    New summary

Whitespace will be preserved in the title:

    >>> submit_commands(bug_four, 'summary "New             summary"')
    >>> print(bug_four.title)  # doctest: -NORMALIZE_WHITESPACE
    New             summary

If we omit the quotes, there will be an error:

    >>> submit_commands(bug_four, "summary New summary")
    >>> print_latest_email()
    Subject: Submit Request Failure
    To: test@canonical.com
    <BLANKLINE>
    ...
    Failing command:
        summary New summary
    ...
    Please enclose the new summary within quotes. For example:
    <BLANKLINE>
        summary "This is a new summary"
    ...


private yes|no
~~~~~~~~~~~~~~

Changes the visibility of the bug. Example:

(We'll subscribe Sample Person to this bug before marking it private,
otherwise permission to complete the operation will be denied.)

    >>> subscription = bug_four.subscribe(bug_four.owner, bug_four.owner)

We will also add an attachment to the bug.

    >>> bug_attachment = bug_four.addAttachment(
    ...     bug_four.owner, b"Attachment", "No comment", "test.txt", url=None
    ... )

    >>> submit_commands(bug_four, "private yes")
    >>> bug_four.private
    True

We flush the database caches to ensure that the timestamp is set:

    >>> from lp.services.database.sqlbase import flush_database_caches
    >>> flush_database_caches()

A timestamp and the user that sets the bug private is also recorded:

    >>> bug_four.date_made_private
    datetime.datetime(...)
    >>> print(bug_four.who_made_private.name)
    name12
    >>> bug_attachment.libraryfile.restricted
    True

The bug report can also be made public:

    >>> submit_commands(bug_four, "private no")
    >>> bug_four.private
    False
    >>> bug_attachment.libraryfile.restricted
    False

The timestamp and user are cleared:

    >>> print(bug_four.date_made_private)
    None
    >>> print(bug_four.who_made_private)
    None

Specifying something else than 'yes' or 'no' produces an error:

    >>> submit_commands(bug_four, "private whatever")
    >>> print_latest_email()
    Subject: Submit Request Failure
    To: test@canonical.com
    <BLANKLINE>
    ...
    Failing command:
        private whatever
    ...
    The 'private' command expects either 'yes' or 'no'.
    <BLANKLINE>
    For example:
    <BLANKLINE>
        private yes
    ...


security yes|no
~~~~~~~~~~~~~~~

Changes the security flag of the bug. Example:

    >>> bug_four.private
    False
    >>> bug_four.security_related
    False

    >>> submit_commands(bug_four, "security yes")
    >>> bug_four.security_related
    True

Switching on the security flag will also make the bug private, since
most often security bugs should be private as well.

    >>> bug_four.private
    True

Switching off the security flag won't make the bug public, though.

    >>> submit_commands(bug_four, "security no")
    >>> bug_four.security_related
    False

    >>> bug_four.private
    True
    >>> bug_four.setPrivate(False, getUtility(ILaunchBag).user)
    True
    >>> transaction.commit()

Specifying something else than 'yes' or 'no' produces an error:

    >>> submit_commands(bug_four, "security whatever")
    >>> print_latest_email()
    Subject: Submit Request Failure
    To: test@canonical.com
    <BLANKLINE>
    ...
    Failing command:
        security whatever
    ...
    The 'security' command expects either 'yes' or 'no'.
    <BLANKLINE>
    For example:
    <BLANKLINE>
        security yes
    ...

subscribe [$name|$email]
~~~~~~~~~~~~~~~~~~~~~~~~

Subscribes yourself or someone else to the bug. All arguments are
optional. If you don't specify a name, the sender of the email will
be subscribed. Examples:

    >>> subscriptions = [
    ...     subscription.person.name
    ...     for subscription in bug_four.subscriptions
    ... ]
    >>> subscriptions.sort()
    >>> for name in subscriptions:
    ...     print(name)
    ...
    name12


    >>> submit_commands(bug_four, "subscribe")
    >>> "Sample Person" in [
    ...     subscription.person.displayname
    ...     for subscription in bug_four.subscriptions
    ... ]
    True
    >>> submit_commands(bug_four, "subscribe foo.bar@canonical.com")
    >>> "Foo Bar" in [
    ...     subscription.person.displayname
    ...     for subscription in bug_four.subscriptions
    ... ]
    True
    >>> submit_commands(bug_four, "subscribe mark")
    >>> "Mark Shuttleworth" in [
    ...     subscription.person.displayname
    ...     for subscription in bug_four.subscriptions
    ... ]
    True

If we specify a non-existent user, an error message will be sent:

    >>> submit_commands(bug_four, "subscribe non_existant@canonical.com")
    >>> print_latest_email()
    Subject: Submit Request Failure
    To: test@canonical.com
    <BLANKLINE>
    ...
    Failing command:
        subscribe non_existant@canonical.com
    ...
    There's no such person with the specified name or email:
    non_existant@canonical.com
    ...

unsubscribe [$name|$email]
~~~~~~~~~~~~~~~~~~~~~~~~~~

Unsubscribes yourself or someone else from the bug.  If you don't
specify a name or email, the sender of the email will be
unsubscribed. Examples:

    >>> login("foo.bar@canonical.com")
    >>> submit_commands(bug_four, "unsubscribe foo.bar@canonical.com")
    >>> "Foo Bar" in [
    ...     subscription.person.displayname
    ...     for subscription in bug_four.subscriptions
    ... ]
    False
    >>> login(sampledata.USER_EMAIL)
    >>> submit_commands(bug_four, "unsubscribe")
    >>> "Sample Person" in [
    ...     subscription.person.displayname
    ...     for subscription in bug_four.subscriptions
    ... ]
    False

If the user sending the email does not have permission to perform
the unsubscribe request, an error message will be sent.

    >>> login(sampledata.NO_PRIVILEGE_EMAIL)
    >>> submit_commands(bug_four, "unsubscribe mark")
    >>> print_latest_email()
    Subject: Submit Request Failure
    To: no-priv@canonical.com
    <BLANKLINE>
    ...
    You do not have permission to unsubscribe Mark Shuttleworth.
    ...

Unsubscribing from a bug also unsubscribes you from its duplicates. To
demonstrate, let's first make no_privs an indirect subscriber from bug
#5, by subscribing them directly to a dupe of bug #5, bug #6.

    >>> from operator import attrgetter
    >>> from lp.registry.interfaces.person import IPersonSet

    >>> login("no-priv@canonical.com")

    >>> no_priv = getUtility(IPersonSet).getByName("no-priv")
    >>> bug_five = bugset.get(5)
    >>> bug_six = bugset.get(6)
    >>> bug_six.duplicateof == bug_five
    True

    >>> for subscriber in sorted(
    ...     bug_five.getIndirectSubscribers(), key=attrgetter("displayname")
    ... ):
    ...     print(subscriber.displayname)
    Sample Person

    >>> bug_six.subscribe(no_priv, no_priv)
    <BugSubscription ...>

    >>> for subscriber in sorted(
    ...     bug_five.getIndirectSubscribers(), key=attrgetter("displayname")
    ... ):
    ...     print(subscriber.displayname)
    No Privileges Person
    Sample Person

Now, if we unsubscribe no-priv from bug #5, they will actually get
unsubscribed from bug #6, thus no longer being indirectly subscribed to
bug #5.

    >>> bug_six.isSubscribed(no_priv)
    True

    >>> submit_commands(bug_five, "unsubscribe")

    >>> bug_six.isSubscribed(no_priv)
    False

    >>> for subscriber in sorted(
    ...     bug_five.getIndirectSubscribers(), key=attrgetter("displayname")
    ... ):
    ...     print(subscriber.displayname)
    Sample Person

(Log back in for the tests that follow.)

    >>> login(sampledata.USER_EMAIL)

If we specify a non-existent user, an error message will be sent:

    >>> submit_commands(bug_four, "unsubscribe non_existant")
    >>> print_latest_email()
    Subject: Submit Request Failure
    To: test@canonical.com
    <BLANKLINE>
    ...
    Failing command:
        unsubscribe non_existant
    ...
    There's no such person with the specified name or email: non_existant
    ...

Let's subscribe Sample Person to the bug again, so that it has at least
one subscriber:

    >>> submit_commands(bug_four, "subscribe test@canonical.com")


tag $tag
~~~~~~~~

The 'tag' command assigns a tag to a bug. Using this command we will add the
tags foo and bar to the bug. Adding a single tag multiple times should
only result in the tag showing up once on the bug.

    >>> submit_commands(bug_four, "tag foo bar foo bar")
    >>> for tag in bug_four.tags:
    ...     print(tag)
    ...
    bar
    foo
    layout-test

We can also use the tag command to remove tags.

    >>> submit_commands(bug_four, "tag -foo")
    >>> for tag in bug_four.tags:
    ...     print(tag)
    ...
    bar
    layout-test

Trying to remove a tag that is not assigned will result in an error message
being sent.

    >>> submit_commands(bug_four, "tag -foobar")
    >>> print_latest_email()
    Subject: Submit Request Failure
    To: test@canonical.com
    <BLANKLINE>
    ...
    Failing command:
        tag -foobar
    ...
    The tag you tried to remove is not assigned to this bug: foobar
    ...

If we specify an invalid tag to be added, an error message will be sent:

    >>> submit_commands(bug_four, "tag bad_tag")
    >>> print_latest_email()
    Subject: Submit Request Failure
    To: test@canonical.com
    <BLANKLINE>
    ...
    Failing command:
        tag bad_tag
    ...
    A tag you specified is invalid: bad_tag
    <BLANKLINE>
    Tags must start with a letter or number and be lowercase. The
    characters "+", "-" and "." are also allowed after the first
    character.
    ...

We will receive the same message if we specify an invalid tag to be removed:

    >>> submit_commands(bug_four, "tag -bad_tag")
    >>> print_latest_email()
    Subject: Submit Request Failure
    To: test@canonical.com
    <BLANKLINE>
    ...
    Failing command:
        tag -bad_tag
    ...
    A tag you specified is invalid: bad_tag
    <BLANKLINE>
    Tags must start with a letter or number and be lowercase. The
    characters "+", "-" and "." are also allowed after the first
    character.
    ...

As the message says, tags can contain a few non-alphanumeric character
after the first character.

    >>> submit_commands(bug_four, "tag with-hyphen+period.")
    >>> for tag in bug_four.tags:
    ...     print(tag)
    ...
    bar
    layout-test
    with-hyphen+period.


duplicate $bug_id
~~~~~~~~~~~~~~~~~

The 'duplicate' command marks a bug as a duplicate of another bug.

    >>> bug_four.duplicateof is None
    True
    >>> submit_commands(bug_four, "duplicate 1")
    >>> bug_four.duplicateof.id
    1

It's possible to unmark a bug as a duplicate by specifying 'no' as the
bug id.

    >>> submit_commands(bug_four, "duplicate no")
    >>> bug_four.duplicateof is None
    True

The bug id can also be the bug's name.

    >>> submit_commands(bug_four, "duplicate blackhole")
    >>> print(bug_four.duplicateof.name)
    blackhole

An error message is sent if a nonexistent bug id is given.

    >>> submit_commands(bug_four, "duplicate nonexistent")
    >>> print_latest_email()
    Subject: Submit Request Failure
    To: test@canonical.com
    <BLANKLINE>
    ...
    Failing command:
        duplicate nonexistent
    ...
    There is no such bug in Launchpad: nonexistent
    ...


If the specified bug already is a duplicate, an error message is sent,
telling you that you what bug it's a duplicate of.  Due to bug #1088358
the error is escaped as if it was HTML.

    >>> bug_two = getUtility(IBugSet).get(2)
    >>> bug_two.duplicateof is None
    True
    >>> submit_commands(bug_two, "duplicate 4")
    >>> bug_two.duplicateof is None
    True

    >>> print_latest_email()
    Subject: Submit Request Failure
    To: test@canonical.com
    <BLANKLINE>
    ...
    Failing command:
        duplicate 4
    ...
    Bug 4 is already a duplicate of bug 2. You can only
    mark a bug report as duplicate of one that isn&#x27;t a
    duplicate itself.
    ...


cve $cve
~~~~~~~~

The 'cve' command associates a bug with a CVE reference.

    >>> from lp.bugs.interfaces.bug import CreateBugParams
    >>> from lp.registry.interfaces.product import IProductSet
    >>> def new_firefox_bug():
    ...     firefox = getUtility(IProductSet).getByName("firefox")
    ...     return firefox.createBug(
    ...         CreateBugParams(
    ...             getUtility(ILaunchBag).user, "New Bug", comment="New bug."
    ...         )
    ...     )
    ...
    >>> bug = new_firefox_bug()
    >>> submit_commands(bug, "cve CVE-1999-8979")
    >>> for cve in bug.cves:
    ...     print(cve.displayname)
    ...
    CVE-1999-8979

If the CVE sequence can't be found, an error message is sent to the
user.

    >>> bug = new_firefox_bug()
    >>> transaction.commit()
    >>> submit_commands(bug, "cve no-such-cve")
    >>> bug.cves
    []

    >>> print_latest_email()
    Subject: Submit Request Failure
    To: test@canonical.com
    <BLANKLINE>
    ...
    Failing command:
        cve no-such-cve
    ...
    Launchpad can't find the CVE "no-such-cve".
    ...

affects, assignee, status, importance, milestone
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

affects $path [assignee $name|$email|nobody]
              [status $status]
              [importance $importance]
              [milestone $milestone]

XXX: BjornTillenius 2006-04-06 GavinPanella 2007-10-18 bug=153343:
     This section should be split into four different sections, one
     for each command. It used to be possible to write 'affects /foo
     status confirmed', but it's not anymore.  'affects', 'status',
     'importance' and 'assignee' are different commands, and they need
     to be on separate lines. There's no such thing as a sub command
     anymore.

Change the state of a bug in a specific context. $path can be of
the following form:

    $productname
    $productname/$series
    $distroname
    $distroname/$sourcepackagename
    $distroname/$series
    $distroname/$series/$sourcepackagename

If there is no task with the specified $path target, a new task is
created:

    >>> stub.test_emails = []
    >>> len(bug_four.bugtasks)
    1
    >>> "debian" in [bugtask.target.name for bugtask in bug_four.bugtasks]
    False
    >>> submit_commands(bug_four, "affects debian")
    >>> len(bug_four.bugtasks)
    2
    >>> "debian" in [bugtask.target.name for bugtask in bug_four.bugtasks]
    True

A notification was added:

    >>> bug_notification = (
    ...     IStore(BugNotification)
    ...     .find(BugNotification)
    ...     .order_by(BugNotification.id)
    ...     .last()
    ... )
    >>> print(bug_notification.message.text_contents)
    ** Also affects: debian
    ...

Submitting the same thing again doesn't do anything, since the task
already exists:

    >>> submit_commands(bug_four, "affects debian")
    >>> len(bug_four.bugtasks)
    2

We can change the assignee, status, and importance using the sub
commands. It's possible to have these sub commands on separate lines:

    >>> submit_commands(
    ...     bug_four,
    ...     "affects debian",
    ...     "importance critical",
    ...     "status confirmed",
    ...     "assignee test@canonical.com",
    ... )

    >>> len(bug_four.bugtasks)
    2
    >>> debian_task = bug_four.bugtasks[-1]
    >>> print(debian_task.importance.name)
    CRITICAL
    >>> print(debian_task.status.name)
    CONFIRMED
    >>> print(debian_task.assignee.displayname)
    Sample Person

A milestone can be assigned to the current task.

    >>> firefox_task = [
    ...     bugtask
    ...     for bugtask in bug_four.bugtasks
    ...     if bugtask.pillar.name == "firefox"
    ... ][0]
    >>> print(firefox_task.milestone)
    None
    >>> submit_commands(bug_four, "milestone 1.0")
    >>> print(firefox_task.milestone.name)
    1.0
    >>> submit_commands(bug_four, "milestone -")
    >>> print(firefox_task.milestone)
    None

Trying to set a milestone that does not exist elicits a helpful error
message:

    >>> submit_commands(bug_four, "milestone 1.1")
    >>> print_latest_email()
    Subject: Submit Request Failure
    To: test@canonical.com
    <BLANKLINE>
    ...
    Failing command:
        milestone 1.1
    ...
    The milestone 1.1 does not exist for Mozilla Firefox. Note that
    milestones are not automatically created from emails; they must be
    created on the website.
    ...

Attempting to set the milestone for a bug without sufficient
permissions also elicits an error message:

    >>> login(sampledata.USER_EMAIL)
    >>> bug = new_firefox_bug()
    >>> transaction.commit()

    >>> login("no-priv@canonical.com")
    >>> for bugtask in bug.bugtasks:
    ...     print(bugtask.pillar.title)
    ...
    Mozilla Firefox
    >>> print(bug.bugtasks[0].milestone)
    None
    >>> submit_commands(bug, "milestone 1.0")
    >>> print(bug.bugtasks[0].milestone)
    None
    >>> print_latest_email()
    Subject: Submit Request Failure
    To: no-priv@canonical.com
    <BLANKLINE>
    ...
    Failing command:
        milestone 1.0
    ...
    You do not have permission to set the milestone for Mozilla Firefox.
    Only owners, drivers and bug supervisors may assign milestones.
    ...

Sample person must be a bug supervisor for Ubuntu and Evolution to be able to
nominate bugs for a release.

    >>> from lp.registry.interfaces.distribution import IDistributionSet
    >>> from lp.testing.sampledata import ADMIN_EMAIL
    >>> from zope.component import getUtility
    >>> from zope.security.proxy import removeSecurityProxy
    >>>
    >>> login(ADMIN_EMAIL)
    >>> sample_person = getUtility(IPersonSet).getByEmail(
    ...     sampledata.USER_EMAIL
    ... )
    >>> ubuntu = getUtility(IDistributionSet).getByName("ubuntu")
    >>> ubuntu = removeSecurityProxy(ubuntu)
    >>> ubuntu.bug_supervisor = sample_person

    >>> login(sampledata.USER_EMAIL)

Like the web UI, we can assign a bug to nobody.

    >>> submit_commands(bug_four, "affects debian", "assignee nobody")
    >>> debian_task.assignee is None
    True

Also like the web UI, we can assign a bug to "me", the current user.

    >>> submit_commands(bug_four, "affects debian", "assignee me")
    >>> print(debian_task.assignee.name)
    name12

To set which source package the bug affects, we use:

    >>> submit_commands(bug_four, "affects debian/mozilla-firefox")
    >>> len(bug_four.bugtasks)
    2
    >>> debian_task = bug_four.bugtasks[-1]
    >>> print(debian_task.sourcepackagename.name)
    mozilla-firefox

If we specify another source package in the same distribution, a new
task will be created:

    >>> submit_commands(bug_four, "affects debian/evolution")
    >>> len(bug_four.bugtasks)
    3
    >>> evolution_task = bug_four.bugtasks[-2]
    >>> print(evolution_task.sourcepackagename.name)
    evolution

It's also possible to add tasks for specific distribution series as
well.

    >>> bug = new_firefox_bug()
    >>> for bugtask in bug.bugtasks:
    ...     print(bugtask.bugtargetdisplayname)
    ...
    Mozilla Firefox

    >>> submit_commands(bug, "affects ubuntu/hoary")

This caused one bugtask to be added to the bug. The added bug task is a
generic Ubuntu task, though.

    >>> for bugtask in bug.bugtasks:
    ...     print(bugtask.bugtargetdisplayname)
    ...
    Mozilla Firefox
    Ubuntu

Because Sample Person isn't a driver of Ubuntu, they're not allowed to
target a bug directly, instead a nomination was created.

    >>> for nomination in bug.getNominations():
    ...     print(nomination.target.bugtargetdisplayname)
    ...
    Ubuntu Hoary

The same happens if we try to target another series.

    >>> submit_commands(bug, "affects ubuntu/warty")

    >>> for bugtask in bug.bugtasks:
    ...     print(bugtask.bugtargetdisplayname)
    ...
    Mozilla Firefox
    Ubuntu

    >>> for nomination in bug.getNominations():
    ...     print(nomination.target.bugtargetdisplayname)
    ...
    Ubuntu Hoary
    Ubuntu Warty

Targeting an existing nomination won't create another nomination.

    >>> submit_commands(bug, "affects ubuntu/warty")

    >>> for bugtask in bug.bugtasks:
    ...     print(bugtask.bugtargetdisplayname)
    ...
    Mozilla Firefox
    Ubuntu

    >>> for nomination in bug.getNominations():
    ...     print(nomination.target.bugtargetdisplayname)
    ...
    Ubuntu Hoary
    Ubuntu Warty

If Sample Person would be the Ubuntu driver, they'll be able to target
bugs directly to series.

    >>> from lp.testing.dbuser import lp_dbuser
    >>> from lp.registry.interfaces.distribution import IDistributionSet

    # The script's default user doesn't have permission to change the driver.
    >>> with lp_dbuser():
    ...     login("foo.bar@canonical.com")
    ...     ubuntu = getUtility(IDistributionSet).getByName("ubuntu")
    ...     ubuntu.driver = getUtility(IPersonSet).getByEmail(
    ...         sampledata.USER_EMAIL
    ...     )
    ...

    >>> login(sampledata.USER_EMAIL)

Now a new bugtask for the series will be created directly.

    >>> submit_commands(bug, "affects ubuntu/grumpy")

    >>> for bugtask in bug.bugtasks:
    ...     print(bugtask.bugtargetdisplayname)
    ...
    Mozilla Firefox
    Ubuntu
    Ubuntu Grumpy

They can also approve existing nominations.

    >>> submit_commands(bug, "affects ubuntu/warty")

    >>> for bugtask in bug.bugtasks:
    ...     print(bugtask.bugtargetdisplayname)
    ...
    Mozilla Firefox
    Ubuntu
    Ubuntu Warty
    Ubuntu Grumpy

It works the same when specifying a source package while targeting a
specific distroseries.

    >>> bug = new_firefox_bug()
    >>> for bugtask in bug.bugtasks:
    ...     print(bugtask.bugtargetdisplayname)
    ...
    Mozilla Firefox

    >>> submit_commands(bug, "affects ubuntu/hoary/mozilla-firefox")

Now we can see that two tasks were created; both the general Ubuntu
task, and the series specific task.

    >>> for bugtask in bug.bugtasks:
    ...     print(bugtask.bugtargetdisplayname)
    ...
    Mozilla Firefox
    mozilla-firefox (Ubuntu)
    mozilla-firefox (Ubuntu Hoary)

As with the example with no source package above; if the user isn't a
driver of the series, only a nomination will be created.

    >>> with lp_dbuser():
    ...     login("foo.bar@canonical.com")
    ...     ubuntu = getUtility(IDistributionSet).getByName("ubuntu")
    ...     ubuntu.driver = None
    ...

    >>> login(sampledata.USER_EMAIL)

    >>> bug = new_firefox_bug()
    >>> for bugtask in bug.bugtasks:
    ...     print(bugtask.bugtargetdisplayname)
    ...
    Mozilla Firefox

    >>> submit_commands(bug, "affects ubuntu/hoary/mozilla-firefox")

    >>> for bugtask in bug.bugtasks:
    ...     print(bugtask.bugtargetdisplayname)
    ...
    Mozilla Firefox
    mozilla-firefox (Ubuntu)

    >>> for nomination in bug.getNominations():
    ...     print(nomination.target.bugtargetdisplayname)
    ...
    Ubuntu Hoary

Nominating product series work the same way as for distro series.
Sample person is a driver for the Firefox trunk series, so the
nomination is automatically approved.

    >>> firefox = getUtility(IProductSet).getByName("firefox")
    >>> for driver in firefox.getSeries("trunk").drivers:
    ...     print(driver.displayname)
    ...
    Sample Person

    >>> login(sampledata.USER_EMAIL)
    >>> submit_commands(bug, "affects /firefox/trunk")

    >>> for bugtask in bug.bugtasks:
    ...     print(bugtask.bugtargetdisplayname)
    ...
    Mozilla Firefox
    Mozilla Firefox trunk
    mozilla-firefox (Ubuntu)

    >>> for nomination in bug.getNominations():
    ...     print(nomination.target.bugtargetdisplayname)
    ...
    Mozilla Firefox trunk
    Ubuntu Hoary

If the user doesn't have permission to approve the nomination, no series
bug task will be created, only a nomination. A general product bugtask
will be created if one doesn't exist.

    >>> login(ADMIN_EMAIL)
    >>> no_priv = getUtility(IPersonSet).getByEmail("no-priv@canonical.com")
    >>> evolution = getUtility(IProductSet).getByName("evolution")
    >>> evolution = removeSecurityProxy(evolution)
    >>> evolution.bug_supervisor = no_priv

    >>> login("no-priv@canonical.com")
    >>> bug = new_firefox_bug()
    >>> submit_commands(bug, "affects /evolution/trunk")

    >>> for bugtask in bug.bugtasks:
    ...     print(bugtask.bugtargetdisplayname)
    ...
    Evolution
    Mozilla Firefox

    >>> for nomination in bug.getNominations():
    ...     print(nomination.target.bugtargetdisplayname)
    ...
    Evolution trunk

    >>> login(sampledata.USER_EMAIL)

Let's take on the upstream task on bug four as well. This time we'll
sneak in a 'subscribe' command between the 'affects' and the other
commands, to show that the commands acting on the bug task don't have to
be grouped together:

    >>> submit_commands(
    ...     bug_four,
    ...     "affects firefox",
    ...     "importance critical",
    ...     "subscribe no-priv",
    ...     "status confirmed",
    ...     "assignee test@canonical.com",
    ... )

    >>> len(bug_four.bugtasks)
    3
    >>> upstream_task = bug_four.bugtasks[0]
    >>> print(upstream_task.importance.name)
    CRITICAL
    >>> print(upstream_task.status.name)
    CONFIRMED
    >>> print(upstream_task.assignee.displayname)
    Sample Person


Restricted bug statuses
~~~~~~~~~~~~~~~~~~~~~~~

    >>> email_user = getUtility(ILaunchBag).user

Bug supervisors can set some restricted statuses:

    >>> with lp_dbuser():
    ...     login("foo.bar@canonical.com")
    ...     upstream_task.pillar.bug_supervisor = email_user
    ...

    >>> ignored = login_person(email_user)

    >>> submit_commands(bug_four, "status wontfix")
    >>> print(upstream_task.status.title)
    Won't Fix

    >>> submit_commands(bug_four, "status expired")
    >>> print(upstream_task.status.title)
    Expired

Everyone else gets an explanatory error message:

    >>> from lp.bugs.interfaces.bugtask import BugTaskStatus
    >>> upstream_task.transitionToStatus(BugTaskStatus.NEW, email_user)

    >>> with lp_dbuser():
    ...     login("foo.bar@canonical.com")
    ...     upstream_task.pillar.bug_supervisor = None
    ...

    >>> login("no-priv@canonical.com")

    >>> submit_commands(bug_four, "affects firefox", "status wontfix")
    >>> print_latest_email()
    Subject: Submit Request Failure
    To: no-priv@canonical.com
    <BLANKLINE>
    ...
    Failing command:
        status wontfix
    ...
    The status cannot be changed to wontfix because you are not the
    maintainer, driver or bug supervisor for Mozilla Firefox.
    ...

    >>> submit_commands(bug_four, "affects firefox", "status expired")
    >>> print_latest_email()
    Subject: Submit Request Failure
    To: no-priv@canonical.com
    <BLANKLINE>
    ...
    Failing command:
        status expired
    ...
    The status cannot be changed to expired because you are not the
    maintainer, driver or bug supervisor for Mozilla Firefox.
    ...

Let's take a look at all the other error messages that the sub
commands can produce.

    >>> ignored = login_person(email_user)

Invalid status:

    >>> submit_commands(bug_four, "status foo")
    >>> print_latest_email()
    Subject: Submit Request Failure
    To: test@canonical.com
    <BLANKLINE>
    ...
    Failing command:
        status foo
    ...
    The 'status' command expects any of the following arguments:
    new, incomplete, opinion, invalid, wontfix, expired, confirmed, triaged,
    inprogress, deferred, fixcommitted, fixreleased, doesnotexist
    <BLANKLINE>
    For example:
    <BLANKLINE>
        status new
    ...

Invalid importance:

    >>> submit_commands(bug_four, "importance foo")
    >>> print_latest_email()
    Subject: Submit Request Failure
    To: test@canonical.com
    <BLANKLINE>
    ...
    Failing command:
        importance foo
    ...
    The 'importance' command expects any of the following arguments:
    undecided, critical, high, medium, low, wishlist
    <BLANKLINE>
    For example:
    <BLANKLINE>
        importance undecided
    ...

XXX mpt 20060516: "importance undecided" is a silly example, but customizing
it to a realistic value is difficult (see convertArguments in
launchpad/mail/commands.py).

Trying to use the obsolete "severity" or "priority" commands:

    >>> stub.test_emails = []
    >>> submit_commands(bug_four, "affects firefox", "severity major")
    >>> print_latest_email()
    Subject: Submit Request Failure
    To: test@canonical.com
    <BLANKLINE>
    ...
    Failing command:
        severity major
    ...
    To make life a little simpler, Malone no longer has "priority" and
    "severity" fields. There is now an "importance" field...
    ...

    >>> submit_commands(bug_four, "affects firefox", "priority low")
    >>> print_latest_email()
    Subject: Submit Request Failure
    To: test@canonical.com
    <BLANKLINE>
    ...
    Failing command:
        priority low
    ...
    To make life a little simpler, Malone no longer has "priority" and
    "severity" fields. There is now an "importance" field...
    ...

Invalid assignee:

    >>> submit_commands(bug_four, "assignee foo")
    >>> print_latest_email()
    Subject: Submit Request Failure
    To: test@canonical.com
    <BLANKLINE>
    ...
    Failing command:
        assignee foo
    ...
    There's no such person with the specified name or email: foo
    ...


    >>> stub.test_emails = []


Multiple Commands
-----------------

An email can contain multiple commands, even for different bugs.

    >>> def print_bugtask_modified_event(bugtask, event):
    ...     old_bugtask = event.object_before_modification
    ...     print(
    ...         "event: bug %i %s => %s"
    ...         % (
    ...             bugtask.bug.id,
    ...             old_bugtask.status.title,
    ...             bugtask.status.title,
    ...         )
    ...     )
    ...     print(
    ...         "event: bug %i %s => %s"
    ...         % (
    ...             bugtask.bug.id,
    ...             old_bugtask.importance.title,
    ...             bugtask.importance.title,
    ...         )
    ...     )
    ...
    >>> def print_bugtask_created_event(bugtask, event):
    ...     print(
    ...         "event: new bugtask, bug %i %s"
    ...         % (bugtask.bug.id, bugtask.status.title)
    ...     )
    ...     print(
    ...         "event: new bugtask, bug %i %s"
    ...         % (bugtask.bug.id, bugtask.importance.title)
    ...     )
    ...
    >>> from lazr.lifecycle.interfaces import (
    ...     IObjectCreatedEvent,
    ...     IObjectModifiedEvent,
    ... )
    >>> from lp.bugs.interfaces.bugtask import IBugTask
    >>> from lp.testing.fixture import ZopeEventHandlerFixture
    >>> bugtask_modified_listener = ZopeEventHandlerFixture(
    ...     print_bugtask_modified_event, (IBugTask, IObjectModifiedEvent)
    ... )
    >>> bugtask_modified_listener.setUp()
    >>> bugtask_created_listener = ZopeEventHandlerFixture(
    ...     print_bugtask_created_event, (IBugTask, IObjectCreatedEvent)
    ... )
    >>> bugtask_created_listener.setUp()
    >>> bug_four_upstream_task = bug_four.bugtasks[0]
    >>> print(bug_four_upstream_task.status.name)
    NEW
    >>> print(bug_four_upstream_task.importance.name)
    CRITICAL
    >>> bug_five_upstream_task = bug_five.bugtasks[0]
    >>> print(bug_five_upstream_task.status.name)
    NEW
    >>> print(bug_five_upstream_task.importance.name)
    CRITICAL
    >>> submit_commands(
    ...     bug_four,
    ...     "bug 4",
    ...     "status confirmed",
    ...     "importance medium",
    ...     "bug new",
    ...     "affects firefox",
    ...     "summary blah",
    ...     "status new",
    ...     "importance high",
    ...     "bug 5",
    ...     "status fixreleased",
    ...     "importance high",
    ... )
    event: bug 4 New => Confirmed
    event: bug 4 Critical => Medium
    event: bug 5 New => Fix Released
    event: bug 5 Critical => High
    >>> print(bug_four_upstream_task.status.name)
    CONFIRMED
    >>> print(bug_four_upstream_task.importance.name)
    MEDIUM
    >>> print(bug_five_upstream_task.status.name)
    FIXRELEASED
    >>> print(bug_five_upstream_task.importance.name)
    HIGH

    >>> bugtask_modified_listener.cleanUp()
    >>> bugtask_created_listener.cleanUp()


Default 'affects' target
------------------------

Most of the time it's not necessary to give the 'affects' command. If
you omit it, the email interface  tries to guess which bug task you
wanted to edit.

If there's only one task, that task will be edited. So if we simply send
a 'status' command to bug seven, the single upstream task will be
edited:

    >>> login("foo.bar@canonical.com")
    >>> bug_ten = getUtility(IBugSet).get(10)
    >>> len(bug_ten.bugtasks)
    1
    >>> submit_commands(bug_ten, "status confirmed")
    >>> linux_task = bug_ten.bugtasks[0]
    >>> print(linux_task.status.name)
    CONFIRMED

    >>> bug_notification = (
    ...     IStore(BugNotification)
    ...     .find(BugNotification)
    ...     .order_by(BugNotification.id)
    ...     .last()
    ... )
    >>> print(bug_notification.bug.id)
    10
    >>> print(bug_notification.message.text_contents)
    ** Changed in: linux-source-2.6.15 (Ubuntu)
        Status: New => Confirmed

If the bug has more than one bug task, we try to guess which bug task
the user wanted to edit. We apply the following heuristics for choosing
which bug task to edit:

The user is a bug supervisors of the upstream product
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    >>> login(sampledata.USER_EMAIL)
    >>> bug_one = getUtility(IBugSet).get(1)
    >>> submit_commands(
    ...     bug_one, "status confirmed", "assignee test@canonical.com"
    ... )
    >>> for bugtask in bug_one.bugtasks:
    ...     print(
    ...         "%s: %s, assigned to %s"
    ...         % (
    ...             bugtask.bugtargetdisplayname,
    ...             bugtask.status.title,
    ...             getattr(bugtask.assignee, "displayname", "no one"),
    ...         )
    ...     )
    ...
    Mozilla Firefox: Confirmed, assigned to Sample Person
    mozilla-firefox (Ubuntu): New, assigned to no one
    mozilla-firefox (Debian): Confirmed, assigned to no one

    >>> from storm.locals import Desc
    >>> pending_notifications = (
    ...     IStore(BugNotification)
    ...     .find(BugNotification)
    ...     .order_by(Desc(BugNotification.id))[:2]
    ... )
    >>> for bug_notification in pending_notifications:
    ...     print(bug_notification.bug.id)
    ...     print(bug_notification.message.text_contents)
    ...
    1
    ** Changed in: firefox
         Assignee: Mark Shuttleworth (mark) => Sample Person (name12)
    1
    ** Changed in: firefox
           Status: New => Confirmed...


The user is a package bug supervisor
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    >>> from lp.registry.interfaces.distribution import IDistributionSet
    >>> from lp.registry.interfaces.sourcepackagename import (
    ...     ISourcePackageNameSet,
    ... )

    >>> with lp_dbuser():
    ...     ubuntu = getUtility(IDistributionSet).getByName("ubuntu")
    ...     moz_name = getUtility(ISourcePackageNameSet)["mozilla-firefox"]
    ...     helge = getUtility(IPersonSet).getByName("kreutzm")
    ...     mozilla_package = ubuntu.getSourcePackage(moz_name)
    ...     ignore = mozilla_package.addBugSubscription(helge, helge)
    ...

    >>> login("kreutzm@itp.uni-hannover.de")

    >>> submit_commands(
    ...     bug_one,
    ...     "status confirmed",
    ...     "assignee kreutzm@itp.uni-hannover.de",
    ... )
    >>> for bugtask in bug_one.bugtasks:
    ...     print(
    ...         "%s: %s, assigned to %s"
    ...         % (
    ...             bugtask.bugtargetdisplayname,
    ...             bugtask.status.title,
    ...             getattr(bugtask.assignee, "displayname", "no one"),
    ...         )
    ...     )
    ...
    Mozilla Firefox: Confirmed, assigned to Sample Person
    mozilla-firefox (Ubuntu): Confirmed, assigned to Helge Kreutzmann
    mozilla-firefox (Debian): Confirmed, assigned to no one

    >>> pending_notifications = (
    ...     IStore(BugNotification)
    ...     .find(BugNotification)
    ...     .order_by(Desc(BugNotification.id))[:2]
    ... )
    >>> for bug_notification in pending_notifications:
    ...     print(bug_notification.bug.id)
    ...     print(bug_notification.message.text_contents)
    ...
    1
    ** Changed in: mozilla-firefox (Ubuntu)
         Assignee: (unassigned) => Helge Kreutzmann (kreutzm)
    1
    ** Changed in: mozilla-firefox (Ubuntu)
           Status: New => Confirmed

The user is a bug supervisor of a distribution
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

XXX: TBD after InitialBugContacts is implemented.
     -- Bjorn Tillenius, 2005-11-30

The user is a distribution member
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    >>> login("foo.bar@canonical.com")
    >>> submit_commands(bug_one, "status new", "assignee test@canonical.com")
    >>> for bugtask in bug_one.bugtasks:
    ...     print(
    ...         "%s: %s, assigned to %s"
    ...         % (
    ...             bugtask.bugtargetdisplayname,
    ...             bugtask.status.title,
    ...             getattr(bugtask.assignee, "displayname", "no one"),
    ...         )
    ...     )
    ...
    Mozilla Firefox: Confirmed, assigned to Sample Person
    mozilla-firefox (Ubuntu): New, assigned to Sample Person
    mozilla-firefox (Debian): Confirmed, assigned to no one

    >>> pending_notifications = (
    ...     IStore(BugNotification)
    ...     .find(BugNotification)
    ...     .order_by(Desc(BugNotification.id))[:2]
    ... )
    >>> for bug_notification in pending_notifications:
    ...     print(bug_notification.bug.id)
    ...     print(bug_notification.message.text_contents)
    ...
    1
    ** Changed in: mozilla-firefox (Ubuntu)
         Assignee: Helge Kreutzmann (kreutzm) => Sample Person (name12)
    1
    ** Changed in: mozilla-firefox (Ubuntu)
           Status: Confirmed => New


No matching bug task
~~~~~~~~~~~~~~~~~~~~

If none of the bug tasks can be chosen, an error message is sent to the
user, telling them that they have to use the 'affects' command.

    >>> del stub.test_emails[:]
    >>> login("stuart.bishop@canonical.com")
    >>> submit_commands(
    ...     bug_one, "status new", "assignee foo.bar@canonical.com"
    ... )
    >>> for bugtask in bug_one.bugtasks:
    ...     print(
    ...         "%s: %s, assigned to %s"
    ...         % (
    ...             bugtask.bugtargetdisplayname,
    ...             bugtask.status.title,
    ...             getattr(bugtask.assignee, "displayname", "no one"),
    ...         )
    ...     )
    ...
    Mozilla Firefox: Confirmed, assigned to Sample Person
    mozilla-firefox (Ubuntu): New, assigned to Sample Person
    mozilla-firefox (Debian): Confirmed, assigned to no one

    >>> print_latest_email()
    Subject: Submit Request Failure
    To: stuart.bishop@canonical.com
    <BLANKLINE>
    ...
    You tried to edit bug 1 via email, but it couldn't be determined in
    which context you wanted the changes to occur. The bug is reported in 3
    different contexts, and you have to specify which one by using the
    affects command.
    ...


More About Error Handling
-------------------------

If an error is encountered, an email is sent to the sender informing
them about the error. Let's start with trying to submit a bug without
signing the mail:

    >>> del stub.test_emails[:]
    >>> login(sampledata.USER_EMAIL)
    >>> simulate_receiving_untrusted_mail()

    >>> from lp.services.mail.signedmessage import signed_message_from_bytes
    >>> msg = signed_message_from_bytes(submit_mail)
    >>> import email.utils
    >>> msg["Message-Id"] = email.utils.make_msgid()
    >>> handler.process(
    ...     msg,
    ...     msg["To"],
    ... )
    True
    >>> print_latest_email()
    Subject: Submit Request Failure
    To: test@canonical.com
    <BLANKLINE>
    ...
    The message you sent included commands to modify the bug report,
    but you didn't sign the message with an OpenPGP key that is
    registered in Launchpad.
    ...

A submit without specifying on what we want to file the bug on:

    >>> login(sampledata.USER_EMAIL)
    >>> submit_mail_no_bugtask = b"""From: test@canonical.com
    ... To: new@malone
    ... Date: Fri Jun 17 10:20:23 BST 2005
    ... Subject: A bug without a product or distribution
    ...
    ... There's a nasty bug in Evolution."""
    >>> process_email(submit_mail_no_bugtask)
    >>> print_latest_email()  # doctest: -NORMALIZE_WHITESPACE
    Subject: Submit Request Failure
    To: test@canonical.com
    <BLANKLINE>
    ...
    You didn't specify the project, distribution, or package that the bug is
    ...


Submit a bug on a distribution that doesn't exist:

    >>> submit_mail_distro_not_found = b"""From: test@canonical.com
    ... To: new@malone
    ... Date: Fri Jun 17 10:20:23 BST 2005
    ... Subject: A bug with a non existing distribution
    ...
    ... There's a nasty bug in Foo.
    ...  affects foo"""
    >>> process_email(submit_mail_distro_not_found)
    >>> print_latest_email()  # doctest: -NORMALIZE_WHITESPACE
    Subject: Submit Request Failure
    To: test@canonical.com
    <BLANKLINE>
    ...
    Failing command:
        affects foo
    ...
    There is no project named 'foo' registered in Launchpad.
    ...

    >>> stub.test_emails = []

An empty unsigned mail to new@malone:

    >>> submit_empty = b"""From: test@canonical.com
    ... To: new@malone
    ... Date: Fri Jun 17 10:20:27 BST 2005
    ... Subject: An empty mail
    ...
    ... """
    >>> process_email(submit_empty)
    >>> print_latest_email()  # doctest: -NORMALIZE_WHITESPACE
    Subject: Submit Request Failure
    To: test@canonical.com
    <BLANKLINE>
    ...
    You didn't specify the project, distribution, or package that the bug is
    ...

    >>> stub.test_emails = []

If we submit an email with no affects command, it is rejected.

    >>> from lp.bugs.model.bug import Bug
    >>> before_count = IStore(Bug).find(Bug).count()
    >>> submit_mail = b"""From: Foo Bar <foo.bar@canonical.com>
    ... To: new@bugs.launchpad.ubuntu.com
    ... Date: Fri Jun 17 10:20:23 BST 2005
    ... Subject: A bug with no affects
    ...
    ... I'm abusing ltsp-build-client to build a diskless fat client, but dint
    ... of --late-packages ubuntu-desktop. The dpkg --configure step for eg.
    ... HAL will try to start the daemon and failing, due to the lack of
    ... /proc.  This is just the tip of the iceberg; I'll file more bugs as I
    ... go along.
    ... """

    >>> process_email(submit_mail)
    >>> before_count == IStore(Bug).find(Bug).count()
    True

    >>> print_latest_email()
    Subject: Submit Request Failure
    To: test@canonical.com
    <BLANKLINE>
    ...
    You didn't specify the project, distribution, or package that the bug is
    ...

    >>> stub.test_emails = []

Even if there are other commands, the affects command is still
required. If it is missing, the message is also rejected.

XXX: Gavin Panella 2009-07-24 bug=404010: The need for this test
arises from the implementation of MaloneHandler.

    >>> before_count = IStore(Bug).find(Bug).count()
    >>> submit_mail = b"""From: Foo Bar <foo.bar@canonical.com>
    ... To: new@bugs.launchpad.ubuntu.com
    ... Date: Fri Jun 17 10:20:23 BST 2005
    ... Subject: A bug with no affects
    ...
    ... I have forgotten to say what this affects.
    ...
    ...  status confirmed
    ... """

    >>> process_email(submit_mail)
    >>> before_count == IStore(Bug).find(Bug).count()
    True

    >>> print_latest_email()
    Subject: Submit Request Failure
    To: test@canonical.com
    <BLANKLINE>
    ...
    You didn't specify the project, distribution, or package that the bug is
    ...

    >>> stub.test_emails = []

Another example of forgetting the affects command: trying to start a
new bug before saying what is affected by the implicitly created new
bug (sending email to new@bugs is equivalent to sending " bug new" to
edit@bugs).

XXX: Gavin Panella 2009-07-24 bug=404010: The need for this test
arises from the implementation of MaloneHandler.

    >>> before_count = IStore(Bug).find(Bug).count()
    >>> submit_mail = b"""\
    ... From: Foo Bar <foo.bar@canonical.com>
    ... To: new@bugs.launchpad.ubuntu.com
    ... Date: Fri Jun 17 10:20:23 BST 2005
    ... Subject: A bug with no affects
    ...
    ...  bug new
    ... """

    >>> process_email(submit_mail)
    >>> before_count == IStore(Bug).find(Bug).count()
    True

    >>> print_latest_email()
    Subject: Submit Request Failure
    To: test@canonical.com
    <BLANKLINE>
    ...
    You didn't specify the project, distribution, or package that the bug is
    ...

    >>> stub.test_emails = []

Even though bug-specific commands (i.e. those that don't require a
bugtask context) can run successfully, at least one bugtask context
must be set for a new bug, or the message will ultimately be rejected.

XXX: Gavin Panella 2009-07-24 bug=404010: Some combinations of
bug-related commands do blow up before the check for a bugtask is
reached. For example, unsubscribing oneself from a private bug then
linking a CVE.

    >>> before_count = IStore(Bug).find(Bug).count()
    >>> submit_mail = b"""\
    ... From: Foo Bar <foo.bar@canonical.com>
    ... To: new@bugs.launchpad.ubuntu.com
    ... Date: Fri Jun 17 10:20:23 BST 2005
    ... Subject: A bug with no affects
    ...
    ...  private yes
    ...  unsubscribe
    ...  cve 1999-8979
    ... """

    >>> process_email(submit_mail)
    >>> before_count == IStore(Bug).find(Bug).count()
    True

    >>> print_latest_email()
    Subject: Submit Request Failure
    To: test@canonical.com
    <BLANKLINE>
    ...
    You didn't specify the project, distribution, or package that the bug is
    ...

    >>> stub.test_emails = []

Let's take a closer look at send_process_error_notification(), which is
used to send the error messages. It needs the message that caused the
error, so let's create one.

    >>> test_msg = email.message_from_bytes(
    ...     b"""From: foo.bar@canonical.com
    ... To: bugs@launchpad.net
    ... Message-Id: <original@msg>
    ... Subject: Original Message Subject
    ... Date: Mon, 20 Mar 2006 10:26:28 -0000
    ... Content-Type: text/plain
    ...
    ... Original message body.
    ... """
    ... )

Now we can send an error mail, passing the created message to
send_process_error_notification().

    >>> from lp.services.mail.notification import (
    ...     send_process_error_notification,
    ... )
    >>> send_process_error_notification(
    ...     sampledata.USER_EMAIL,
    ...     "Some subject",
    ...     "Some error message.",
    ...     test_msg,
    ...     failing_command=["foo bar"],
    ... )

The To and Subject headers got set to the values we provided:

    >>> transaction.commit()
    >>> from_addr, to_addrs, raw_message = stub.test_emails[-1]
    >>> sent_msg = email.message_from_bytes(raw_message)
    >>> sent_msg["To"]
    'test@canonical.com'
    >>> sent_msg["Subject"]
    'Some subject'

The sent message contains two parts:

    >>> sent_msg.is_multipart()
    True
    >>> failure_msg, original_msg = sent_msg.get_payload()

The first part is the error message, explaining what went wrong.

    >>> print(failure_msg.get_payload(decode=True).decode("UTF-8"))
    An error occurred while processing a mail you sent to Launchpad's email
    interface.
    <BLANKLINE>
    Failing command:
        foo bar
    <BLANKLINE>
    Error message:
    <BLANKLINE>
    Some error message.
    <BLANKLINE>
    --
    For more information about using Launchpad by email, see
    https://help.launchpad.net/EmailInterface
    or send an email to help@launchpad.net

The second part is the message that the user sent, which caused the
error to happen.

    >>> original_msg.get_content_type()
    'message/rfc822'
    >>> len(original_msg.get_payload())
    1

    >>> msg = original_msg.get_payload()[0]
    >>> msg["Subject"]
    'Original Message Subject'
    >>> msg["Message-Id"]
    '<original@msg>'
    >>> print(msg.get_payload(decode=True).decode("UTF-8"))
    Original message body.

Sometimes the original error was caused by the original message being
too large.  In that case we cannot really return the entire original
message as our outgoing message will be too big.  So, we can truncate
the original message.

    >>> import math

    >>> max_return_size = int(math.ceil(len(str(test_msg)) / 2))
    >>> send_process_error_notification(
    ...     sampledata.USER_EMAIL,
    ...     "Some subject",
    ...     "Some error message.",
    ...     test_msg,
    ...     failing_command=["foo bar"],
    ...     max_return_size=max_return_size,
    ... )
    >>> transaction.commit()
    >>> from_addr, to_addrs, raw_message = stub.test_emails[-1]
    >>> sent_msg = email.message_from_bytes(raw_message)
    >>> failure_msg, original_msg = sent_msg.get_payload()
    >>> msg = original_msg.get_payload()[0]

Fudge due to new lines added to the payload.

    >>> len(str(msg)) <= (max_return_size + 2)
    True

Error handling
--------------

When creating a new task and assigning it to a team, it is possible
that the team will not have a contact address. This is not generally
a problem, but when formatting the notification email resulting from
that action we used to have a bug (See bug #126943).

First, we create a new firefox bug.

    >>> login(sampledata.USER_EMAIL)
    >>> submit_mail = b"""From: Sample Person <test@canonical.com>
    ... To: new@bugs.canonical.com
    ... Date: Fri Jun 17 10:20:23 BST 2006
    ... Subject: Another bug in Firefox
    ...
    ... Another bug in Firefox.
    ...  affects firefox
    ... """
    >>> process_email(submit_mail)
    >>> ff_bug = get_latest_added_bug()

Ordinary persons always have a preferred email address, but teams can
exist without a contact address.

    >>> wartygnome = getUtility(IPersonSet).getByName("warty-gnome")
    >>> print(wartygnome.preferredemail)
    None

We send another email, creating a new task (for the package in ubuntu)
and assigning the bug to `landscape-developers`.

    >>> submit_commands(
    ...     ff_bug,
    ...     "affects ubuntu/mozilla-firefox",
    ...     "assignee landscape-developers",
    ... )

The email was handled correctly - A new bugtask was added and assigned
to the specified team.

    >>> print(ff_bug.bugtasks[-1].assignee.name)
    landscape-developers


Recovering from errors
----------------------

When a user sends an email with multiple commands, some of them might
fail (because of bad arguments, for example). Some commands, namely
'affects', 'bug', 'security' and 'private', must succeed for the entire
email to be processed, but others can fail without affecting the other
commands.

The latest firefox bug task has a NEW status.

    >>> firefox = getUtility(IProductSet).getByName("firefox")
    >>> for task in ff_bug.bugtasks:
    ...     if task.product == firefox:
    ...         print(task.status.name)
    ...
    NEW

Sample Person sends an email with several commands. First comes an
'affects', to select the firefox task, then a 'subscribe' with a user
that doesn't exist (and so is guaranteed to result in a failure) and
finally, the status of the selected bug task is set to 'confirmed'.

    >>> submit_mail = (
    ...     """From: Sample Person <test@canonical.com>
    ... To: %s@bugs.canonical.com
    ... Date: Thu Apr 3 11:53:23 BST 2008
    ... Subject: A new bug in Firefox
    ...
    ... Another bug in Firefox.
    ...  affects firefox
    ...  subscribe nonexistentuser
    ...  status confirmed
    ... """
    ...     % ff_bug.id
    ... ).encode("ASCII")
    >>> process_email(submit_mail)

The 'affects' and 'status' commands were processed successfully - the
status for the firefox task is now set to CONFIRMED.

    >>> for task in ff_bug.bugtasks:
    ...     if task.product == firefox:
    ...         print(task.status.name)
    ...
    CONFIRMED

The 'subscribe' command failed, and the user is being notified of the
failure in an email.

    >>> from_addr, to_addrs, raw_message = stub.test_emails[-1]
    >>> sent_msg = email.message_from_bytes(raw_message)
    >>> failure_msg, original_msg = sent_msg.get_payload()
    >>> print(failure_msg.get_payload(decode=True).decode("UTF-8"))
    An error occurred while processing a mail you sent to Launchpad's email
    interface.
    <BLANKLINE>
    Failing command:
        subscribe nonexistentuser
    <BLANKLINE>
    Error message:
    <BLANKLINE>
    There's no such person with the specified name or email: nonexistentuser
    <BLANKLINE>
    --
    For more information about using Launchpad by email, see
    https://help.launchpad.net/EmailInterface
    or send an email to help@launchpad.net

We send another email to the same bug, selecting the same bug task. The
email has other two commands - 'security maybe', which is guaranteed to
fail, and 'status triaged' which is OK. 'security' commands cause the
entire email to not to be processed, though.

    >>> transaction.commit()
    >>> submit_mail = (
    ...     """From: Sample Person <test@canonical.com>
    ... To: %s@bugs.canonical.com
    ... Date: Thu Apr 3 11:53:23 BST 2008
    ... Subject: A new bug in Firefox
    ...
    ... Another bug in Firefox.
    ...  affects firefox
    ...  status triaged
    ...  security maybe
    ... """
    ...     % ff_bug.id
    ... ).encode("ASCII")
    >>> process_email(submit_mail)

The status hasn't changed.

    >>> firefox = getUtility(IProductSet).getByName("firefox")
    >>> for task in ff_bug.bugtasks:
    ...     if task.product == firefox:
    ...         print(task.status.name)
    ...
    CONFIRMED

And the sender receives an email to let them know about the failing
'security' command.

    >>> from_addr, to_addrs, raw_message = stub.test_emails[-1]
    >>> sent_msg = email.message_from_bytes(raw_message)
    >>> failure_msg, original_msg = sent_msg.get_payload()
    >>> print(failure_msg.get_payload(decode=True).decode("UTF-8"))
    An error occurred while processing a mail you sent to Launchpad's email
    interface.
    <BLANKLINE>
    Failing command:
        security maybe
    <BLANKLINE>
    Error message:
    <BLANKLINE>
    The 'security' command expects either 'yes' or 'no'.
    <BLANKLINE>
    For example:
    <BLANKLINE>
        security yes
    <BLANKLINE>
    --
    For more information about using Launchpad by email, see
    https://help.launchpad.net/EmailInterface
    or send an email to help@launchpad.net


Terminating command input
-------------------------

To make it possible to submit emails with lines that look like commands
(but aren't), a 'done' statement is provided. When the email parser
encounters a line with that statement, it stops reading any additional
commands.

We send an email with four commands: 'affects', to choose the target,
'importance', to set the importance to high, 'done', to stop reading,
and 'status', which will be ignored.

    >>> submit_mail = (
    ...     """From: Sample Person <test@canonical.com>
    ... To: %s@bugs.canonical.com
    ... Date: Thu Apr 3 11:53:23 BST 2008
    ... Subject: A new bug in Firefox
    ...
    ... Another bug in Firefox.
    ...  affects firefox
    ...  importance high
    ...  done
    ...  status triaged
    ... """
    ...     % ff_bug.id
    ... ).encode("UTF-8")
    >>> process_email(submit_mail)

The target (Firefox) is selected and the importance set, but the status
hasn't changed, since the command to set it came after the 'done' statement.

    >>> for task in ff_bug.bugtasks:
    ...     if task.product == firefox:
    ...         print(task.importance.name)
    ...
    HIGH
    >>> for task in ff_bug.bugtasks:
    ...     if task.product == firefox:
    ...         print(task.status.name)
    ...
    CONFIRMED


Requesting help
---------------

It's possible to ask for the help document for the email interface via
email too. Just send an email to `help@bugs.launchpad.net`.

    >>> submit_mail = b"""From: Sample Person <test@canonical.com>
    ... To: help@bugs.canonical.com
    ... Date: Fri Jun 17 10:20:23 BST 2006
    ... Subject: help
    ...
    ... help
    ... """
    >>> process_email(submit_mail)
    >>> from_addr, to_addrs, raw_message = stub.test_emails[-1]
    >>> print(raw_message.decode("UTF-8"))
    Content-Type: text/plain; charset="utf-8"
    ...
    To: test@canonical.com
    From: help@bugs.launchpad.net
    Subject: Launchpad Bug Tracker Email Interface Help
    ...
    Launchpad's bug tracker sends you email...
    ...

Only mail coming from verified Launchpad users is answered.

    >>> submit_mail = b"""From: Not a User <nobody@nowhere.com>
    ... To: help@bugs.canonical.com
    ... Date: Fri Jun 17 10:20:23 BST 2006
    ... Subject: help
    ...
    ... help
    ... """
    >>> process_email(submit_mail)
    >>> b"nobody@nowhere.com" in stub.test_emails[-1][2]
    False

The help text is taken from the Launchpad help wiki as raw text, and
transformed to be a bit more readable as a plain text document.

    >>> from lp.services.mail.helpers import reformat_wiki_text
    >>> wiki_text = """
    ... = Sample Wiki Text =
    ... # A comment line
    ... Some Text. [[Macro()]]
    ... Don't push the [#boom red button]!
    ... See you in {{{#launchpad}}}.
    ... """  # noqa
    >>> print(reformat_wiki_text(wiki_text))
    = Sample Wiki Text =
    Some Text.
    Don't push the red button!
    See you in {{{#launchpad}}}.


Email attachments
-----------------

Email attachments are stored as bug attachments (provided that they match the
criteria described below).

    >>> def print_attachments(attachments):
    ...     if len(list(attachments)) == 0:
    ...         print("No attachments")
    ...         return
    ...     transaction.commit()
    ...     for attachment in attachments:
    ...         lib = attachment.libraryfile
    ...         print(
    ...             lib.__class__.__name__,
    ...             lib.filename,
    ...             lib.mimetype,
    ...             end=" ",
    ...         )
    ...         print(attachment.type.name)
    ...         print(lib.read().decode("UTF-8"))
    ...
    >>> login("test@canonical.com")
    >>> submit_mail = b"""From: Sample Person <test@canonical.com>
    ... To: new@bugs.canonical.com
    ... Date: Fri Jun 17 10:20:23 BST 2005
    ... Subject: Another bug in Firefox
    ... Content-type: multipart/mixed; boundary="BOUNDARY"
    ...
    ... --BOUNDARY
    ... Content-type: text/plain
    ... Content-transfer-encoding: 7bit
    ...
    ... Found a bug in Firefox. See attached debug output.
    ...
    ...  affects firefox
    ... --BOUNDARY
    ... Content-type: text/plain
    ... Content-disposition: attachment; filename="firefox.log"
    ...
    ... debug text line 1
    ... debug text line 2
    ... debug text line 3
    ... --BOUNDARY"""
    >>>
    >>> process_email(submit_mail)
    >>> print_attachments(get_latest_added_bug().attachments)
    LibraryFileAlias firefox.log text/plain UNSPECIFIED
    debug text line 1
    debug text line 2
    debug text line 3

An email may contain more than one attachment; all of them are stored.

    >>> submit_mail = b"""From: Sample Person <test@canonical.com>
    ... To: new@bugs.canonical.com
    ... Date: Fri Jun 17 10:20:23 BST 2005
    ... Subject: Another bug in Firefox
    ... Content-type: multipart/mixed; boundary="BOUNDARY"
    ...
    ... --BOUNDARY
    ... Content-type: text/plain
    ... Content-transfer-encoding: 7bit
    ...
    ... Found a bug in Firefox. Nothing displayed. See attached files.
    ...
    ...  affects firefox
    ... --BOUNDARY
    ... Content-type: text/plain
    ... Content-disposition: attachment; filename="firefox1.log"
    ...
    ... debug text line 1
    ... debug text line 2
    ... debug text line 3
    ... --BOUNDARY
    ... Content-type: text/html
    ... Content-disposition: attachment; filename="sample.html"
    ...
    ... <html></html>
    ... --BOUNDARY"""
    >>>
    >>> process_email(submit_mail)
    >>> print_attachments(get_latest_added_bug().attachments)
    LibraryFileAlias firefox1.log text/plain UNSPECIFIED
    debug text line 1
    debug text line 2
    debug text line 3
    LibraryFileAlias sample.html text/html UNSPECIFIED
    <html></html>

A bugnotification is sent for each attached file.

    >>> bug_notifications = (
    ...     IStore(BugNotification)
    ...     .find(BugNotification)
    ...     .order_by(Desc(BugNotification.id))[:3]
    ... )
    >>> for bug_notification in bug_notifications:
    ...     print("-------------------")
    ...     print(bug_notification.message.chunks[0].content)
    ...
    -------------------
    Found a bug in Firefox. Nothing displayed. See attached files.
    <BLANKLINE>
     affects firefox
    -------------------
    ** Attachment added: "sample.html"
       http://.../sample.html
    -------------------
    ** Attachment added: "firefox1.log"
       http://.../firefox1.log

If a text/html attachment does not have a filename, it is not stored.
This is the HTML representation of the main text, it is not an
attachment.

    >>> submit_mail = b"""From: Sample Person <test@canonical.com>
    ... To: new@bugs.canonical.com
    ... Date: Fri Jun 17 10:20:23 BST 2005
    ... Subject: Another bug in Firefox
    ... Content-type: multipart/mixed; boundary="BOUNDARY"
    ...
    ... --BOUNDARY
    ... Content-type: text/plain
    ... Content-transfer-encoding: 7bit
    ...
    ... This is an absolutely terrible bug.
    ...
    ...  affects firefox
    ... --BOUNDARY
    ... Content-type: text/html
    ...
    ... <html>
    ...   <BLOCKQUOTE><FONT COLOR="#FF0000">
    ...     This is an absolutely terrible bug.
    ...   </FONT></BLOCKQUOTE>
    ... </html>
    ... --BOUNDARY"""
    >>>
    >>> process_email(submit_mail)
    >>> print_attachments(get_latest_added_bug().attachments)
    No attachments

If the content-disposition header of a message part begins with
"attachment" it is stored as a bug attachment, even if the
content-disposition header does not provide a filename.

    >>> submit_mail = b"""From: Sample Person <test@canonical.com>
    ... To: new@bugs.canonical.com
    ... Date: Fri Jun 17 10:20:23 BST 2005
    ... Subject: Another bug in Firefox
    ... Content-type: multipart/mixed; boundary="BOUNDARY"
    ...
    ... --BOUNDARY
    ... Content-type: text/plain
    ... Content-transfer-encoding: 7bit
    ...
    ... Found a bug in Firefox. Nothing displayed. See attached files.
    ...
    ...  affects firefox
    ... --BOUNDARY
    ... Content-type: text/plain
    ... Content-disposition: attachment
    ...
    ... some more or less important text
    ... --BOUNDARY"""
    >>>
    >>> process_email(submit_mail)
    >>> print_attachments(get_latest_added_bug().attachments)
    LibraryFileAlias unnamed text/plain UNSPECIFIED
    some more or less important text

If the content-disposition header of a message part begins with "inline",
it is stored as a bug attachment, if the header additionally provides
a filename. This ensures that a message part containing debug information
and the content type text/plain is stored as a bug attachment.

    >>> submit_mail = b"""From: Sample Person <test@canonical.com>
    ... To: new@bugs.canonical.com
    ... Date: Fri Jun 17 10:20:23 BST 2005
    ... Subject: Another bug in Firefox
    ... Content-type: multipart/mixed; boundary="BOUNDARY"
    ...
    ... --BOUNDARY
    ... Content-type: text/plain
    ... Content-transfer-encoding: 7bit
    ...
    ... Found a bug in Firefox. See attached debug output.
    ...
    ...  affects firefox
    ... --BOUNDARY
    ... Content-type: text/plain
    ... Content-disposition: inline; filename="firefox.log"
    ...
    ... debug text line 1
    ... debug text line 2
    ... debug text line 3
    ... --BOUNDARY"""
    >>>
    >>> process_email(submit_mail)
    >>> print_attachments(get_latest_added_bug().attachments)
    LibraryFileAlias firefox.log text/plain UNSPECIFIED
    debug text line 1
    debug text line 2
    debug text line 3

If the content-disposition header of a message part begins with "inline",
but has no filename, it is not stored as a bug attachment.

    >>> submit_mail = b"""From: Sample Person <test@canonical.com>
    ... To: new@bugs.canonical.com
    ... Date: Fri Jun 17 10:20:23 BST 2005
    ... Subject: Another bug in Firefox
    ... Content-type: multipart/mixed; boundary="BOUNDARY"
    ...
    ... --BOUNDARY
    ... Content-type: text/plain
    ... Content-transfer-encoding: 7bit
    ...
    ... Found a bug in Firefox. See attached debug output.
    ...
    ...  affects firefox
    ... --BOUNDARY
    ... Content-type: text/plain
    ... Content-disposition: inline
    ...
    ... some text
    ... --BOUNDARY"""
    >>>
    >>> process_email(submit_mail)
    >>> print_attachments(get_latest_added_bug().attachments)
    No attachments

If an attachment has no content disposition header, it is not stored
as a bug attachment.

    >>> submit_mail = b"""From: Sample Person <test@canonical.com>
    ... To: new@bugs.canonical.com
    ... Date: Fri Jun 17 10:20:23 BST 2005
    ... Subject: Another bug in Firefox
    ... Content-type: multipart/mixed; boundary="BOUNDARY"
    ...
    ... --BOUNDARY
    ... Content-type: text/plain
    ... Content-transfer-encoding: 7bit
    ...
    ... Found a bug in Firefox. See attached debug output.
    ...
    ...  affects firefox
    ... --BOUNDARY
    ... Content-type: text/plain
    ...
    ... debug text line 1
    ... debug text line 2
    ... debug text line 3
    ... --BOUNDARY"""
    >>>
    >>> process_email(submit_mail)
    >>> print_attachments(get_latest_added_bug().attachments)
    No attachments

If an attachment has one of the content types application/applefile
(the resource fork of a MacOS file), application/pgp-signature,
application/pkcs7-signature, application/x-pkcs7-signature,
text/x-vcard, application/ms-tnef, it is not stored.

    >>> submit_mail = b"""From: Sample Person <test@canonical.com>
    ... To: new@bugs.canonical.com
    ... Date: Fri Jun 17 10:20:23 BST 2005
    ... Subject: Another bug in Firefox
    ... Content-type: multipart/mixed; boundary="BOUNDARY"
    ...
    ... --BOUNDARY
    ... Content-type: text/plain
    ... Content-transfer-encoding: 7bit
    ...
    ... Found a bug in Firefox.
    ...
    ...  affects firefox
    ... --BOUNDARY
    ... Content-type: application/pgp-signature
    ... Content-disposition: attachment; filename="signature1.asc"
    ...
    ... -----BEGIN PGP SIGNATURE-----
    ... Version: GnuPG v1.4.6 (GNU/Linux)
    ...
    ... 123eetsdtdgdg43e4
    ... -----END PGP SIGNATURE-----
    ... --BOUNDARY
    ... Content-type: application/pkcs7-signature
    ... Content-disposition: attachment; filename="signature2.asc"
    ...
    ... 123eetsdtdgdg43e4
    ... --BOUNDARY
    ... Content-type: application/x-pkcs7-signature
    ... Content-disposition: attachment; filename="signature3.asc"
    ...
    ... 123eetsdtdgdg43e4
    ... --BOUNDARY
    ... Content-type: text/x-vcard
    ... Content-disposition: attachment; filename="sample.person.vcf"
    ...
    ... begin:vcard
    ... n: Person;Sample
    ... tel;work:+1..23..456789
    ... end:vcard
    ... --BOUNDARY
    ... Content-type: application/ms-tnef; name="winmail.dat"
    ...
    ... some useless content
    ... --BOUNDARY"""
    >>>
    >>> process_email(submit_mail)
    >>> print_attachments(get_latest_added_bug().attachments)
    No attachments

    >>> submit_mail = b"""From: Sample Person <test@canonical.com>
    ... To: new@bugs.canonical.com
    ... Date: Fri Jun 17 10:20:23 BST 2005
    ... Subject: Another bug in Firefox
    ... Content-type: multipart/mixed; boundary="BOUNDARY"
    ...
    ... --BOUNDARY
    ... Content-type: text/plain
    ... Content-transfer-encoding: 7bit
    ...
    ... Found a bug in Firefox.
    ...
    ...  affects firefox
    ... --BOUNDARY
    ... Content-type: multipart/appledouble; boundary="SUBBOUNDARY"
    ...
    ... --SUBBOUNDARY
    ... Content-type: application/applefile
    ... Content-disposition: attachment; filename="sampledata"
    ... Content-tranfer-encoding: 7bit
    ...
    ... qwert
    ... --SUBBOUNDARY
    ... Content-type: text/plain
    ... Content-disposition: attachment; filename="sampledata"
    ... Content-tranfer-encoding: 7bit
    ...
    ... some text
    ... --SUBBOUNDARY
    ... --BOUNDARY"""
    >>>
    >>> process_email(submit_mail)
    >>> bug = get_latest_added_bug()
    >>> print_attachments(get_latest_added_bug().attachments)
    LibraryFileAlias sampledata text/plain UNSPECIFIED
    some text

Attachments sent in replies to existing bugs are stored too.

    >>> submit_mail = b"""From: Sample Person <test@canonical.com>
    ... To: 1@bugs.canonical.com
    ... Date: Fri Jun 17 10:20:23 BST 2005
    ... Subject: Another bug in Firefox
    ... Content-type: multipart/mixed; boundary="BOUNDARY"
    ... Message-Id: comment-with-attachment
    ...
    ... --BOUNDARY
    ... Content-type: text/plain
    ... Content-transfer-encoding: 7bit
    ...
    ... See attached data.
    ...
    ... --BOUNDARY
    ... Content-type: text/plain
    ... Content-disposition: attachment; filename="attachment.txt"
    ...
    ... blahhh
    ... --BOUNDARY"""
    >>>
    >>> process_email(submit_mail)
    >>> new_message = getUtility(IMessageSet).get("comment-with-attachment")[
    ...     0
    ... ]
    >>> new_message in set(bug_one.messages)
    True
    >>> print_attachments(new_message.bugattachments)
    LibraryFileAlias attachment.txt text/plain UNSPECIFIED
    blahhh

If an attachment has the content type text/x-diff or text/x-patch,
it is considered to contain a patch.

    >>> submit_mail = b"""From: Sample Person <test@canonical.com>
    ... To: new@bugs.canonical.com
    ... Date: Fri Jun 17 10:20:23 BST 2005
    ... Subject: Another bug in Firefox
    ... Content-type: multipart/mixed; boundary="BOUNDARY"
    ...
    ... --BOUNDARY
    ... Content-type: text/plain
    ... Content-transfer-encoding: 7bit
    ...
    ... Found and fixed a bug in Firefox. See attached patches.
    ...
    ...  affects firefox
    ... --BOUNDARY
    ... Content-type: text/x-diff
    ... Content-disposition: attachment; filename="sourcefile1.diff"
    ...
    ... this should be diff output.
    ... --BOUNDARY
    ... Content-type: text/x-patch
    ... Content-disposition: attachment; filename="sourcefile2.diff"
    ...
    ... this should be another diff output.
    ... --BOUNDARY
    ... Content-type: text/plain
    ... Content-disposition: attachment; filename="logfile"
    ...
    ... this should be log data.
    ... --BOUNDARY"""
    >>>
    >>> process_email(submit_mail)
    >>> print_attachments(get_latest_added_bug().attachments)
    LibraryFileAlias sourcefile1.diff text/x-diff PATCH
    this should be diff output.
    LibraryFileAlias sourcefile2.diff text/x-patch PATCH
    this should be another diff output.
    LibraryFileAlias logfile text/plain UNSPECIFIED
    this should be log data.

Mail attachments without a filename are named "unnamed".

    >>> submit_mail = b"""From: Sample Person <test@canonical.com>
    ... To: new@bugs.canonical.com
    ... Date: Fri Jun 17 10:20:23 BST 2005
    ... Subject: Another bug in Firefox
    ... Content-type: multipart/mixed; boundary="BOUNDARY"
    ...
    ... --BOUNDARY
    ... Content-type: text/plain
    ... Content-transfer-encoding: 7bit
    ...
    ... Found a bug in Firefox. See attached patches.
    ...
    ...  affects firefox
    ... --BOUNDARY
    ... Content-type: text/plain
    ... Content-disposition: attachment
    ...
    ... this could be some log data.
    ... --BOUNDARY
    ... Content-type: text/plain
    ... Content-disposition: attachment
    ...
    ... this could be logfile 2.
    ... --BOUNDARY
    ... Content-type: text/plain
    ... Content-disposition: attachment
    ...
    ... this could be logfile 3.
    ... --BOUNDARY"""
    >>>
    >>> process_email(submit_mail)
    >>> print_attachments(get_latest_added_bug().attachments)
    LibraryFileAlias unnamed text/plain UNSPECIFIED
    this could be some log data.
    LibraryFileAlias unnamed text/plain UNSPECIFIED
    this could be logfile 2.
    LibraryFileAlias unnamed text/plain UNSPECIFIED
    this could be logfile 3.

If an email has two attachments with the same filename, the names are
not changed.

    >>> submit_mail = b"""From: Sample Person <test@canonical.com>
    ... To: new@bugs.canonical.com
    ... Date: Fri Jun 17 10:20:23 BST 2005
    ... Subject: Another bug in Firefox
    ... Content-type: multipart/mixed; boundary="BOUNDARY"
    ...
    ... --BOUNDARY
    ... Content-type: text/plain
    ... Content-transfer-encoding: 7bit
    ...
    ... Found a bug in Firefox. See attached patches.
    ...
    ...  affects firefox
    ... --BOUNDARY
    ... Content-type: text/plain
    ... Content-disposition: attachment; filename="logfile"
    ...
    ... this could be some log data.
    ... --BOUNDARY
    ... Content-type: text/plain
    ... Content-disposition: attachment; filename="logfile"
    ...
    ... this could be some other log data.
    ... --BOUNDARY"""
    >>>
    >>> process_email(submit_mail)
    >>> print_attachments(get_latest_added_bug().attachments)
    LibraryFileAlias logfile text/plain UNSPECIFIED
    this could be some log data.
    LibraryFileAlias logfile text/plain UNSPECIFIED
    this could be some other log data.

Base64 encoded attachments are decoded before being stored.

    >>> submit_mail = b"""From: Sample Person <test@canonical.com>
    ... To: new@bugs.canonical.com
    ... Date: Fri Jun 17 10:20:23 BST 2005
    ... Subject: Another bug in Firefox
    ... Content-type: multipart/mixed; boundary="BOUNDARY"
    ...
    ... --BOUNDARY
    ... Content-type: text/plain
    ... Content-transfer-encoding: 7bit
    ...
    ... Found a bug in Firefox. Attached image file not properly
    ... displayed.
    ...
    ...  affects firefox
    ... --BOUNDARY
    ... Content-Type: image/jpeg
    ... Content-Transfer-Encoding: base64
    ... X-Attachment-Id: f_fcuhv1fz0
    ... Content-Disposition: attachment; filename=image.jpg
    ...
    ... dGhpcyBpcyBub3QgYSByZWFsIEpQRyBmaWxl==
    ... --BOUNDARY"""
    >>>
    >>> process_email(submit_mail)
    >>> print_attachments(get_latest_added_bug().attachments)
    LibraryFileAlias image.jpg image/jpeg UNSPECIFIED
    this is not a real JPG file

Some mail clients append a filename to the content type of attachments.
The content type of the PGP signature is properly detected and thus no bug
attachment is created.

    >>> submit_mail = b"""From: Sample Person <test@canonical.com>
    ... To: new@bugs.canonical.com
    ... Date: Fri Jun 17 10:20:23 BST 2005
    ... Subject: Another bug in Firefox
    ... Content-type: multipart/mixed; boundary="BOUNDARY"
    ...
    ... --BOUNDARY
    ... Content-type: text/plain
    ... Content-transfer-encoding: 7bit
    ...
    ... Found another bug in Firefox.
    ...
    ...
    ...  affects firefox
    ... --BOUNDARY
    ... Content-Type: image/jpeg; name="image.jpg"
    ... Content-Transfer-Encoding: base64
    ... X-Attachment-Id: f_fcuhv1fz0
    ... Content-Disposition: attachment
    ...
    ... dGhpcyBpcyBub3QgYSByZWFsIEpQRyBmaWxl==
    ... --BOUNDARY
    ... Content-type: text/x-diff; name="sourcefile1.diff"
    ... Content-disposition: attachment; filename="sourcefile.diff"
    ...
    ... this should be diff output.
    ... --BOUNDARY
    ... Content-Type: application/pgp-signature; name="signature.asc"
    ... Content-Description: Digital signature
    ... Content-Disposition: inline
    ...
    ... -----BEGIN PGP SIGNATURE-----
    ... Version: GnuPG v1.4.6 (GNU/Linux)
    ...
    ... iD8DBQFH7MnnonjfXui9pOMRAseJAJ0ZHoiLQ+pA2aljwhgszMiImdC1xwCcCdax
    ... oTWHlYEemRSD/E68f9Zsb2s=
    ... =HMT0
    ... -----END PGP SIGNATURE-----
    ...
    ... --BOUNDARY"""
    >>>
    >>> process_email(submit_mail)
    >>> print_attachments(get_latest_added_bug().attachments)
    LibraryFileAlias ... image/jpeg; name="image.jpg" UNSPECIFIED
    this is not a real JPG file
    LibraryFileAlias ... text/x-diff; name="sourcefile1.diff" PATCH
    this should be diff output.


XXX: Add tests for non-ascii mails.
     -- Bjorn Tillenius, 2005-05-20


Reply to a comment on a remote bug
----------------------------------

If someone uses the email interface to reply to a comment which was
imported into Launchpad from a remote bugtracker their reply will be
linked to the remote bug (and eventually pushed to the remote server if
possible).

To demonstrate this we need to set up some example objects. Firstly,
we'll create a new bug on firefox and link it to a remote bug.

    >>> from lp.bugs.interfaces.bugtracker import BugTrackerType
    >>> from lp.bugs.tests.externalbugtracker import new_bugtracker
    >>> from lp.bugs.interfaces.bugwatch import IBugWatchSet
    >>> from lp.registry.interfaces.product import IProductSet

    >>> firefox = getUtility(IProductSet).getByName("firefox")
    >>> no_priv = getUtility(IPersonSet).getByName("no-priv")

    >>> from datetime import datetime, timezone
    >>> from dateutil import tz
    >>> creation_date = datetime(2008, 4, 12, 10, 12, 12, tzinfo=timezone.utc)

We create the initial bug message separately from the bug itself so that
we can ensure that its datecreated field is set correctly. This is
because specifying a datecreated for the bug at creation time doesn't
set the datecreated field of the bug's initial message (see bug
232252).

    >>> initial_bug_message = getUtility(IMessageSet).fromText(
    ...     "A message",
    ...     "The initial message for the bug.",
    ...     no_priv,
    ...     datecreated=creation_date,
    ... )

    >>> bug_with_watch = firefox.createBug(
    ...     CreateBugParams(
    ...         no_priv,
    ...         "New Bug with watch",
    ...         msg=initial_bug_message,
    ...         datecreated=creation_date,
    ...     )
    ... )
    >>> transaction.commit()

    >>> with lp_dbuser():
    ...     from lp.app.interfaces.launchpad import ILaunchpadCelebrities
    ...
    ...     bug_tracker = new_bugtracker(BugTrackerType.TRAC)
    ...     bug_watch = bug_with_watch.addWatch(
    ...         bug_tracker,
    ...         "12345",
    ...         getUtility(ILaunchpadCelebrities).janitor,
    ...     )
    ...

Someone comments on the remote bug and that bug is imported into
Launchpad. We'll simulate this locally rather than using the bug
importing machinery.

    >>> bug_with_watch = getUtility(IBugSet).get(bug_with_watch.id)
    >>> bug_watch = getUtility(IBugWatchSet).get(bug_watch.id)

    >>> comment_date = datetime(
    ...     2008, 5, 19, 16, 19, 12, tzinfo=tz.gettz("Europe/Prague")
    ... )

    >>> initial_mail = (
    ...     """From: test@canonical.com
    ... To: %(bug_id)s@malone-domain
    ... Date: %(date)s
    ... Message-Id: <76543@launchpad.net>
    ... Subject: Bug %(bug_id)s
    ...
    ... Oh, hai!
    ...
    ... I'm in your comments, sending you a message.
    ... """
    ...     % {
    ...         "bug_id": bug_with_watch.id,
    ...         "date": comment_date.strftime("%a %b %d %H:%M:%S %Z %Y"),
    ...     }
    ... ).encode("ASCII")
    >>> message = getUtility(IMessageSet).fromEmail(initial_mail, no_priv)

    >>> bug_message = bug_with_watch.linkMessage(message, bug_watch)

Now someone uses the email interface to respond to the comment that has
been submitted.

    >>> comment_date = datetime(
    ...     2008, 5, 20, 11, 24, 12, tzinfo=tz.gettz("Europe/Prague")
    ... )

    >>> reply_mail = (
    ...     """From: test@canonical.com
    ... To: %(bug_id)s@malone-domain
    ... Date: %(date)s
    ... Message-Id: <1234567890@launchpad.net>
    ... Subject: Replying to your comment about being in my comments
    ... In-Reply-To: %(rfc822msgid)s
    ...
    ... You are not in my comments and I deny categorically that you are
    ... sending me any messages. Foolish cat.
    ... """
    ...     % {
    ...         "bug_id": bug_with_watch.id,
    ...         "date": comment_date.strftime("%a %b %d %H:%M:%S %Z %Y"),
    ...         "rfc822msgid": str(message.rfc822msgid),
    ...     }
    ... ).encode("ASCII")

    >>> process_email(reply_mail)
    >>> transaction.commit()

    >>> [reply_message] = list(bug_with_watch.messages)[-1:]
    >>> print(reply_message.rfc822msgid)
    <1234567890@launchpad.net>

The parent of the new comment is set to the message which was imported
from the remote bugtracker.

    >>> print(reply_message.parent.rfc822msgid)
    <76543@launchpad.net>

The BugMessage instance which links the emailed comment to the bug also
links it to the remote bug via the BugWatch that the original comment
was imported from.

    >>> from lp.bugs.interfaces.bugmessage import IBugMessageSet
    >>> bug_watch = getUtility(IBugWatchSet).get(bug_watch.id)

    >>> reply_bug_message = getUtility(IBugMessageSet).getByBugAndMessage(
    ...     bug_with_watch, reply_message
    ... )

    >>> reply_bug_message.bugwatch == bug_watch
    True

If a user sends in an email which has an In-Reply-To header that points
to an email that isn't linked to the bug, the new message will be linked
to the bug and will not have its bugwatch field set.

    >>> comment_date = datetime(
    ...     2008, 5, 21, 11, 9, 12, tzinfo=tz.gettz("Europe/Prague")
    ... )

    >>> initial_mail = (
    ...     """From: test@canonical.com
    ... To: %(bug_id)s@malone-domain
    ... Date: %(date)s
    ... Message-Id: <912876543@launchpad.net>
    ... Subject: Bug %(bug_id)s
    ...
    ... Yet another mail.
    ... """
    ...     % {
    ...         "bug_id": bug_with_watch.id,
    ...         "date": comment_date.strftime("%a %b %d %H:%M:%S %Z %Y"),
    ...     }
    ... ).encode("ASCII")
    >>> message = getUtility(IMessageSet).fromEmail(initial_mail, no_priv)

    >>> comment_date = datetime(
    ...     2008, 5, 21, 12, 52, 12, tzinfo=tz.gettz("Europe/Prague")
    ... )

    >>> reply_mail = (
    ...     """From: test@canonical.com
    ... To: %(bug_id)s@malone-domain
    ... Date: %(date)s
    ... Message-Id: <asu90ik1234567890@launchpad.net>
    ... Subject: Replying to your comment about being in my comments
    ... In-Reply-To: <912876543@launchpad.net>
    ...
    ... Once again, a reply.
    ... """
    ...     % {
    ...         "bug_id": bug_with_watch.id,
    ...         "date": comment_date.strftime("%a %b %d %H:%M:%S %Z %Y"),
    ...     }
    ... ).encode("ASCII")

    >>> process_email(reply_mail)
    >>> transaction.commit()

    >>> [reply_message] = list(bug_with_watch.messages)[-1:]

    >>> reply_bug_message = getUtility(IBugMessageSet).getByBugAndMessage(
    ...     bug_with_watch, reply_message
    ... )

    >>> print(reply_bug_message.bugwatch)
    None
