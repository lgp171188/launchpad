Adding members to a team
========================

Any administrator of a team can add new members to that team.

    >>> browser = setupBrowser(auth="Basic test@canonical.com:test")
    >>> browser.open("http://launchpad.test/~landscape-developers")
    >>> browser.getLink("Add member").click()
    >>> browser.url
    'http://launchpad.test/~landscape-developers/+addmember'
    >>> browser.getControl("New member").value = "cprov"
    >>> browser.getControl("Add Member").click()

    >>> for tag in find_tags_by_class(
    ...     browser.contents, "informational message"
    ... ):
    ...     print(tag.decode_contents())
    Celso Providelo (cprov) has been added as a member of this team.

Let's make sure that 'cprov' is now an Approved member of
'landscape-developers'.

    >>> from lp.registry.model.person import Person
    >>> from lp.registry.model.teammembership import TeamMembership
    >>> from lp.services.database.interfaces import IStore
    >>> cprov = IStore(Person).find(Person, name="cprov").one()
    >>> landscape_team = (
    ...     IStore(Person).find(Person, name="landscape-developers").one()
    ... )
    >>> cprov_landscape_membership = (
    ...     IStore(TeamMembership)
    ...     .find(TeamMembership, person=cprov, team=landscape_team)
    ...     .one()
    ... )
    >>> cprov_landscape_membership.status.title
    'Approved'
    >>> cprov.inTeam(landscape_team)
    True


Adding teams
------------

Teams are not added as members like we do with people. Instead, teams are
invited and one of their admins have to accept the invitation for them to
become a member.

    >>> browser.open("http://launchpad.test/~landscape-developers/+addmember")
    >>> browser.getControl("New member").value = "launchpad"
    >>> browser.getControl("Add Member").click()

    >>> for tag in find_tags_by_class(
    ...     browser.contents, "informational message"
    ... ):
    ...     print(tag.decode_contents())
    Launchpad Developers (launchpad) has been invited to join this team.

As we can see, the launchpad team will not be one of the team's active
members.

    >>> launchpad = IStore(Person).find(Person, name="launchpad").one()
    >>> launchpad in landscape_team.activemembers
    False
    >>> membership = (
    ...     IStore(TeamMembership)
    ...     .find(TeamMembership, person=launchpad, team=landscape_team)
    ...     .one()
    ... )
    >>> membership.status.title
    'Invited'

And nor will the admins of Landscape Developers be able to do any changes
with the TeamMembership representing the invitation sent to the Launchpad
team, not even if they manually craft the URL.

    >>> browser.open(
    ...     "http://launchpad.test/~landscape-developers/+member/launchpad"
    ... )

    >>> print(extract_text(find_tag_by_id(browser.contents, "not-responded")))
    Launchpad Developers (launchpad) has been invited to join this team, but
    hasn't responded to the invitation yet.

    >>> landscape_admin_browser = browser


Accepting/Declining invitations
-------------------------------

Any admin of the team which receives an invitation can either accept or deny
it. Although they get a link to the invitation's page, there's also a page
listing all open invitation sent to a given team.

    >>> browser = setupBrowser(auth="Basic foo.bar@canonical.com:test")
    >>> browser.open("http://launchpad.test/~launchpad")
    >>> browser.getLink("Show received invitations").click()
    >>> browser.url
    'http://launchpad.test/~launchpad/+invitations'

As said above, only admins of the invited team can accept/decline the
invitation. Not even an admin of the landscape team (which as so has the
rights to edit the membership in question) can do it.

    >>> landscape_admin_browser.open(
    ...     "http://launchpad.test/~launchpad/+invitation/"
    ...     "landscape-developers"
    ... )
    Traceback (most recent call last):
    ...
    zope.security.interfaces.Unauthorized: ...

First, let's accept the invitation sent on behalf of Landscape Developers to
the Launchpad Developers.

    >>> print(extract_text(find_tag_by_id(browser.contents, "invitations")))
    Sent by         On behalf of
    Andrew Bennetts Landscape Developers

    >>> browser.getLink(
    ...     url="/~launchpad/+invitation/landscape-developers"
    ... ).click()
    >>> browser.url
    'http://launchpad.test/~launchpad/+invitation/landscape-developers'

    >>> browser.getControl(name="field.acknowledger_comment").value = (
    ...     "This is just a test"
    ... )
    >>> browser.getControl("Accept").click()

    >>> browser.url
    'http://launchpad.test/~launchpad'
    >>> print(
    ...     extract_text(
    ...         find_tags_by_class(browser.contents, "informational")[0]
    ...     )
    ... )
    This team is now a member of Landscape Developers.

Now we'll decline the invitation sent on behalf of Ubuntu Team to
Warty Security Team:

    >>> browser.open("http://launchpad.test/~name20/+invitation/ubuntu-team")
    >>> browser.getControl("Decline").click()
    >>> browser.url
    'http://launchpad.test/~name20'
    >>> print(
    ...     extract_text(
    ...         find_tags_by_class(browser.contents, "informational")[0]
    ...     )
    ... )
    Declined the invitation to join Ubuntu Team


Corner cases
------------

Given that team can have more than one admin, it's possible that at the time
one admin is browsing the invitation page, another admin might be doing the
same. When an admin accepts or declines an invitation, the other admin can't
take action on that invitation anymore.

First invite name20 to be a member of ubuntu-team.

    >>> browser = setupBrowser(auth="Basic colin.watson@ubuntulinux.com:test")
    >>> browser.open("http://launchpad.test/~ubuntu-team/+addmember")
    >>> browser.getControl("New member:").value = "name20"
    >>> browser.getControl("Add Member").click()

    >>> for tag in find_tags_by_class(
    ...     browser.contents, "informational message"
    ... ):
    ...     print(tag.decode_contents())
    Warty Security Team (name20) has been invited to join this team.

Open the invitations page with one admin browser.

    >>> browser = setupBrowser(auth="Basic mark@example.com:test")
    >>> browser.open("http://launchpad.test/~name20/+invitation/ubuntu-team")

Open the same page with another admin browser.

    >>> second_browser = setupBrowser(auth="Basic mark@example.com:test")
    >>> second_browser.open(
    ...     "http://launchpad.test/~name20/+invitation/ubuntu-team"
    ... )

Accept the invitation in the first browser.

    >>> browser.getControl("Accept").click()
    >>> browser.url
    'http://launchpad.test/~name20'

    >>> for tag in find_tags_by_class(
    ...     browser.contents, "informational message"
    ... ):
    ...     print(tag.decode_contents())
    This team is now a member of Ubuntu Team.

Accepting the invitation in the second browser, redirects to the team page
and a message is displayed.

    >>> second_browser.getControl("Accept").click()
    >>> second_browser.url
    'http://launchpad.test/~name20'

    >>> for tag in find_tags_by_class(
    ...     second_browser.contents, "informational message"
    ... ):
    ...     print(tag.decode_contents())
    This invitation has already been processed.
