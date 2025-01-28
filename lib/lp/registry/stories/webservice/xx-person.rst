People and teams
================

Since we use a single class (Person) to represent a person or a team,
representations of people and teams are supposed to have nearly the
same keys.  I say nearly because some attributes are only made available
for teams (as they're defined in the ITeam interface).

    >>> from lazr.restful.testing.webservice import pprint_entry
    >>> salgado = webservice.get("/~salgado").jsonBody()
    >>> pprint_entry(salgado)
    admins_collection_link: 'http://.../~salgado/admins'
    archive_link: None
    confirmed_email_addresses_collection_link:
        'http://.../~salgado/confirmed_email_addresses'
    date_created: '2005-06-06T08:59:51.596025+00:00'
    deactivated_members_collection_link:
        'http://.../~salgado/deactivated_members'
    description: None
    display_name: 'Guilherme Salgado'
    expired_members_collection_link: 'http://.../~salgado/expired_members'
    gpg_keys_collection_link: 'http://.../~salgado/gpg_keys'
    hide_email_addresses: False
    homepage_content: None
    id: ...
    invited_members_collection_link: 'http://.../~salgado/invited_members'
    irc_nicknames_collection_link: 'http://.../~salgado/irc_nicknames'
    is_probationary: True
    is_team: False
    is_ubuntu_coc_signer: False
    is_valid: True
    jabber_ids_collection_link: 'http://.../~salgado/jabber_ids'
    karma: 0
    languages_collection_link: 'http://.../~salgado/languages'
    latitude: None
    logo_link: 'http://.../~salgado/logo'
    longitude: None
    mailing_list_auto_subscribe_policy: 'Ask me when I join a team'
    members_collection_link: 'http://.../~salgado/members'
    members_details_collection_link: 'http://.../~salgado/members_details'
    memberships_details_collection_link:
        'http://.../~salgado/memberships_details'
    mugshot_link: 'http://.../~salgado/mugshot'
    name: 'salgado'
    open_membership_invitations_collection_link:
        'http://.../~salgado/open_membership_invitations'
    participants_collection_link: 'http://.../~salgado/participants'
    ppas_collection_link: 'http://.../~salgado/ppas'
    preferred_email_address_link:
        'http://.../~salgado/+email/guilherme.salgado@canonical.com'
    private: False
    proposed_members_collection_link: 'http://.../~salgado/proposed_members'
    recipes_collection_link: 'http://.../~salgado/recipes'
    resource_type_link: 'http://.../#person'
    self_link: 'http://.../~salgado'
    social_accounts_collection_link: 'http://.../~salgado/social_accounts'
    sshkeys_collection_link: 'http://.../~salgado/sshkeys'
    sub_teams_collection_link: 'http://.../~salgado/sub_teams'
    super_teams_collection_link: 'http://.../~salgado/super_teams'
    team_owner_link: None
    time_zone: 'UTC'
    visibility: 'Public'
    web_link: 'http://launchpad.../~salgado'
    wiki_names_collection_link: 'http://.../~salgado/wiki_names'

    >>> ubuntu_team = webservice.get("/~ubuntu-team").jsonBody()
    >>> pprint_entry(ubuntu_team)
    admins_collection_link: 'http://.../~ubuntu-team/admins'
    archive_link: None
    confirmed_email_addresses_collection_link:
        'http://.../~ubuntu-team/confirmed_email_addresses'
    date_created: '2005-06-06T08:59:51.605760+00:00'
    deactivated_members_collection_link:
        'http://.../~ubuntu-team/deactivated_members'
    default_membership_period: None
    default_renewal_period: None
    description: 'This Team is responsible for the Ubuntu Distribution'
    display_name: 'Ubuntu Team'
    expired_members_collection_link:
        'http://.../~ubuntu-team/expired_members'
    gpg_keys_collection_link: 'http://.../~ubuntu-team/gpg_keys'
    hide_email_addresses: False
    homepage_content: None
    id: ...
    invited_members_collection_link:
        'http://.../~ubuntu-team/invited_members'
    irc_nicknames_collection_link: 'http://.../~ubuntu-team/irc_nicknames'
    is_probationary: False
    is_team: True
    is_ubuntu_coc_signer: False
    is_valid: True
    jabber_ids_collection_link: 'http://.../~ubuntu-team/jabber_ids'
    karma: 0
    languages_collection_link: 'http://.../~ubuntu-team/languages'
    latitude: None
    logo_link: 'http://.../~ubuntu-team/logo'
    longitude: None
    mailing_list_auto_subscribe_policy: 'Ask me when I join a team'
    members_collection_link: 'http://.../~ubuntu-team/members'
    members_details_collection_link:
        'http://.../~ubuntu-team/members_details'
    membership_policy: 'Moderated Team'
    memberships_details_collection_link:
        'http://.../~ubuntu-team/memberships_details'
    mugshot_link: 'http://.../~ubuntu-team/mugshot'
    name: 'ubuntu-team'
    open_membership_invitations_collection_link:
        'http://.../~ubuntu-team/open_membership_invitations'
    participants_collection_link: 'http://.../~ubuntu-team/participants'
    ppas_collection_link: 'http://.../~ubuntu-team/ppas'
    preferred_email_address_link:
        'http://.../~ubuntu-team/+email/support@ubuntu.com'
    private: False
    proposed_members_collection_link:
        'http://.../~ubuntu-team/proposed_members'
    recipes_collection_link: 'http://.../~ubuntu-team/recipes'
    renewal_policy: 'invite them to apply for renewal'
    resource_type_link: 'http://.../#team'
    self_link: 'http://.../~ubuntu-team'
    social_accounts_collection_link: 'http://.../~ubuntu-team/social_accounts'
    sshkeys_collection_link: 'http://.../~ubuntu-team/sshkeys'
    sub_teams_collection_link: 'http://.../~ubuntu-team/sub_teams'
    subscription_policy: 'Moderated Team'
    super_teams_collection_link: 'http://.../~ubuntu-team/super_teams'
    team_description: 'This Team is responsible for the Ubuntu Distribution'
    team_owner_link: 'http://.../~mark'
    time_zone: 'UTC'
    visibility: 'Public'
    web_link: 'http://launchpad.../~ubuntu-team'
    wiki_names_collection_link: 'http://.../~ubuntu-team/wiki_names'

    >>> for key in sorted(set(ubuntu_team.keys()).difference(salgado.keys())):
    ...     print(key)
    ...
    default_membership_period
    default_renewal_period
    membership_policy
    renewal_policy
    subscription_policy
    team_description

    >>> sorted(set(salgado.keys()).difference(ubuntu_team.keys()))
    []


Links to related things
-----------------------

As seen above, many attributes of a person are actually links to other
things (or collections).


Email addresses
...............

Apart from the link to the preferred email, there is a link to the
collection of other confirmed email addresses of that person/team.

    >>> sample_person = webservice.get("/~name12").jsonBody()
    >>> print(sample_person["preferred_email_address_link"])
    http://.../~name12/+email/test@canonical.com
    >>> emails = sample_person["confirmed_email_addresses_collection_link"]
    >>> print(emails)
    http://.../~name12/confirmed_email_addresses
    >>> print_self_link_of_entries(webservice.get(emails).jsonBody())
    http://.../~name12/+email/testing@canonical.com

Email addresses are first-class objects with their own URLs and
representations too.

    >>> email = webservice.get(
    ...     sample_person["preferred_email_address_link"]
    ... ).jsonBody()
    >>> pprint_entry(email)
    email: 'test@canonical.com'
    person_link: 'http://.../~name12'
    resource_type_link: 'http://.../#email_address'
    self_link: 'http://.../~name12/+email/test@canonical.com'

One can only traverse to the email addresses of the person already
traversed to, obviously.

    >>> print(webservice.get("/~salgado/+email/test@canonical.com"))
    HTTP/1.1 404 Not Found
    ...

SSH keys
........

People have SSH keys which we can manipulate over the API.

The sample person "ssh-user" doesn't have any keys to begin with:

    >>> login("test@canonical.com")
    >>> person = factory.makePerson(
    ...     name="ssh-user", email="ssh@launchpad.net"
    ... )
    >>> logout()
    >>> sample_person = webservice.get("/~ssh-user").jsonBody()
    >>> sshkeys = sample_person["sshkeys_collection_link"]
    >>> print(sshkeys)
    http://.../~ssh-user/sshkeys
    >>> print_self_link_of_entries(anon_webservice.get(sshkeys).jsonBody())

Let's give "ssh-user" a key via the back door of our internal Python APIs.
This setting of the ssh key should trigger a notice that the key has been
added.

    >>> from zope.component import getUtility
    >>> from lp.services.mail import stub
    >>> import transaction
    >>> from lp.testing import person_logged_in
    >>> with person_logged_in(person):
    ...     ssh_key = factory.makeSSHKey(person)
    ...     transaction.commit()
    ...     efrom, eto, emsg = stub.test_emails.pop()
    ...     eto
    ...
    ['ssh@launchpad.net']

    >>> logout()

Now when we get the sshkey collection for 'sssh-user' again, the key should
show up:

    >>> keys = anon_webservice.get(sshkeys).jsonBody()
    >>> print_self_link_of_entries(keys)
    http://.../~ssh-user/+ssh-keys/...


And then we can actually retrieve the key:

    >>> pprint_entry(keys["entries"][0])
    comment: 'unique-...'
    keytext: '...'
    keytype: 'RSA'
    resource_type_link: 'http://.../#ssh_key'
    self_link: 'http://.../~ssh-user/+ssh-keys/...'

GPG keys
........

People have GPG keys which we can manipulate over the API.

The sample person "name12" doesn't have any keys to begin with:

    >>> sample_person = webservice.get("/~name12").jsonBody()
    >>> gpgkeys = sample_person["gpg_keys_collection_link"]
    >>> print(gpgkeys)
    http://.../~name12/gpg_keys
    >>> print_self_link_of_entries(webservice.get(gpgkeys).jsonBody())

Let's give "name12" a key via the back door of our internal Python APIs:

    >>> from lp.registry.interfaces.person import IPersonSet
    >>> login(ANONYMOUS)
    >>> gpg_user = getUtility(IPersonSet).getByName("name12")
    >>> gpg_key = factory.makeGPGKey(gpg_user)
    >>> logout()

Now when we get the gpgkey collection for 'name12' again, the key should show
up:

    >>> keys = anon_webservice.get(gpgkeys).jsonBody()
    >>> print_self_link_of_entries(keys)
    http://.../~name12/+gpg-keys/...


And then we can actually retrieve the key:

    >>> pprint_entry(keys["entries"][0])
    fingerprint: '...'
    keyid: '...'
    resource_type_link: 'http://.../#gpg_key'
    self_link: 'http://.../~name12/+gpg-keys/...'


Team memberships
................

A person is linked to their team memberships.

    >>> salgado_memberships = salgado["memberships_details_collection_link"]
    >>> print(salgado_memberships)
    http://.../~salgado/memberships_details

Similarly, a team is linked to the team memberships of its members.

    >>> landscape_developers = webservice.get(
    ...     "/~landscape-developers"
    ... ).jsonBody()
    >>> print(landscape_developers["members_details_collection_link"])
    http://.../~landscape-developers/members_details

And to all membership invitations sent to it.

    >>> lp_team = webservice.get("/~launchpad").jsonBody()
    >>> lp_invitations = lp_team[
    ...     "open_membership_invitations_collection_link"
    ... ]
    >>> print(lp_invitations)
    http://.../~launchpad/open_membership_invitations

    >>> print_self_link_of_entries(webservice.get(lp_invitations).jsonBody())
    http://.../~landscape-developers/+member/launchpad

Team memberships are first-class objects with their own URLs.

    >>> print_self_link_of_entries(
    ...     webservice.get(salgado_memberships).jsonBody()
    ... )
    http://.../~admins/+member/salgado
    http://.../~landscape-developers/+member/salgado

Team memberships also have data fields.

    >>> salgado_landscape = [
    ...     entry
    ...     for entry in webservice.get(salgado_memberships).jsonBody()[
    ...         "entries"
    ...     ]
    ...     if entry["team_link"].endswith("~landscape-developers")
    ... ][0]
    >>> for key in sorted(salgado_landscape):
    ...     print(key)
    ...
    date_expires
    date_joined
    http_etag
    last_change_comment
    last_changed_by_link
    member_link
    resource_type_link
    self_link
    status
    team_link
    web_link

Each team membership links to the person who approved the link.

    >>> print(salgado_landscape["last_changed_by_link"])
    http://.../~name16

Also to the person whose membership it is.

    >>> print(salgado_landscape["member_link"])
    http://.../~salgado

Also to the team in which the membership is valid.

    >>> print(salgado_landscape["team_link"])
    http://.../~landscape-developers

A TeamMembership relates a person to a team, and the relationship
works both ways. You've already seen how the representation of a
person includes a link to that person's team memberships. But it's
possible to navigate from a team, to the collection of peoples'
memberships in the team.

    >>> print_self_link_of_entries(
    ...     webservice.get(
    ...         "/~landscape-developers/members_details"
    ...     ).jsonBody()
    ... )
    http://.../~landscape-developers/+member/name12
    http://.../~landscape-developers/+member/salgado

You can also change a TeamMembership through its custom operations.

To change its expiration date, use setExpirationDate(date).

    >>> print(salgado_landscape["date_expires"])
    None

    >>> from datetime import datetime, timezone
    >>> someday = datetime(2058, 8, 1, tzinfo=timezone.utc)
    >>> print(
    ...     webservice.named_post(
    ...         salgado_landscape["self_link"],
    ...         "setExpirationDate",
    ...         {},
    ...         date=str(someday),
    ...     )
    ... )
    HTTP/1.1 200 Ok
    ...

    >>> print(
    ...     webservice.get(salgado_landscape["self_link"]).jsonBody()[
    ...         "date_expires"
    ...     ]
    ... )
    2058-08-01...

To change its status, use setStatus(status).

    >>> print(salgado_landscape["status"])
    Approved

    >>> print(
    ...     webservice.named_post(
    ...         salgado_landscape["self_link"],
    ...         "setStatus",
    ...         {},
    ...         status="Deactivated",
    ...     )
    ... )
    HTTP/1.1 200 Ok
    ...

    >>> print(
    ...     webservice.get(salgado_landscape["self_link"]).jsonBody()[
    ...         "status"
    ...     ]
    ... )
    Deactivated

    >>> print(
    ...     webservice.named_post(
    ...         salgado_landscape["self_link"],
    ...         "setStatus",
    ...         {},
    ...         status="Approved",
    ...         silent=True,
    ...     )
    ... )
    HTTP/1.1 200 Ok
    ...

    >>> print(
    ...     webservice.get(salgado_landscape["self_link"]).jsonBody()[
    ...         "status"
    ...     ]
    ... )
    Approved

    >>> print(
    ...     webservice.named_post(
    ...         salgado_landscape["self_link"],
    ...         "setStatus",
    ...         {},
    ...         status="Deactivated",
    ...         silent=True,
    ...     )
    ... )
    HTTP/1.1 200 Ok
    ...

    # Now revert the change to salgado's membership to not break other tests
    # further down.
    >>> print(
    ...     webservice.named_post(
    ...         salgado_landscape["self_link"],
    ...         "setStatus",
    ...         {},
    ...         status="Approved",
    ...     )
    ... )
    HTTP/1.1 200 Ok
    ...


Members
.......

A list of team memberships is distinct from a list of a team's
members. Members are people; memberships are TeamMemberships. You've
seen the memberships for the 'landscape-developers' team above; here
are the members.

    >>> print_self_link_of_entries(
    ...     webservice.get("/~landscape-developers/members").jsonBody()
    ... )
    http://.../~name12
    http://.../~salgado

Here are the admins:

    >>> print_self_link_of_entries(
    ...     webservice.get("/~landscape-developers/admins").jsonBody()
    ... )
    http://.../~name12

All participants (direct or indirect members):

    >>> print_self_link_of_entries(
    ...     webservice.get("/~landscape-developers/participants").jsonBody()
    ... )
    http://.../~name12
    http://.../~salgado

There are also links to proposed, invited, deactivated and expired
members.

    >>> print_self_link_of_entries(
    ...     webservice.get("/~myteam/proposed_members").jsonBody()
    ... )
    http://.../~no-priv

    >>> print_self_link_of_entries(
    ...     webservice.get("/~ubuntu-team/invited_members").jsonBody()
    ... )
    http://.../~name20

    >>> print_self_link_of_entries(
    ...     webservice.get("/~admins/deactivated_members").jsonBody()
    ... )
    http://.../~cprov
    http://.../~ddaa
    http://.../~jblack

    >>> print_self_link_of_entries(
    ...     webservice.get(
    ...         "/~landscape-developers/expired_members"
    ...     ).jsonBody()
    ... )
    http://.../~karl


Sub-teams and super-teams
.........................

Teams can be members of other teams, and sometimes it's useful to know
which teams are members of any given team as well as the ones it is a
member of.

    >>> print_self_link_of_entries(
    ...     webservice.get(
    ...         ubuntu_team["sub_teams_collection_link"]
    ...     ).jsonBody()
    ... )
    http://.../~warty-gnome

    >>> print_self_link_of_entries(
    ...     webservice.get(
    ...         ubuntu_team["super_teams_collection_link"]
    ...     ).jsonBody()
    ... )
    http://.../~guadamen


Wiki names
..........

All wiki names associated to a person/team are also linked to that
person/team.

    >>> wikis_link = salgado["wiki_names_collection_link"]
    >>> print(wikis_link)
    http://.../~salgado/wiki_names
    >>> print_self_link_of_entries(webservice.get(wikis_link).jsonBody())
    http://.../~salgado/+wikiname/2

They can be listed by anonymous clients.

    >>> print_self_link_of_entries(anon_webservice.get(wikis_link).jsonBody())
    http://.../~salgado/+wikiname/2

Wiki names are first-class objects with their own URLs and
representations too.

    >>> wiki_name = sorted(webservice.get(wikis_link).jsonBody()["entries"])[
    ...     0
    ... ]
    >>> pprint_entry(wiki_name)
    person_link: 'http://.../~salgado'
    resource_type_link: 'http://.../#wiki_name'
    self_link: 'http://.../~salgado/+wikiname/2'
    url: 'https://wiki.ubuntu.com/GuilhermeSalgado'
    wiki: 'https://wiki.ubuntu.com/'
    wikiname: 'GuilhermeSalgado'

One can only traverse to the WikiNames of the person already traversed
to, obviously.

    >>> print(webservice.get("/~name12/+wikiname/2"))
    HTTP/1.1 404 Not Found
    ...

Wiki names can be modified.

    >>> import json
    >>> patch = {"wiki": "http://www.example.com/", "wikiname": "MrExample"}
    >>> response = webservice.patch(
    ...     wiki_name["self_link"], "application/json", json.dumps(patch)
    ... )
    >>> wiki_name = sorted(webservice.get(wikis_link).jsonBody()["entries"])[
    ...     0
    ... ]
    >>> print(wiki_name["url"])
    http://www.example.com/MrExample

But only if we supply valid data. Due to bug #1088358 the error is
escaped as if it was HTML.

    >>> patch = {"wiki": "javascript:void/**/", "wikiname": "MrExample"}
    >>> response = webservice.patch(
    ...     wiki_name["self_link"], "application/json", json.dumps(patch)
    ... )
    >>> print(response)
    HTTP/1.1 400 Bad Request
    ...
    wiki: The URI scheme &quot;javascript&quot; is not allowed.
    Only URIs with the following schemes may be used: http, https


Jabber IDs
..........

Jabber IDs of a person are also linked.

    >>> mark = webservice.get("/~mark").jsonBody()
    >>> jabber_ids_link = mark["jabber_ids_collection_link"]
    >>> print(jabber_ids_link)
    http://.../~mark/jabber_ids
    >>> print_self_link_of_entries(webservice.get(jabber_ids_link).jsonBody())
    http://.../~mark/+jabberid/markshuttleworth@jabber.org

Jabber IDs are first-class objects with their own URLs and
representations too.

    >>> jabber_id = sorted(
    ...     webservice.get(jabber_ids_link).jsonBody()["entries"]
    ... )[0]
    >>> pprint_entry(jabber_id)
    jabberid: 'markshuttleworth@jabber.org'
    person_link: 'http://.../~mark'
    resource_type_link: 'http://.../#jabber_id'
    self_link: 'http://.../~mark/+jabberid/markshuttleworth@jabber.org'

One can only traverse to the Jabber IDs of the person already traversed
to, obviously.

    >>> print(
    ...     webservice.get("/~salgado/+jabberid/markshuttleworth@jabber.org")
    ... )
    HTTP/1.1 404 Not Found
    ...

Social Accounts
..........

Social Accounts of a person are also linked.

    >>> mark = webservice.get("/~mark").jsonBody()
    >>> social_accounts_link = mark["social_accounts_collection_link"]
    >>> print(social_accounts_link)
    http://.../~mark/social_accounts
    >>> print_self_link_of_entries(
    ...     webservice.get(social_accounts_link).jsonBody()
    ... )

IRC nicknames
.............

The same for IRC nicknames

    >>> irc_ids_link = mark["irc_nicknames_collection_link"]
    >>> print(irc_ids_link)
    http://.../~mark/irc_nicknames
    >>> print_self_link_of_entries(webservice.get(irc_ids_link).jsonBody())
    http://.../~mark/+ircnick/1

Anonymous listing is possible.

    >>> print_self_link_of_entries(
    ...     anon_webservice.get(irc_ids_link).jsonBody()
    ... )
    http://.../~mark/+ircnick/1

IRC IDs are first-class objects with their own URLs and representations
too.

    >>> irc_id = sorted(webservice.get(irc_ids_link).jsonBody()["entries"])[0]
    >>> pprint_entry(irc_id)
    network: 'chat.freenode.net'
    nickname: 'mark'
    person_link: 'http://.../~mark'
    resource_type_link: 'http://.../#irc_id'
    self_link: 'http://.../~mark/+ircnick/1'

One can only traverse to the IRC IDs of the person already traversed
to, obviously.

    >>> print(webservice.get("/~salgado/+ircnick/1"))
    HTTP/1.1 404 Not Found
    ...


PPAs
....

We can get to the person's default PPA via the 'archive' property:

    >>> mark_archive_link = mark["archive_link"]
    >>> print(mark_archive_link)
    http://.../~mark/+archive/ubuntu/ppa

    >>> mark_archive = webservice.get(mark_archive_link).jsonBody()
    >>> print(mark_archive["description"])
    packages to help the humanity (you know, ubuntu)

The 'ppas' property returns a collection of PPAs owned by that
person.

    >>> print_self_link_of_entries(
    ...     webservice.get(mark["ppas_collection_link"]).jsonBody()
    ... )
    http://.../~mark/+archive/ubuntu/ppa

A specific PPA can be looked up by name via 'getPPAByName'
named-operation on IPerson.

    >>> print(
    ...     webservice.named_get(
    ...         mark["self_link"],
    ...         "getPPAByName",
    ...         distribution="/ubuntu",
    ...         name="ppa",
    ...     ).jsonBody()["self_link"]
    ... )
    http://.../~mark/+archive/ubuntu/ppa

If no distribution is specified, it defaults to Ubuntu.

    >>> print(
    ...     webservice.named_get(
    ...         mark["self_link"], "getPPAByName", name="ppa"
    ...     ).jsonBody()["self_link"]
    ... )
    http://.../~mark/+archive/ubuntu/ppa

In cases where a PPA with a given name cannot be found, a Not Found error is
returned.

    >>> print(
    ...     webservice.named_get(
    ...         mark["self_link"],
    ...         "getPPAByName",
    ...         distribution="/debian",
    ...         name="ppa",
    ...     )
    ... )
    HTTP/1.1 404 Not Found
    ...
    No such ppa: 'ppa'.

The method doesn't even bother to execute the lookup if the given
'name' doesn't match the constraints for PPA names. An error message
indicating what was wrong is returned.

    >>> print(
    ...     webservice.named_get(
    ...         mark["self_link"],
    ...         "getPPAByName",
    ...         distribution="/ubuntu",
    ...         name="XpTo@#$%",
    ...     )
    ... )
    HTTP/1.1 400 Bad Request
    ...
    name:
    Invalid name 'XpTo@#$%'. Names must be at least two characters ...

The 'getArchiveSubscriptionURLs' named operation will return a list of
all the URLs to the private archives that the person can access.

    >>> login("mark@example.com")
    >>> mark_person = getUtility(IPersonSet).getByName("mark")
    >>> mark_private_ppa = factory.makeArchive(
    ...     owner=mark_person,
    ...     distribution=mark_person.archive.distribution,
    ...     private=True,
    ...     name="p3a",
    ... )
    >>> new_sub_to_mark_ppa = mark_private_ppa.newSubscription(
    ...     mark_person, mark_person, description="testing"
    ... )
    >>> token = mark_private_ppa.newAuthToken(mark_person, "testtoken")
    >>> logout()

    >>> launchpad = launchpadlib_for("person test", "mark", "WRITE_PUBLIC")
    >>> for url in launchpad.me.getArchiveSubscriptionURLs():
    ...     print(url)
    ...
    http://mark:testtoken@private-ppa.launchpad.test/mark/p3a/ubuntu


Custom operations
-----------------

IPerson supports a bunch of operations.

Teams can subscribe to source packages:

    >>> login("admin@canonical.com")
    >>> pythons_db = factory.makeTeam(name="pythons")
    >>> package_db = factory.makeDistributionSourcePackage(
    ...     sourcepackagename="fooix"
    ... )
    >>> ignored = package_db.addSubscription(None, pythons_db)
    >>> logout()

Subscribed packages can be listed with getBugSubscriberPackages:

    >>> from lazr.restful.testing.webservice import pprint_collection
    >>> subscriptions = webservice.named_get(
    ...     "/~pythons", "getBugSubscriberPackages"
    ... ).jsonBody()
    >>> pprint_collection(subscriptions)
    start: 0
    total_size: 1
    ---
    bug_reported_acknowledgement: None
    bug_reporting_guidelines: None
    content_templates: None
    display_name: '...'
    distribution_link: '...'
    name: 'fooix'
    official_bug_tags: []
    resource_type_link: '...'
    self_link: '...'
    title: '...'
    upstream_product_link: None
    web_link: '...'
    ---


Team membership operations
..........................

Joining and leaving teams:

    >>> print(
    ...     webservice.named_post(
    ...         salgado["self_link"],
    ...         "join",
    ...         {},
    ...         team=ubuntu_team["self_link"],
    ...     )
    ... )
    HTTP/1.1 200 Ok
    ...
    >>> print(
    ...     webservice.get("/~ubuntu-team/+member/salgado").jsonBody()[
    ...         "status"
    ...     ]
    ... )
    Proposed

    >>> print(
    ...     webservice.named_post(
    ...         salgado["self_link"],
    ...         "leave",
    ...         {},
    ...         team=landscape_developers["self_link"],
    ...     )
    ... )
    HTTP/1.1 200 Ok
    ...
    >>> print(
    ...     webservice.get(
    ...         "/~landscape-developers/+member/salgado"
    ...     ).jsonBody()["status"]
    ... )
    Deactivated

Though it is not possible through the Launchpad UI, some users of the
REST API propose other people (as opposed to teams) as part of a
mentoring process (Bug 498181).

    >>> from lp.testing.pages import webservice_for_person
    >>> from lp.services.webapp.interfaces import OAuthPermission
    >>> login(ANONYMOUS)
    >>> owner = getUtility(IPersonSet).getByName("owner")
    >>> logout()
    >>> owner_webservice = webservice_for_person(
    ...     owner, permission=OAuthPermission.WRITE_PRIVATE
    ... )

    # The sample user (name12) is used to verify that it works when
    # the new member's email address is hidden.
    >>> print(
    ...     owner_webservice.named_post(
    ...         webservice.getAbsoluteUrl("~otherteam"),
    ...         "addMember",
    ...         {},
    ...         person=webservice.getAbsoluteUrl("/~name12"),
    ...         status="Proposed",
    ...         comment="Just a test",
    ...     )
    ... )
    HTTP/1.1 200 Ok
    ...
    >>> print(
    ...     owner_webservice.get("/~otherteam/+member/name12").jsonBody()[
    ...         "status"
    ...     ]
    ... )
    Proposed

Adding a team as a new member will result in the membership being
set to the Invited status.

    >>> print(
    ...     webservice.named_post(
    ...         ubuntu_team["self_link"],
    ...         "addMember",
    ...         {},
    ...         person=landscape_developers["self_link"],
    ...         comment="Just a test",
    ...     )
    ... )
    HTTP/1.1 200 Ok
    ...
    >>> print(
    ...     webservice.get(
    ...         "/~ubuntu-team/+member/landscape-developers"
    ...     ).jsonBody()["status"]
    ... )
    Invited

Accepting or declining a membership invitation:

    >>> print(
    ...     webservice.named_post(
    ...         landscape_developers["self_link"],
    ...         "acceptInvitationToBeMemberOf",
    ...         {},
    ...         team=ubuntu_team["self_link"],
    ...         comment="Just a test",
    ...     )
    ... )
    HTTP/1.1 200 Ok
    ...
    >>> print(
    ...     webservice.get(
    ...         "/~ubuntu-team/+member/landscape-developers"
    ...     ).jsonBody()["status"]
    ... )
    Approved

    >>> print(
    ...     webservice.named_post(
    ...         "/~name20",
    ...         "declineInvitationToBeMemberOf",
    ...         {},
    ...         team=ubuntu_team["self_link"],
    ...         comment="Just a test",
    ...     )
    ... )
    HTTP/1.1 200 Ok
    ...
    >>> print(
    ...     webservice.get("/~ubuntu-team/+member/name20").jsonBody()[
    ...         "status"
    ...     ]
    ... )
    Invitation declined

The retractTeamMembership method allows a team admin to remove their team
from another team.

    >>> print(
    ...     webservice.named_post(
    ...         landscape_developers["self_link"],
    ...         "retractTeamMembership",
    ...         {},
    ...         team=ubuntu_team["self_link"],
    ...         comment="bye bye",
    ...     )
    ... )
    HTTP/1.1 200 Ok
    ...
    >>> print(
    ...     webservice.get(
    ...         "/~ubuntu-team/+member/landscape-developers"
    ...     ).jsonBody()["status"]
    ... )
    Deactivated


Restrictions
------------

A team can't be its own owner.

    >>> doc = {"team_owner_link": webservice.getAbsoluteUrl("/~admins")}
    >>> print(
    ...     webservice.patch("/~admins", "application/json", json.dumps(doc))
    ... )
    HTTP/1.1 400 Bad Request
    ...
    team_owner_link: Constraint not satisfied.
