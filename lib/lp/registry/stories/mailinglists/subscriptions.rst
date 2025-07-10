====================================
Mailing list subscription management
====================================

Teams can have mailing lists associated with them, and a member of a
team with a usable mailing list can subscribe to that list. A person
can subscribe to a mailing list using any of their email addresses, or a
dynamic subscription which uses whichever email address is their
preferred address at a given time.

Non-team members can request a subscription to a mailing list at the
same time as they sign up for a new team.  Their list membership is
approved at the same time that they are approved for the team.


Setup
=====

Carlos is a member of four teams: admins, rosetta-admins, testing-spanish-team
and ubuntu-translators.  He has two email addresses, one of which is his
preferred email address.  Both the admins and rosetta-admins teams are given
mailing lists but only admins will actually use its mailing list as its
contact address.

    >>> from zope.security.management import newInteraction, endInteraction
    >>> from lp.testing.factory import LaunchpadObjectFactory

    >>> newInteraction()
    >>> factory = LaunchpadObjectFactory()
    >>> factory.makeTeamAndMailingList("admins", "foo")  # doctest: +ELLIPSIS
    (<Person admins (Launchpad Administrators)>,
    <MailingList for team "admins"; status=ACTIVE;
    address=admins@lists.launchpad.test at ...>)
    >>> endInteraction()

    >>> newInteraction()
    >>> factory = LaunchpadObjectFactory()
    >>> factory.makeTeamAndMailingList(
    ...     "rosetta-admins", "foo"
    ... )  # doctest: +ELLIPSIS
    (<Person rosetta-admins (Rosetta Administrators)>,
    <MailingList for team "rosetta-admins"; status=ACTIVE;
    address=rosetta-admins@lists.launchpad.test at ...>)
    >>> endInteraction()

    >>> admin_browser.open("http://launchpad.test/~admins/+edit")
    >>> admin_browser.getLink(url="+contactaddress").click()
    >>> admin_browser.getControl("The Launchpad mailing list").selected = True
    >>> admin_browser.getControl("Change").click()

Carlos requests a mailing list for testing-spanish-team but it will not
actually be approved (new mailing lists cannot be created).

    >>> browser = setupBrowser(auth="Basic carlos@canonical.com:test")
    >>> browser.open(
    ...     "http://launchpad.test/~testing-spanish-team/+mailinglist"
    ... )
    >>> print(
    ...     extract_text(find_tag_by_id(browser.contents, "no_mailing_list"))
    ... )
    Launchpad no longer supports the creation of new mailing lists.
    Read more about it here.


Subscribing
===========

Any team member can join the mailing list.

    >>> admin_browser.open("http://launchpad.test/~rosetta-admins/+addmember")
    >>> admin_browser.getControl("New member").value = "no-team-memberships"
    >>> admin_browser.getControl("Add Member").click()

    >>> from lp.testing.pages import setupBrowserFreshLogin
    >>> from zope.component import getUtility
    >>> from lp.registry.interfaces.person import IPersonSet
    >>> login(ANONYMOUS)
    >>> person = getUtility(IPersonSet).getByEmail(
    ...     "no-team-memberships@test.com"
    ... )
    >>> logout()
    >>> no_team_browser = setupBrowserFreshLogin(person)

    >>> no_team_browser.open(
    ...     "http://launchpad.test/people/+me/+editmailinglists"
    ... )
    >>> rosetta_admins = no_team_browser.getControl(
    ...     name="field.subscription.rosetta-admins"
    ... )
    >>> rosetta_admins.displayOptions
    ['Preferred address', "Don't subscribe", 'no-team-memberships@test.com']


Subscription management
=======================

To subscribe to a mailing list, Carlos uses his subscription management
screen, which shows a subscription control for the mailing lists of every team
he's a member of.  Mailing lists show up in this list regardless of whether
it's currently the team contact method.

    >>> login(ANONYMOUS)
    >>> carlos = getUtility(IPersonSet).getByName("carlos")
    >>> logout()
    >>> carlos_browser = setupBrowserFreshLogin(carlos)
    >>> carlos_browser.open("http://launchpad.test/~carlos")
    >>> carlos_browser.getLink(url="+editmailinglists").click()

    >>> from lp.services.helpers import backslashreplace
    >>> print(backslashreplace(carlos_browser.title))
    Change your mailing list subscriptions...

    >>> admins = carlos_browser.getControl(name="field.subscription.admins")
    >>> rosetta_admins = carlos_browser.getControl(
    ...     name="field.subscription.rosetta-admins"
    ... )

    >>> admins.displayOptions
    ['Preferred address', "Don't subscribe",
     'carlos@canonical.com', 'carlos@test.com']

    >>> print(admins.value)
    ["Don't subscribe"]
    >>> print(rosetta_admins.value)
    ["Don't subscribe"]

However, testing-spanish-team's list doesn't show up because its creation has
not been completed (specifically, Mailman hasn't constructed it yet).

    >>> carlos_browser.getControl(
    ...     name="field.subscription.testing-spanish-team"
    ... )
    Traceback (most recent call last):
    ...
    LookupError: name ...'field.subscription.testing-spanish-team'
    ...

Carlos can subscribe to a list using his preferred email address.  Such
subscriptions will track changes to his preferred address without requiring
him to update his subscription.  So this is not the same as subscribing
explicitly with whatever is his preferred email address.

    >>> admins = carlos_browser.getControl(name="field.subscription.admins")
    >>> admins.value = ["Preferred address"]
    >>> carlos_browser.getControl("Update Subscriptions").click()

    >>> print_feedback_messages(carlos_browser.contents)
    Subscriptions updated.

    >>> admins = carlos_browser.getControl(name="field.subscription.admins")
    >>> rosetta_admins = carlos_browser.getControl(
    ...     name="field.subscription.rosetta-admins"
    ... )
    >>> print(admins.value)
    ['Preferred address']
    >>> print(rosetta_admins.value)
    ["Don't subscribe"]

Carlos can subscribe to a list using any of his validated addresses
explicitly.

    >>> admins.value = ["carlos@canonical.com"]
    >>> rosetta_admins.value = ["carlos@test.com"]
    >>> carlos_browser.getControl("Update Subscriptions").click()

    >>> admins = carlos_browser.getControl(name="field.subscription.admins")
    >>> rosetta_admins = carlos_browser.getControl(
    ...     name="field.subscription.rosetta-admins"
    ... )
    >>> print(admins.value)
    ['carlos@canonical.com']
    >>> print(rosetta_admins.value)
    ['carlos@test.com']

He can switch from one address to another, or from a specific address
to the preferred address.

    >>> admins.value = ["Preferred address"]
    >>> rosetta_admins.value = ["carlos@canonical.com"]
    >>> carlos_browser.getControl("Update Subscriptions").click()

    >>> admins = carlos_browser.getControl(name="field.subscription.admins")
    >>> rosetta_admins = carlos_browser.getControl(
    ...     name="field.subscription.rosetta-admins"
    ... )
    >>> print(admins.value)
    ['Preferred address']
    >>> print(rosetta_admins.value)
    ['carlos@canonical.com']

Finally, he can unsubscribe from any mailing list by setting the subscription
menu item to "Don't subscribe".

    >>> admins = carlos_browser.getControl(name="field.subscription.admins")
    >>> rosetta_admins = carlos_browser.getControl(
    ...     name="field.subscription.rosetta-admins"
    ... )
    >>> admins.value = ["Don't subscribe"]
    >>> rosetta_admins.value = ["Don't subscribe"]
    >>> carlos_browser.getControl("Update Subscriptions").click()

    >>> admins = carlos_browser.getControl(name="field.subscription.admins")
    >>> rosetta_admins = carlos_browser.getControl(
    ...     name="field.subscription.rosetta-admins"
    ... )
    >>> print(admins.value)
    ["Don't subscribe"]
    >>> print(rosetta_admins.value)
    ["Don't subscribe"]


Subscription during team sign up
================================

Jdub is only a member of the ubuntu team.  He can request to be placed
on another team's mailing list at the same time that he requests
membership on the team.

First we need to confirm that the desired team has a list to subscribe
to.  We will use Carlos, as he is an administrator for the Rosetta
Admins team, and he should know if the list is available.

    >>> carlos_browser.open("http://launchpad.test/~carlos")
    >>> carlos_browser.getLink(url="+editmailinglists").click()
    >>> print(backslashreplace(carlos_browser.title))
    Change your mailing list subscriptions...

    >>> rosetta_admins = carlos_browser.getControl(
    ...     name="field.subscription.rosetta-admins"
    ... )
    >>> rosetta_admins.displayOptions
    ['Preferred address', "Don't subscribe",
     'carlos@canonical.com', 'carlos@test.com']

Now Jdub can apply for team membership and mailing list access.

    >>> browser = setupBrowser(auth="Basic jeff.waugh@ubuntulinux.com:test")
    >>> browser.open("http://launchpad.test/~rosetta-admins")
    >>> browser.getLink("Join the team").click()
    >>> browser.url
    'http://launchpad.test/~rosetta-admins/+join'

    >>> browser.getControl(name="field.mailinglist_subscribe").value = True
    >>> browser.getControl(name="field.actions.join").click()
    >>> browser.url
    'http://launchpad.test/~rosetta-admins'

    >>> for tag in find_tags_by_class(browser.contents, "informational"):
    ...     print(tag.decode_contents())
    ...
    Your request to join Rosetta Administrators is awaiting approval.
    Your mailing list subscription is awaiting approval.

Jdub hasn't been approved for the team yet, so he is not subscribed to
the list.  The list does not show up on his Subscription Management
screen.

    >>> login(ANONYMOUS)
    >>> jdub = getUtility(IPersonSet).getByName("jdub")
    >>> logout()
    >>> jdub_browser = setupBrowserFreshLogin(jdub)
    >>> jdub_browser.open("http://launchpad.test/~jdub")
    >>> jdub_browser.getLink(url="+editmailinglists").click()
    >>> print(jdub_browser.title)
    Change your mailing list subscriptions...

    >>> jdub_browser.getControl(name="field.subscription.rosetta-admins")
    Traceback (most recent call last):
    ...
    LookupError: name ...'field.subscription.rosetta-admins'
    ...

Jdub will become a member of the team's mailing list as soon as he has
been approved for the team.

    >>> admin_browser.open("http://launchpad.test/~rosetta-admins")
    >>> admin_browser.getLink("All members").click()
    >>> admin_browser.getLink(url="/~rosetta-admins/+member/jdub").click()
    >>> print(admin_browser.url)
    http://launchpad.test/~rosetta-admins/+member/jdub
    >>> admin_browser.getControl(name="approve").click()

His mailing list subscription is now available to be managed.

    >>> jdub_browser.open("http://launchpad.test/~jdub")
    >>> jdub_browser.getLink(url="+editmailinglists").click()
    >>> print(jdub_browser.title)
    Change your mailing list subscriptions...

    >>> rosetta_team = jdub_browser.getControl(
    ...     name="field.subscription.rosetta-admins"
    ... )

    >>> rosetta_team.displayOptions
    ['Preferred address', "Don't subscribe", 'jeff.waugh@ubuntulinux.com']

Jdub's mailing list preferences are preserved when he leaves the team.
When he requests to re-join, the option to re-subscribe to the mailing
list is not presented.

    >>> browser.open("http://launchpad.test/~rosetta-admins/+leave")
    >>> browser.getControl(name="field.actions.leave").click()

    >>> browser.open("http://launchpad.test/~rosetta-admins")
    >>> browser.getLink("Join the team").click()
    >>> print(browser.url)
    http://launchpad.test/~rosetta-admins/+join

    >>> browser.getControl(name="mailinglist_subscribe")
    Traceback (most recent call last):
    ...
    LookupError: name ...'mailinglist_subscribe'
    ...

Of course, the option to subscribe to the mailing list isn't present
for teams that don't have mailing lists.

    >>> browser.open("http://launchpad.test/~testing-spanish-team")
    >>> browser.getLink("Join the team").click()
    >>> print(browser.url)
    http://launchpad.test/~testing-spanish-team/+join

    >>> browser.getControl(name="mailinglist_subscribe")
    Traceback (most recent call last):
    ...
    LookupError: name ...'mailinglist_subscribe'
    ...

And the option is also missing from the sign-up pages of teams that
have restricted membership.  (Note that we can only see the join page
if we visit the URL directly, as the link is not present on the Team
Overview.)

    >>> browser.open("http://launchpad.test/~launchpad/+join")
    >>> print(browser.url)
    http://launchpad.test/~launchpad/+join

    >>> browser.getControl(name="mailinglist_subscribe")
    Traceback (most recent call last):
    ...
    LookupError: name ...'mailinglist_subscribe'
    ...


Team page quick-links
=====================

Links to subscribe and unsubscribe from the mailing lists are also
available from the team's Overview page.

Carlos can see the subscribe link on the admin team's Overview
page, because he is not subscribed to the team mailing list.

    >>> carlos_browser.open("http://launchpad.test/~admins")
    >>> carlos_browser.getLink("Subscribe to mailing list").click()
    >>> print(carlos_browser.url)
    http://launchpad.test/~carlos/+editmailinglists

The unsubscribe link is visible for the rosetta admins team, which
has an active mailing list.

    # Subscribe to the list using the normal technique.
    >>> carlos_browser.open("http://launchpad.test/~carlos")
    >>> carlos_browser.getLink(url="+editmailinglists").click()
    >>> rosetta_admins = carlos_browser.getControl(
    ...     name="field.subscription.rosetta-admins"
    ... )
    >>> rosetta_admins.value = ["Preferred address"]
    >>> carlos_browser.getControl("Update Subscriptions").click()
    >>> print(rosetta_admins.value)
    ['Preferred address']
    >>> for tag in find_tags_by_class(
    ...     carlos_browser.contents, "informational"
    ... ):
    ...     print(tag.decode_contents())
    Subscriptions updated.

    >>> carlos_browser.open("http://launchpad.test/~rosetta-admins")
    >>> carlos_browser.getControl("Unsubscribe")
    <SubmitControl name='unsubscribe' type='submit'>

Clicking the link will unsubscribe you from the list immediately.

    >>> carlos_browser.getControl("Unsubscribe").click()
    >>> print_feedback_messages(carlos_browser.contents)
    You have been unsubscribed from the team mailing list.

    >>> carlos_browser.open("http://launchpad.test/~rosetta-admins")
    >>> print(
    ...     extract_text(
    ...         find_tag_by_id(carlos_browser.contents, "mailing-lists")
    ...     )
    ... )
    Mailing list...
    Subscribe to mailing list...

The Ubuntu translators team, which does not have any lists configured,
does not show either link.

    >>> carlos_browser.open("http://launchpad.test/~ubuntu-translators")
    >>> print(
    ...     extract_text(
    ...         find_portlet(carlos_browser.contents, "Mailing list")
    ...     )
    ... )
    Mailing list
    Launchpad no longer supports the creation of new mailing lists.
    Read more about it here.

    >>> carlos_browser.getLink("Subscribe")
    Traceback (most recent call last):
    ...
    zope.testbrowser.browser.LinkNotFoundError

    >>> carlos_browser.getLink("Unsubscribe")
    Traceback (most recent call last):
    ...
    zope.testbrowser.browser.LinkNotFoundError


Team page subscribers link
==========================

Team administrators can see a link to a page listing the team's
mailing list subscribers, if there is an active mailing list.  The
rosetta admins team has such a list and carlos is the owner.

    >>> carlos_browser.open("http://launchpad.test/~rosetta-admins")
    >>> print(
    ...     extract_text(
    ...         find_portlet(carlos_browser.contents, "Mailing list")
    ...     )
    ... )
    Mailing list
    rosetta-admins@lists.launchpad.test
    Policy: You must be a team member to subscribe to the team mailing list.
    Subscribe to mailing list
    View public archive
    View subscribers...

The mailing list for Rosetta Admins has no subscribers.
(Jeff Waugh has asked to subscribe but he's not considered a subscriber
because his membership on Rosetta Admins hasn't been approved)

    >>> carlos_browser.getLink("View subscribers").click()
    >>> print(carlos_browser.title)
    Mailing list subscribers for the Rosetta Administrators team...

    >>> print(
    ...     extract_text(
    ...         find_tag_by_id(carlos_browser.contents, "subscribers")
    ...     )
    ... )
    Nobody has subscribed to this team's mailing list yet.

If it had subscribers, though, they'd be shown on that page, in a batched
list.

    # Forge two new subscribers to the team's mailing list.
    >>> from lp.services.config import config
    >>> config.push(
    ...     "default-batch-size",
    ...     """
    ... [launchpad]
    ... default_batch_size: 1
    ... """,
    ... )
    >>> login("foo.bar@canonical.com")

    >>> person_set = getUtility(IPersonSet)
    >>> jdub = person_set.getByName("jdub")
    >>> mark = person_set.getByName("mark")
    >>> salgado = person_set.getByName("salgado")
    >>> jordi = person_set.getByName("jordi")
    >>> rosetta_admins = person_set.getByName("rosetta-admins")
    >>> ignored = rosetta_admins.addMember(salgado, reviewer=mark)
    >>> rosetta_admins.mailing_list.subscribe(salgado)
    >>> ignored = rosetta_admins.addMember(jordi, reviewer=mark)
    >>> rosetta_admins.mailing_list.subscribe(jordi)
    >>> logout()
    >>> carlos_browser.reload()
    >>> print(
    ...     extract_text(
    ...         find_tag_by_id(carlos_browser.contents, "subscribers")
    ...     )
    ... )
    The following people are subscribed...
    Guilherme Salgado
    1 of 2 results...

    >>> carlos_browser.getLink("Next").click()
    >>> print(
    ...     extract_text(
    ...         find_tag_by_id(carlos_browser.contents, "subscribers")
    ...     )
    ... )
    The following people are subscribed...
    Jordi Mallach
    2 of 2 results...

    >>> config_data = config.pop("default-batch-size")

If the team has no mailing list, then the archive and subscribers
links are not present.

    >>> admin_browser.open("http://launchpad.test/~commercial-admins")
    >>> summary_content = extract_text(
    ...     find_portlet(admin_browser.contents, "Mailing list")
    ... )
    >>> "Mailing list archive" in summary_content
    False
    >>> "Mailing list subscribers" in summary_content
    False


Mailing list auto-subscription settings
=======================================

Launchpad may automatically subscribe a person to a team's mailing
list based on a setting in the person's Email preferences page.

    >>> carlos_browser.open("http://launchpad.test/~carlos")
    >>> carlos_browser.getLink(url="+editmailinglists").click()
    >>> print(backslashreplace(carlos_browser.title))
    Change your mailing list subscriptions...

Carlos's default setting, 'Ask me when I join a team', is still in place.

    >>> print_radio_button_field(
    ...     carlos_browser.contents, "mailing_list_auto_subscribe_policy"
    ... )
    ( ) Never subscribe to mailing lists
    (*) Ask me when I join a team
    ( ) Always subscribe me to mailing lists

Carlos can update the value at any time using his Email Preferences
page.

    # A convenient helper for setting and submitting a new
    # auto-subscribe policy.
    >>> def set_autosubscribe_policy_and_submit(newvalue, current_browser):
    ...     control = current_browser.getControl(
    ...         name="field.mailing_list_auto_subscribe_policy"
    ...     )
    ...     control.value = [newvalue]
    ...     current_browser.getControl("Update Policy").click()
    ...     print_radio_button_field(
    ...         current_browser.contents, "mailing_list_auto_subscribe_policy"
    ...     )
    ...

    >>> original_value = carlos_browser.getControl(
    ...     name="field.mailing_list_auto_subscribe_policy"
    ... ).value.pop()

    >>> set_autosubscribe_policy_and_submit("ALWAYS", carlos_browser)
    ( ) Never subscribe to mailing lists
    ( ) Ask me when I join a team
    (*) Always subscribe me to mailing lists

    # We only need to check this once.
    >>> print_feedback_messages(carlos_browser.contents)
    Your auto-subscribe policy has been updated.

    >>> set_autosubscribe_policy_and_submit("NEVER", carlos_browser)
    (*) Never subscribe to mailing lists
    ( ) Ask me when I join a team
    ( ) Always subscribe me to mailing lists

    >>> set_autosubscribe_policy_and_submit("ON_REGISTRATION", carlos_browser)
    ( ) Never subscribe to mailing lists
    (*) Ask me when I join a team
    ( ) Always subscribe me to mailing lists

Updating the value twice has no adverse affect.

    # Restores the original value while performing the test.
    >>> assert original_value == "ON_REGISTRATION"
    >>> set_autosubscribe_policy_and_submit(original_value, carlos_browser)
    ( ) Never subscribe to mailing lists
    (*) Ask me when I join a team
    ( ) Always subscribe me to mailing lists

Regardless of this setting, users will always receive a notification when a
team they are a member of creates a new mailing list.  This notification
offers them to join the new mailing list.  This page informs them of this
behaviour.

    >>> print(
    ...     extract_text(
    ...         find_tag_by_id(carlos_browser.contents, "notification-info")
    ...     )
    ... )
    When a team you are a member of creates a new mailing list, you will
    receive an email notification offering you the opportunity to join the new
    mailing list. Launchpad can also automatically subscribe you to a team's
    mailing list whenever you join a team.

These settings also effect what a user sees when they go to join a new
team.  The 'Team Join' page has a checkbox that allows a user to sign
up for the team mailing list at the same time as joining the
team. Users who have chosen the 'On registration' or 'Always'
subscription settings will see the box checked by default.

    >>> login(ANONYMOUS)
    >>> james = getUtility(IPersonSet).getByEmail(
    ...     "james.blackwell@ubuntulinux.com"
    ... )
    >>> logout()
    >>> browser = setupBrowserFreshLogin(james)
    >>> browser.open("http://launchpad.test/~jblack")
    >>> browser.getLink(url="+editmailinglists").click()
    >>> print_radio_button_field(
    ...     browser.contents, "mailing_list_auto_subscribe_policy"
    ... )
    ( ) Never subscribe to mailing lists
    (*) Ask me when I join a team
    ( ) Always subscribe me to mailing lists

    >>> browser.open("http://launchpad.test/~rosetta-admins")
    >>> browser.getLink("Join the team").click()
    >>> print(browser.url)
    http://launchpad.test/~rosetta-admins/+join

    >>> print(browser.getControl(name="field.mailinglist_subscribe").value)
    True

    # Change James' setting
    >>> browser.open("http://launchpad.test/~jblack")
    >>> browser.getLink(url="+editmailinglists").click()
    >>> set_autosubscribe_policy_and_submit("ALWAYS", browser)
    ( ) Never subscribe to mailing lists
    ( ) Ask me when I join a team
    (*) Always subscribe me to mailing lists

    >>> browser.open("http://launchpad.test/~rosetta-admins")
    >>> browser.getLink("Join the team").click()
    >>> print(browser.getControl(name="field.mailinglist_subscribe").value)
    True

Users who have chosen to never be auto-subscribed to mailing
lists will not have the box checked.

    # Change James' setting
    >>> browser.open("http://launchpad.test/~jblack")
    >>> browser.getLink(url="+editmailinglists").click()
    >>> set_autosubscribe_policy_and_submit("NEVER", browser)
    (*) Never subscribe to mailing lists
    ( ) Ask me when I join a team
    ( ) Always subscribe me to mailing lists

    >>> browser.open("http://launchpad.test/~rosetta-admins")
    >>> browser.getLink("Join the team").click()
    >>> print(
    ...     bool(browser.getControl(name="field.mailinglist_subscribe").value)
    ... )
    False

    # Restore James' setting.
    >>> browser.open("http://launchpad.test/~jblack")
    >>> browser.getLink(url="+editmailinglists").click()
    >>> set_autosubscribe_policy_and_submit("ON_REGISTRATION", browser)
    ( ) Never subscribe to mailing lists
    (*) Ask me when I join a team
    ( ) Always subscribe me to mailing lists
