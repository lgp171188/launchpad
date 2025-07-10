======================
Mailing list lifecycle
======================

Every team in Launchpad can have a mailing list, and every mailing list is
associated with exactly one team.


Hosted mailing list
===================

The owner of Landscape Developers cannot create a new mailing list.

    >>> from zope.security.management import newInteraction, endInteraction
    >>> from lp.testing.factory import LaunchpadObjectFactory

    >>> browser = setupBrowser(auth="Basic test@canonical.com:test")
    >>> browser.open(
    ...     "http://launchpad.test/~landscape-developers/+mailinglist"
    ... )
    >>> from lp.services.helpers import backslashreplace
    >>> print(backslashreplace(browser.title))
    Mailing list configuration : \u201cLandscape Developers\u201d team
    >>> print(
    ...     extract_text(find_tag_by_id(browser.contents, "no_mailing_list"))
    ... )
    Launchpad no longer supports the creation of new mailing lists.
    Read more about it here.

    >>> browser.open("http://launchpad.test/~landscape-developers")
    >>> print(browser.title)
    Landscape Developers in Launchpad

    # Create a new mailing list for testing purposes.
    >>> newInteraction()
    >>> factory = LaunchpadObjectFactory()
    >>> factory.makeTeamAndMailingList(
    ...     "landscape-developers", "test"
    ... )  # doctest: +ELLIPSIS
    (<Person landscape-developers (Landscape Developers)>,
    <MailingList for team "landscape-developers"; status=ACTIVE;
    address=landscape-developers@lists.launchpad.test at ...>)
    >>> endInteraction()

    >>> def mailing_list_status_message(contents):
    ...     """Find out if a mailing list is in an unusual state."""
    ...     tag = find_tag_by_id(contents, "mailing_list_status_message")
    ...     if tag:
    ...         return extract_text(tag.strong)
    ...     else:
    ...         return ""
    ...

Mailman helper function.

    >>> from lp.registry.tests import mailinglists_helper
    >>> def act():
    ...     login("foo.bar@canonical.com")
    ...     mailinglists_helper.mailman.act()
    ...     transaction.commit()
    ...     logout()
    ...

Once the team's mailing list is active, there is a link to its archive.  This
is true even if no messages have yet been posted to the mailing list (since
the archiver will display an informative message to that effect).

    >>> browser.open("http://launchpad.test/~landscape-developers")
    >>> print(
    ...     extract_link_from_tag(
    ...         find_tag_by_id(browser.contents, "mailing-list-archive")
    ...     )
    ... )
    http://lists.launchpad.test/landscape-developers

The team's overview page also displays the posting address.

    >>> print(
    ...     extract_text(
    ...         find_tag_by_id(
    ...             browser.contents, "mailing-list-posting-address"
    ...         )
    ...     )
    ... )
    landscape-developers@lists.launchpad.test

Now that the mailing list is active, it can be used as the team's contact
address.

    >>> from lp.testing.pages import strip_label

    >>> browser.getLink(url="+mailinglist").click()
    >>> print(
    ...     extract_text(
    ...         find_tag_by_id(
    ...             browser.contents, "mailing_list_not_contact_address"
    ...         )
    ...     )
    ... )
    The mailing list is not set as the team contact address. You can
    set it.

    >>> browser.getLink(url="+contactaddress").click()
    >>> browser.getControl("The Launchpad mailing list").selected = True
    >>> browser.getControl("Change").click()

    >>> browser.getLink(url="+contactaddress").click()
    >>> control = browser.getControl(name="field.contact_method")
    >>> [strip_label(label) for label in control.displayValue]
    ['The Launchpad mailing list for this team...]

The mailing list's configuration screen is also now available.

    >>> print(browser.getLink(url="+mailinglist").url)
    http://launchpad.test/~landscape-developers/+mailinglist

When the mailing list is not the team's contact address, the mailing
list configuration screen displays a message to this effect.

    >>> browser.getControl("Each member individually").selected = True
    >>> browser.getControl("Change").click()

    >>> browser.getLink(url="+mailinglist").click()
    >>> print(
    ...     extract_text(
    ...         find_tag_by_id(
    ...             browser.contents, "mailing_list_not_contact_address"
    ...         )
    ...     )
    ... )
    The mailing list is not set as the team contact address. You can
    set it.

The message contains a link to the contact address screen.

    >>> browser.getLink("set it").click()
    >>> browser.getControl("The Launchpad mailing list").selected = True
    >>> browser.getControl("Change").click()
    >>> print(browser.title)
    Landscape Developers in Launchpad

When the mailing list is the team's contact address, the message does
not show up.

    >>> browser.getLink(url="+mailinglist").click()
    >>> find_tag_by_id(
    ...     browser.contents, "mailing_list_not_contact_address"
    ... ) is None
    True

The contact address is now set to the mailing list address.

    >>> browser.goBack()
    >>> browser.getLink(url="+contactaddress").click()
    >>> control = browser.getControl(name="field.contact_method")
    >>> [strip_label(label) for label in control.displayValue]
    ['The Launchpad mailing list for this team -
      landscape-developers@lists.launchpad.test']


Deactivating and reactivating lists
===================================

An active mailing list can be deactivated. If the deactivated mailing
list was the team contact method, the contact method will be changed
to 'each user individually'.

    >>> browser.open(
    ...     "http://launchpad.test/~landscape-developers/+mailinglist"
    ... )
    >>> browser.getControl("Deactivate this Mailing List").click()
    >>> browser.getLink(url="+contactaddress").click()
    >>> control = browser.getControl(name="field.contact_method")
    >>> [strip_label(label) for label in control.displayValue]
    ['Each member individually']

    >>> act()
    >>> browser.open(
    ...     "http://launchpad.test/~landscape-developers/+mailinglist"
    ... )
    >>> print(mailing_list_status_message(browser.contents))
    This team's mailing list has been deactivated.

A deactivated mailing list still has a link to its archive, because archives
are never deleted.

    >>> browser.open("http://launchpad.test/~landscape-developers")
    >>> print(
    ...     extract_link_from_tag(
    ...         find_tag_by_id(browser.contents, "mailing-list-archive")
    ...     )
    ... )
    http://lists.launchpad.test/landscape-developers

An inactive mailing list cannot be reactivated.

    >>> browser.getLink(url="+mailinglist").click()
    >>> print(
    ...     extract_text(
    ...         find_tag_by_id(browser.contents, "mailing_list_reactivate")
    ...     )
    ... )
    Launchpad no longer supports the reactivation of mailing lists.
    Read more about it here.

The archive link is only available for public mailing lists as shown above,
and for private mailing lists for team members.

    >>> from lp.registry.interfaces.person import PersonVisibility
    >>> login("foo.bar@canonical.com")
    >>> bassists = mailinglists_helper.new_team("bassists")
    >>> bassists.visibility = PersonVisibility.PRIVATE
    >>> bassists_list = mailinglists_helper.new_list_for_team(bassists)
    >>> logout()

The owner of the list can see archive link.

    >>> user_browser.open("http://launchpad.test/~bassists")
    >>> print(
    ...     extract_link_from_tag(
    ...         find_tag_by_id(user_browser.contents, "mailing-list-archive")
    ...     )
    ... )
    http://lists.launchpad.test/bassists

Anonymous users cannot see the link, because they cannot even see the
private team.

    >>> anon_browser.open("http://launchpad.test/~bassists")
    Traceback (most recent call last):
    ...
    zope.publisher.interfaces.NotFound: Object: <...>, name: '~bassists'

The same is true for normal users who are not team members.

    >>> browser.open("http://launchpad.test/~bassists")
    Traceback (most recent call last):
    ...
    zope.publisher.interfaces.NotFound: Object: <...>, name: '~bassists'

Members who are not owners can see the link.

    >>> cprov_browser = setupBrowser(
    ...     auth="Basic celso.providelo@canonical.com:test"
    ... )
    >>> cprov_browser.open("http://launchpad.test/~bassists")
    Traceback (most recent call last):
    ...
    zope.publisher.interfaces.NotFound: Object: <...>, name: '~bassists'

    >>> admin_browser.open("http://launchpad.test/~bassists/+addmember")
    >>> admin_browser.getControl("New member").value = "cprov"
    >>> admin_browser.getControl("Add Member").click()

    >>> cprov_browser.open("http://launchpad.test/~bassists")
    >>> print(
    ...     extract_link_from_tag(
    ...         find_tag_by_id(cprov_browser.contents, "mailing-list-archive")
    ...     )
    ... )
    http://lists.launchpad.test/bassists

Admins who are not members of the team can see the link too.

    >>> admin_browser.open("http://launchpad.test/~bassists")
    >>> print(
    ...     extract_link_from_tag(
    ...         find_tag_by_id(admin_browser.contents, "mailing-list-archive")
    ...     )
    ... )
    http://lists.launchpad.test/bassists


Purge permissions
=================

A mailing list may be 'purged' when it is in one of several safe states.
By 'safe' we mean that there are no artifacts of the mailing list on the
Mailman side that need to be preserved.  This is not guaranteed by the
code, except by the state of the mailing list, so if for example we want
to delete the archives of an INACTIVE list, this must be done manually.

    # Create a team without a mailing list owned by no-priv so the owner of
    # the team has no additional privileges.
    >>> login("foo.bar@canonical.com")
    >>> team = mailinglists_helper.new_team("aardvarks")
    >>> logout()

    >>> from zope.component import getUtility
    >>> from lp.registry.interfaces.mailinglist import IMailingListSet
    >>> def print_list_state(team_name="aardvarks"):
    ...     login("foo.bar@canonical.com")
    ...     mailing_list = getUtility(IMailingListSet).get(team_name)
    ...     print(mailing_list.status.name)
    ...     logout()
    ...

The team owner cannot create new mailing lists.

    >>> user_browser.open("http://launchpad.test/~aardvarks/+mailinglist")
    >>> print(
    ...     extract_text(
    ...         find_tag_by_id(user_browser.contents, "no_mailing_list")
    ...     )
    ... )
    Launchpad no longer supports the creation of new mailing lists.
    Read more about it here.

    # Create a mailing list to test the deletion, purging, and reactivation
    # options.
    >>> newInteraction()
    >>> mailinglists_helper.new_list_for_team(team)  # doctest: +ELLIPSIS
    <MailingList for team "aardvarks"; status=ACTIVE;
    address=aardvarks@lists.launchpad.test at ...>
    >>> endInteraction()

The team owner can purge or deactivate mailing lists.

    >>> user_browser.open("http://launchpad.test/~aardvarks/+mailinglist")
    >>> user_browser.getControl("Deactivate this Mailing List").click()
    >>> act()
    >>> print_list_state()
    INACTIVE

    >>> def purge_text(browser):
    ...     tag = find_tag_by_id(browser.contents, "mailing_list_purge")
    ...     if tag is None:
    ...         return None
    ...     return tag.p.contents[0].strip()
    ...

    >>> user_browser.getLink(url="+mailinglist").click()
    >>> print(purge_text(user_browser))
    You can purge this mailing list...

The team owner cannot reactivate mailing lists.

    >>> print(
    ...     extract_text(
    ...         find_tag_by_id(
    ...             user_browser.contents, "mailing_list_reactivate"
    ...         )
    ...     )
    ... )
    Launchpad no longer supports the reactivation of mailing lists.
    Read more about it here.

    >>> user_browser.getControl("Purge this Mailing List")
    <SubmitControl name='field.actions.purge_list' type='submit'>

Mailing list experts can also purge mailing lists.  Sample Person is
trustworthy enough to become a mailing list expert, but not a Launchpad
administrator.  They're given mailing list expert authority so that they can
purge mailing lists.

    >>> login("foo.bar@canonical.com")
    >>> from lp.app.interfaces.launchpad import ILaunchpadCelebrities
    >>> from lp.registry.interfaces.person import IPersonSet
    >>> person_set = getUtility(IPersonSet)
    >>> test = person_set.getByName("name12")
    >>> experts = getUtility(ILaunchpadCelebrities).registry_experts
    >>> ignored = experts.addMember(test, reviewer=experts.teamowner)
    >>> logout()
    >>> transaction.commit()

Sample Person, who is now a mailing list expert but not a Launchpad
administrator, can purge a list.

    >>> expert_browser = setupBrowser("Basic test@canonical.com:test")
    >>> expert_browser.open("http://launchpad.test/~aardvarks/+mailinglist")
    >>> print(purge_text(expert_browser))
    You can purge this mailing list...

A constructing, modified, updating, or deactivating or mod-failed list cannot
be purged.

    >>> from zope.security.proxy import removeSecurityProxy
    >>> from lp.registry.interfaces.mailinglist import MailingListStatus

    >>> def set_list_state(team_name, status):
    ...     login("foo.bar@canonical.com")
    ...     mailing_list = getUtility(IMailingListSet).get(team_name)
    ...     naked_list = removeSecurityProxy(mailing_list)
    ...     naked_list.status = status
    ...     transaction.commit()
    ...     logout()
    ...

    >>> def show_states(*states):
    ...     url = "http://launchpad.test/~aardvarks/+mailinglist"
    ...     for status in states:
    ...         set_list_state("aardvarks", status)
    ...         print_list_state()
    ...         admin_browser.open(url)
    ...         print(purge_text(admin_browser))
    ...         expert_browser.open(url)
    ...         print(purge_text(expert_browser))
    ...

A purged list acts as if it doesn't even exist.

    >>> set_list_state("aardvarks", MailingListStatus.PURGED)
    >>> print_list_state()
    PURGED
    >>> admin_browser.open("http://launchpad.test/~aardvarks/+mailinglist")
    >>> print(
    ...     extract_text(
    ...         find_tag_by_id(admin_browser.contents, "no_mailing_list")
    ...     )
    ... )
    Launchpad no longer supports the creation of new mailing lists.
    Read more about it here.
    >>> expert_browser.open("http://launchpad.test/~aardvarks/+mailinglist")
    >>> print(
    ...     extract_text(
    ...         find_tag_by_id(expert_browser.contents, "no_mailing_list")
    ...     )
    ... )
    Launchpad no longer supports the creation of new mailing lists.
    Read more about it here.

The team owner can see that an inactive list can be reactivated or purged.

    >>> set_list_state("aardvarks", MailingListStatus.INACTIVE)
