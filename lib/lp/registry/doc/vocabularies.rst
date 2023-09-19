Registry vocabularies
=====================

    >>> from lp.services.database.sqlbase import flush_database_updates
    >>> from lp.services.webapp.interfaces import IOpenLaunchBag
    >>> from lp.registry.interfaces.person import IPersonSet
    >>> from lp.registry.interfaces.product import IProductSet
    >>> from lp.registry.interfaces.projectgroup import IProjectGroupSet
    >>> from lp.testing import login
    >>> person_set = getUtility(IPersonSet)
    >>> product_set = getUtility(IProductSet)
    >>> login("foo.bar@canonical.com")
    >>> launchbag = getUtility(IOpenLaunchBag)
    >>> launchbag.clear()

    >>> from zope.schema.vocabulary import getVocabularyRegistry
    >>> from zope.security.proxy import removeSecurityProxy
    >>> vocabulary_registry = getVocabularyRegistry()
    >>> def get_naked_vocab(context, name):
    ...     return removeSecurityProxy(vocabulary_registry.get(context, name))
    ...
    >>> product_vocabulary = get_naked_vocab(None, "Product")


ActiveMailingList
-----------------

The active mailing lists vocabulary matches and returns only those
mailing lists which are active.

    >>> list_vocabulary = get_naked_vocab(None, "ActiveMailingList")
    >>> from lp.testing import verifyObject
    >>> from lp.services.webapp.vocabulary import IHugeVocabulary
    >>> verifyObject(IHugeVocabulary, list_vocabulary)
    True

    >>> list_vocabulary.displayname
    'Select an active mailing list.'

At first, there are no active mailing lists.

    >>> list(list_vocabulary)
    []

    >>> len(list_vocabulary)
    0

    >>> list(list_vocabulary.search())
    []

Mailing lists are not active when they are first registered.

    >>> personset = getUtility(IPersonSet)
    >>> ddaa = personset.getByName("ddaa")
    >>> carlos = personset.getByName("carlos")
    >>> from lp.registry.interfaces.mailinglist import (
    ...     IMailingListSet,
    ...     MailingListStatus,
    ... )
    >>> from lp.registry.interfaces.person import TeamMembershipPolicy
    >>> team_one = personset.newTeam(
    ...     ddaa,
    ...     "bass-players",
    ...     "Bass Players",
    ...     membership_policy=TeamMembershipPolicy.OPEN,
    ... )
    >>> team_two = personset.newTeam(
    ...     ddaa,
    ...     "guitar-players",
    ...     "Guitar Players",
    ...     membership_policy=TeamMembershipPolicy.OPEN,
    ... )
    >>> team_three = personset.newTeam(
    ...     ddaa,
    ...     "drummers",
    ...     "Drummers",
    ...     membership_policy=TeamMembershipPolicy.OPEN,
    ... )
    >>> listset = getUtility(IMailingListSet)
    >>> list_one = listset.new(team_one)
    >>> list_two = listset.new(team_two)
    >>> list_three = listset.new(team_three)
    >>> list(list_vocabulary)
    []

    >>> len(list_vocabulary)
    0

    >>> list(list_vocabulary.search())
    []

Mailing lists become active once they have been constructed by Mailman
(which indicates so by transitioning the state to ACTIVE).

    >>> list_one.startConstructing()
    >>> list_two.startConstructing()
    >>> list_three.startConstructing()
    >>> list_one.transitionToStatus(MailingListStatus.ACTIVE)
    >>> list_two.transitionToStatus(MailingListStatus.ACTIVE)
    >>> list_three.transitionToStatus(MailingListStatus.ACTIVE)
    >>> flush_database_updates()
    >>> from operator import attrgetter
    >>> for mailing_list in sorted(
    ...     list_vocabulary, key=attrgetter("team.displayname")
    ... ):
    ...     print(mailing_list.team.displayname)
    Bass Players
    Drummers
    Guitar Players

    >>> len(list_vocabulary)
    3

Searching for active lists is done through the vocabulary as well.  With
a search term of None, all active lists are returned.

    >>> for mailing_list in sorted(
    ...     list_vocabulary.search(None), key=attrgetter("team.displayname")
    ... ):
    ...     print(mailing_list.team.displayname)
    Bass Players
    Drummers
    Guitar Players

If given, the search term matches the team name.

    >>> for mailing_list in sorted(
    ...     list_vocabulary.search("player"),
    ...     key=attrgetter("team.displayname"),
    ... ):
    ...     print(mailing_list.team.displayname)
    Bass Players
    Guitar Players

The IHugeVocabulary interface also requires a search method that returns
a CountableIterator.

    >>> iter = list_vocabulary.searchForTerms("player")
    >>> from lp.services.webapp.vocabulary import CountableIterator
    >>> isinstance(iter, CountableIterator)
    True

    >>> for term in sorted(iter, key=attrgetter("value.team.name")):
    ...     print(pretty((term.value.team.name, term.token, term.title)))
    ...
    ('bass-players', 'bass-players', 'Bass Players')
    ('guitar-players', 'guitar-players', 'Guitar Players')

The vocabulary supports accessing mailing lists by 'term', where the
term must be a mailing list.  The returned term's value is the mailing
list object, the token is the team name and the title is the team's
display name.

    >>> term_1 = list_vocabulary.getTerm(list_two)
    >>> print(term_1.value.team.displayname)
    Guitar Players

    >>> term_1.token
    'guitar-players'

    >>> print(term_1.title)
    Guitar Players

You cannot get a term by an other object, such as a team.

    >>> list_vocabulary.getTerm(team_one)
    Traceback (most recent call last):
    ...
    zope.security.interfaces.ForbiddenAttribute: ...

Given a token, we can get back the term.

    >>> term_2 = list_vocabulary.getTermByToken(term_1.token)
    >>> print(term_2.value.team.displayname)
    Guitar Players

    >>> term_3 = list_vocabulary.getTerm(list_one)
    >>> term_4 = list_vocabulary.getTermByToken(term_3.token)
    >>> print(term_4.value.team.displayname)
    Bass Players

If you try to get the term by a token not represented in the vocabulary,
you get an exception.

    >>> list_vocabulary.getTermByToken("turntablists")
    Traceback (most recent call last):
    ...
    LookupError: turntablists

You can also ask whether a mailing list is contained in the vocabulary.

    >>> list_three in list_vocabulary
    True

You are not allowed to ask whether a non-mailing list object is
contained in this vocabulary.

    >>> team_three in list_vocabulary
    Traceback (most recent call last):
    ...
    zope.security.interfaces.ForbiddenAttribute: ...

Non-ACTIVE mailing lists are also not contained in the vocabulary.

    >>> team_four = personset.newTeam(
    ...     ddaa,
    ...     "flautists",
    ...     "Flautists",
    ...     membership_policy=TeamMembershipPolicy.OPEN,
    ... )
    >>> list_four = listset.new(team_four)
    >>> list_four in list_vocabulary
    False

Sometimes, the vocabulary search doesn't return any active lists.

    >>> list(list_vocabulary.search("flautists"))
    []

    >>> list(list_vocabulary.search("cellists"))
    []


DistroSeriesVocabulary
......................

Reflects the available distribution series.  Results are ordered by
`name`

    >>> distroseries_vocabulary = get_naked_vocab(None, "DistroSeries")
    >>> for term in distroseries_vocabulary:
    ...     print("%30s %s" % (term.token, term.title))
    ...
            ubuntu/breezy-autotest Ubuntu: Breezy Badger Autotest
                     ubuntu/grumpy Ubuntu: The Grumpy Groundhog Release
                      ubuntu/hoary Ubuntu: The Hoary Hedgehog Release
                      ubuntu/warty Ubuntu: The Warty Warthog Release
                      debian/sarge Debian: Sarge
                        debian/sid Debian: Sid
                      debian/woody Debian: WOODY
                    guadalinex/2k5 GuadaLinex: Guada 2005
                    kubuntu/krunch Kubuntu: The Krunchy Kangaroo
                        redhat/7.0 Red Hat: Seven
                        redhat/six Red Hat: Six Six Six
        ubuntutest/breezy-autotest ubuntutest: Breezy Badger Autotest
             ubuntutest/hoary-test ubuntutest: Mock Hoary

    >>> print(
    ...     distroseries_vocabulary.getTermByToken("ubuntu/hoary").value.title
    ... )
    The Hoary Hedgehog Release

    >>> def getTerms(vocab, search_text):
    ...     [vocab.toTerm(item) for item in vocab.search(search_text)]
    ...

    >>> getTerms(distroseries_vocabulary, "woody")
    >>> getTerms(distroseries_vocabulary, "debian")
    >>> getTerms(distroseries_vocabulary, "invalid")
    >>> getTerms(distroseries_vocabulary, "")

    >> [term.token for term in distroseries_vocabulary.search('woody')]
    ['debian/woody']
    >> [term.token for term in distroseries_vocabulary.search('debian')]
    ['debian/sarge', 'debian/sid', 'debian/woody']
    >> [term.token for term in distroseries_vocabulary.search('invalid')]
    []
    >> [term.token for term in distroseries_vocabulary.search('')]
    []


PersonActiveMembership
......................

All the teams the person is an active member of.

    >>> foo_bar = person_set.getByEmail("foo.bar@canonical.com")
    >>> person_active_membership = get_naked_vocab(
    ...     foo_bar, "PersonActiveMembership"
    ... )
    >>> len(person_active_membership)
    10

    >>> for term in person_active_membership:
    ...     print(term.token, term.value.displayname, term.title)
    ...
    canonical-partner-dev Canonical Partner Developers
        Canonical Partner Developers
    guadamen GuadaMen GuadaMen
    hwdb-team HWDB Team HWDB Team
    admins Launchpad Administrators Launchpad Administrators
    launchpad-buildd-admins Launchpad Buildd Admins Launchpad Buildd Admins
    launchpad Launchpad Developers Launchpad Developers
    testing-spanish-team testing Spanish team testing Spanish team
    name18 Ubuntu Gnome Team Ubuntu Gnome Team
    ubuntu-team Ubuntu Team Ubuntu Team
    vcs-imports VCS imports VCS imports

    >>> launchpad_team = person_set.getByName("launchpad")
    >>> launchpad_team in person_active_membership
    True

    >>> ubuntu_mirror_admins = person_set.getByName("ubuntu-mirror-admins")
    >>> ubuntu_mirror_admins in person_active_membership
    False

The PersonActiveMembership vocabulary only shows teams where the
membership is public.

    >>> from lp.registry.interfaces.person import PersonVisibility
    >>> pubteam = factory.makeTeam(
    ...     owner=foo_bar,
    ...     name="public-team",
    ...     displayname="Public Team",
    ...     visibility=PersonVisibility.PUBLIC,
    ... )
    >>> for term in person_active_membership:
    ...     print(term.token, term.value.displayname, term.title)
    ...
    canonical-partner-dev Canonical Partner Developers
        Canonical Partner Developers
    guadamen GuadaMen GuadaMen
    hwdb-team HWDB Team HWDB Team
    admins Launchpad Administrators Launchpad Administrators
    launchpad-buildd-admins Launchpad Buildd Admins Launchpad Buildd Admins
    launchpad Launchpad Developers Launchpad Developers
    public-team Public Team Public Team
    testing-spanish-team testing Spanish team testing Spanish team
    name18 Ubuntu Gnome Team Ubuntu Gnome Team
    ubuntu-team Ubuntu Team Ubuntu Team
    vcs-imports VCS imports VCS imports

    >>> pubteam.visibility = PersonVisibility.PRIVATE
    >>> for term in person_active_membership:
    ...     print(term.token, term.value.displayname, term.title)
    ...
    canonical-partner-dev Canonical Partner Developers
        Canonical Partner Developers
    guadamen GuadaMen GuadaMen
    hwdb-team HWDB Team HWDB Team
    admins Launchpad Administrators Launchpad Administrators
    launchpad-buildd-admins Launchpad Buildd Admins Launchpad Buildd Admins
    launchpad Launchpad Developers Launchpad Developers
    testing-spanish-team testing Spanish team testing Spanish team
    name18 Ubuntu Gnome Team Ubuntu Gnome Team
    ubuntu-team Ubuntu Team Ubuntu Team
    vcs-imports VCS imports VCS imports

    >>> term = person_active_membership.getTerm(launchpad_team)
    >>> print(term.token, term.value.displayname, term.title)
    launchpad Launchpad Developers Launchpad Developers

    >>> term = person_active_membership.getTerm(ubuntu_mirror_admins)
    Traceback (most recent call last):
    ...
    LookupError:...

    >>> term = person_active_membership.getTermByToken("launchpad")
    >>> print(term.token, term.value.displayname, term.title)
    launchpad Launchpad Developers Launchpad Developers

    >>> term = person_active_membership.getTermByToken("ubuntu-mirror-admins")
    Traceback (most recent call last):
    ...
    LookupError:...


Milestone
.........

All the milestone in a context.

A MilestoneVolcabulary contains different milestones, depending on the
current context. It is pointless to present the large number of all
active milestones known in Launchpad in a vocabulary. Hence a
MilestoneVolcabulary contains only those milestones that are related to
the current context. If no context is given, or if the context does not
have any milestones, a MilestoneVocabulary is empty...

    >>> milestones = get_naked_vocab(None, "Milestone")
    >>> len(milestones)
    0

    >>> from lp.bugs.interfaces.malone import IMaloneApplication
    >>> malone = getUtility(IMaloneApplication)
    >>> milestones = get_naked_vocab(malone, "Milestone")
    >>> len(milestones)
    0

...but if the context is an IPerson, the MilestoneVocabulary contains
all milestones. IPerson related pages showing milestone lists retrieve
the milestones from RelevantMilestonesMixin.getMilestoneWidgetValues()
but we need the big default vocabulary for form input validation.

    >>> sample_person = person_set.getByName("name12")
    >>> all_milestones = get_naked_vocab(sample_person, "Milestone")
    >>> len(all_milestones)
    3

    >>> for term in all_milestones:
    ...     print("%s: %s" % (term.value.target.name, term.value.name))
    ...
    debian: 3.1
    debian: 3.1-rc1
    firefox: 1.0

If the context is a product, only the product's milestones are in the
vocabulary.

    >>> firefox = product_set.getByName("firefox")
    >>> firefox_milestones = get_naked_vocab(firefox, "Milestone")
    >>> for term in firefox_milestones:
    ...     print("%s: %s" % (term.value.target.name, term.value.name))
    ...
    firefox: 1.0

If the context is a productseries, milestones for the series and for the
product itself are included in the vocabulary.

    >>> firefox_trunk = firefox.getSeries("trunk")
    >>> firefox_milestone = factory.makeMilestone(
    ...     product=firefox, name="firefox-milestone-no-series"
    ... )
    >>> firefox_trunk_milestones = get_naked_vocab(firefox_trunk, "Milestone")
    >>> for term in firefox_trunk_milestones:
    ...     print("%s: %s" % (term.value.target.name, term.value.name))
    ...
    firefox: 1.0
    firefox: firefox-milestone-no-series

Inactive milestones are not included in the vocabulary results.
    >>> firefox_milestone.active = False

If the context is a specification, only milestones from that
specification target are in the vocabulary.

    >>> canvas_spec = firefox.getSpecification("canvas")
    >>> spec_target_milestones = get_naked_vocab(canvas_spec, "Milestone")
    >>> for term in spec_target_milestones:
    ...     print("%s: %s" % (term.value.target.name, term.value.name))
    ...
    firefox: 1.0

The vocabulary contains only active milestones.

    >>> for milestone in firefox.milestones:
    ...     print(milestone.name, milestone.active)
    ...
    1.0 True

    >>> one_dot_o = firefox.milestones[0]
    >>> print(one_dot_o.name)
    1.0

    >>> one_dot_o.active = False

    >>> firefox_milestones = get_naked_vocab(firefox, "Milestone")
    >>> len(firefox_milestones)
    0


ProjectProductsVocabulary
.........................

All the products in a project.

    >>> mozilla_project = getUtility(IProjectGroupSet).getByName("mozilla")
    >>> mozilla_products_vocabulary = get_naked_vocab(
    ...     mozilla_project, "ProjectProducts"
    ... )

    >>> for term in mozilla_products_vocabulary:
    ...     print("%s: %s" % (term.token, term.title))
    ...
    firefox: Mozilla Firefox
    thunderbird: Mozilla Thunderbird


ProjectGroupVocabulary
......................

The list of selectable projects. The results are ordered by displayname.

    >>> project_vocabulary = get_naked_vocab(None, "ProjectGroup")
    >>> project_vocabulary.displayname
    'Select a project group'

    >>> for p in project_vocabulary.search("mozilla"):
    ...     print(p.title)
    ...
    The Mozilla Project

    >>> mozilla = project_vocabulary.getTermByToken("mozilla")
    >>> print(mozilla.title)
    The Mozilla Project

  The ProjectGroupVocabulary does not list inactive projects.

    >>> from lp.registry.interfaces.projectgroup import IProjectGroupSet
    >>> moz_project = getUtility(IProjectGroupSet)["mozilla"]
    >>> moz_project in project_vocabulary
    True

    >>> for p in project_vocabulary.search("mozilla"):
    ...     print(p.title)
    ...
    The Mozilla Project

    >>> moz_project.active = False
    >>> flush_database_updates()
    >>> moz_project in project_vocabulary
    False

    >>> [p.title for p in project_vocabulary.search("mozilla")]
    []

    >>> moz_project.active = True
    >>> flush_database_updates()


ProductReleaseVocabulary
........................

The list of selectable products releases.

    >>> productrelease_vocabulary = get_naked_vocab(None, "ProductRelease")
    >>> productrelease_vocabulary.displayname
    'Select a Product Release'

    >>> list(productrelease_vocabulary.search(None))
    []

    >>> evolution_releases = productrelease_vocabulary.search("evolution")
    >>> l = [release_term.title for release_term in evolution_releases]
    >>> release = productrelease_vocabulary.getTermByToken(
    ...     "evolution/trunk/2.1.6"
    ... )
    >>> print(release.title)
    evolution trunk 2.1.6


PersonAccountToMergeVocabulary
..............................

All non-merged people with at least one email address. This vocabulary
is meant to be used only in the people merge form.

    >>> vocab = get_naked_vocab(None, "PersonAccountToMerge")
    >>> vocab.displayname
    'Select a Person to Merge'

Searching for None returns an empty list.

    >>> list(vocab.search(None))
    []

Searching for 'Launchpad Administrators' will return an empty list,
because teams are not part of this vocabulary.

    >>> [item.name for item in list(vocab.search("Launchpad Administrators"))]
    []

A search using part of the email address of a team will also return an
empty list.

    >>> list(vocab.search("admins"))
    []

Searching for a person without a preferred email will return that
person's name.

    >>> for person in vocab.search("salgado"):
    ...     print(person.name)
    ...
    salgado

A search using the beginning of a person's preferred email will return
that person that owns that email.

    >>> for person in vocab.search("foo.bar"):
    ...     print("%s: %s" % (person.name, person.preferredemail.email))
    ...
    name16: foo.bar@canonical.com

A search using part of the host of an email address will not return
anything, as we only match against the beginning of an email address.

    >>> list(vocab.search("canonical"))
    []

A person with a single and unvalidated email address can be merged.

    >>> from lp.services.identity.interfaces.account import AccountStatus
    >>> fooperson = factory.makePerson(account_status=AccountStatus.NOACCOUNT)
    >>> fooperson in vocab
    True

But any person without a single email address can't.

    >>> fooperson.guessedemails[0].destroySelf()
    >>> fooperson in vocab
    False

Any person that's already merged is not part of this vocabulary:

    >>> cprov = person_set.getByName("cprov")
    >>> cprov in vocab
    True

    # Here we cheat because IPerson.merged is a readonly attribute.

    >>> naked_cprov = removeSecurityProxy(cprov)
    >>> naked_cprov.merged = 1
    >>> cprov in vocab
    False

A person whose account_status is any of the statuses of
INACTIVE_ACCOUNT_STATUSES is part of the vocabulary, though.

    >>> from lp.services.identity.interfaces.account import (
    ...     AccountStatus,
    ...     INACTIVE_ACCOUNT_STATUSES,
    ... )
    >>> naked_cprov.merged = None
    >>> checked_count = 0
    >>> for status in INACTIVE_ACCOUNT_STATUSES:
    ...     # Placeholder accounts don't have email addresses, so don't
    ...     # show up.
    ...     if status == AccountStatus.PLACEHOLDER:
    ...         continue
    ...     person = factory.makePerson(account_status=status)
    ...     checked_count += int(person in vocab)
    ...
    >>> checked_count == len(INACTIVE_ACCOUNT_STATUSES) - 1
    True

It is possible to search for alternative names.

    >>> for person in vocab.search("matsubara OR salgado"):
    ...     print(person.name)
    ...
    matsubara
    salgado


AdminMergeablePerson
--------------------

The set of non-merged people.

    >>> vocab = get_naked_vocab(None, "AdminMergeablePerson")
    >>> vocab.displayname
    'Select a Person to Merge'

Unlike PersonAccountToMerge, this vocabulary includes people who don't
have a single email address, as it's fine for admins to merge them.

    >>> print(fooperson.preferredemail)
    None

    >>> list(fooperson.validatedemails) + list(fooperson.guessedemails)
    []

    >>> fooperson in vocab
    True


NonMergedPeopleAndTeams
.......................

All non-merged people and teams.

    >>> vocab = get_naked_vocab(None, "NonMergedPeopleAndTeams")
    >>> vocab.displayname
    'Select a Person or Team'

    >>> list(vocab.search(None))
    []

This vocabulary includes both validated and unvalidated profiles, as
well as teams:

    >>> for p in vocab.search("matsubara"):
    ...     print("%s: %s" % (p.name, p.is_valid_person))
    ...
    matsubara: False

    >>> for p in vocab.search("mark@example.com"):
    ...     print("%s: %s" % (p.name, p.is_valid_person))
    ...
    mark: True

    >>> for p in vocab.search("ubuntu-team"):
    ...     print("%s: %s" % (p.name, getattr(p.teamowner, "name", None)))
    ...
    ubuntu-team: mark

But it doesn't include merged accounts:

    >>> fooperson in vocab
    False

It is possible to search for alternative names.

    >>> for p in vocab.search("matsubara OR salgado"):
    ...     print(p.name)
    ...
    matsubara
    salgado


ValidPersonOrTeam
.................

All 'valid' persons or teams. This is currently defined as people with a
preferred email address and not merged (Person.merged is None).  It also
includes all public teams and private teams the user has permission to view.

    >>> vocab = get_naked_vocab(None, "ValidPersonOrTeam")
    >>> vocab.displayname
    'Select a Person or Team'

    >>> list(vocab.search(None))
    []

We can do token lookups using either a person's name or a person's email
address.

    >>> print(vocab.getTermByToken("name16").value.displayname)
    Foo Bar

    >>> print(vocab.getTermByToken("foo.bar@canonical.com").value.displayname)
    Foo Bar

Almost all teams have the word 'team' as part of their names, so a
search for 'team' should give us some of them.  Notice that the
PRIVATE_TEAM 'myteam' is not included in the results.

    >>> ignored = login_person(sample_person)
    >>> ephemeral = factory.makeTeam(owner=foo_bar, name="ephemeral-team")
    >>> for person in sorted(vocab.search("team"), key=attrgetter("name")):
    ...     print(person.name)
    ...
    ephemeral-team
    hwdb-team
    name18
    name20
    name21
    no-team-memberships
    otherteam
    simple-team
    testing-spanish-team
    ubuntu-security
    ubuntu-team
    warty-gnome

Valid teams do not include teams that have been merged.

    >>> from lp.app.interfaces.launchpad import ILaunchpadCelebrities
    >>> from lp.registry.personmerge import merge_people
    >>> ignored = login_person(foo_bar)
    >>> registry_experts = getUtility(ILaunchpadCelebrities).registry_experts
    >>> merge_people(
    ...     ephemeral, registry_experts, reviewer=ephemeral.teamowner
    ... )
    >>> ignored = login_person(sample_person)
    >>> for person in sorted(vocab.search("team"), key=attrgetter("name")):
    ...     print(person.name)
    ...
    hwdb-team
    name18
    name20
    name21
    no-team-memberships
    otherteam
    simple-team
    testing-spanish-team
    ubuntu-security
    ubuntu-team
    warty-gnome

A PRIVATE team is displayed when the logged in user is a member of the
team.

    >>> no_priv = person_set.getByEmail("no-priv@canonical.com")
    >>> vocab = get_naked_vocab(no_priv, "ValidPersonOrTeam")
    >>> login("no-priv@canonical.com")
    >>> priv_team = factory.makeTeam(
    ...     name="private-team",
    ...     displayname="Private Team",
    ...     owner=no_priv,
    ...     visibility=PersonVisibility.PRIVATE,
    ... )
    >>> for person in sorted(vocab.search("team"), key=attrgetter("name")):
    ...     print(person.name)
    ...
    hwdb-team
    name18
    name20
    name21
    no-team-memberships
    otherteam
    private-team
    simple-team
    testing-spanish-team
    ubuntu-security
    ubuntu-team
    warty-gnome

The PRIVATE team is also displayed for Launchpad admins or commercial
admins.

    >>> login("foo.bar@canonical.com")
    >>> for person in sorted(vocab.search("team"), key=attrgetter("name")):
    ...     print(person.name)
    ...
    hwdb-team
    myteam
    name18
    name20
    name21
    no-team-memberships
    otherteam
    private-team
    public-team
    simple-team
    testing-spanish-team
    ubuntu-security
    ubuntu-team
    warty-gnome
    >>> logout()
    >>> login("commercial-member@canonical.com")
    >>> for person in sorted(vocab.search("team"), key=attrgetter("name")):
    ...     print(person.name)
    ...
    hwdb-team
    myteam
    name18
    name20
    name21
    no-team-memberships
    otherteam
    private-team
    public-team
    simple-team
    testing-spanish-team
    ubuntu-security
    ubuntu-team
    warty-gnome

The PRIVATE team can be looked up via getTermByToken for a member of the
team.

    >>> term = vocab.getTermByToken("private-team")
    >>> print(term.title)
    Private Team

The PRIVATE team is not returned for a user who is not part of the team.

    >>> login("owner@canonical.com")
    >>> for person in sorted(vocab.search("team"), key=attrgetter("name")):
    ...     print(person.name)
    ...
    hwdb-team
    myteam
    name18
    name20
    name21
    no-team-memberships
    otherteam
    simple-team
    testing-spanish-team
    ubuntu-security
    ubuntu-team
    warty-gnome

The anonymous user will not see the private team either.

    >>> login(ANONYMOUS)
    >>> for person in sorted(vocab.search("team"), key=attrgetter("name")):
    ...     print(person.name)
    ...
    hwdb-team
    name18
    name20
    name21
    no-team-memberships
    otherteam
    simple-team
    testing-spanish-team
    ubuntu-security
    ubuntu-team
    warty-gnome

Attempting to lookup the team via getTermByToken results in a
LookupError, the same as if the team didn't exist, which is really
important to avoid leaking information about private teams to someone
who just guesses team names.

    >>> term = vocab.getTermByToken("private-team")
    Traceback (most recent call last):
    ...
    LookupError: ...

Searching for all teams, which requires monkey-patching the
`allow_null_search` property, will also return the private team.

    >>> login("no-priv@canonical.com")
    >>> vocab.allow_null_search = True
    >>> sorted(person.name for person in vocab.search(""))
    [...'private-team'...]

A search for 'support' will give us only the persons which have support
as part of their name or displayname, or the beginning of one of its
email addresses.

    >>> login("foo.bar@canonical.com")
    >>> vocab = get_naked_vocab(None, "ValidPersonOrTeam")
    >>> for person in vocab.search("support"):
    ...     print(person.name)
    ...
    ubuntu-team

Matsubara doesn't have a preferred email address; he's not a valid
Person.

    >>> sorted(person.name for person in vocab.search("matsubara"))
    []

'foo.bar@canonical.com' is a valid Person.

    >>> for person in vocab.search("foo.bar"):
    ...     print(person.name)
    ...
    name16

The vocabulary also allows us to search by IRC nickname.

    >>> [cjwatson] = vocab.search("cjwatson")
    >>> print(cjwatson.name)
    kamion
    >>> print(cjwatson.preferredemail.email)
    colin.watson@ubuntulinux.com

    >>> for ircid in cjwatson.ircnicknames:
    ...     print(ircid.nickname)
    ...
    cjwatson

Since there are so many people and teams a vocabulary that includes them
all is not very useful when displaying in the user interface.  So we
limit the number of results.  The results are ordered by rank, displayname and
the first set of those are the ones returned

    >>> login(ANONYMOUS)
    >>> for person in vocab.search("team"):
    ...     print(person.displayname)
    ...
    HWDB Team
    No Team Memberships
    Simple Team
    Ubuntu Team
    testing Spanish team
    Hoary Gnome Team
    Other Team
    Ubuntu Gnome Team
    Ubuntu Security Team
    Warty Gnome Team
    Warty Security Team

If a match is done against irc nick, that is ranked higher than a fti match.

    >>> from lp.registry.interfaces.irc import IIrcIDSet
    >>> ircid_set = getUtility(IIrcIDSet)

    >>> irc_person = factory.makePerson(name="ircperson")
    >>> irc_id = ircid_set.new(irc_person, "chat.freenode.net", "team")
    >>> for person in vocab.search("team"):
    ...     print(person.displayname)
    ...
    Ircperson
    HWDB Team
    No Team Memberships
    Simple Team
    Ubuntu Team
    testing Spanish team
    Hoary Gnome Team
    Other Team
    Ubuntu Gnome Team
    Ubuntu Security Team
    Warty Gnome Team
    Warty Security Team

A match on launchpad name ranks higher than irc nickname:
    >>> lifeless2 = factory.makePerson(name="anotherlifeless")
    >>> irc_id = ircid_set.new(lifeless2, "chat.freenode.net", "lifeless")
    >>> for person in vocab.search("lifeless"):
    ...     print(person.displayname)
    ...
    Robert Collins
    Anotherlifeless

A match on displayname ranks higher than email address:
    >>> lifeless3 = factory.makePerson(name="nolife", displayname="RobertC")
    >>> for person in vocab.search("robertc"):
    ...     print(person.displayname)
    ...
    RobertC
    Robert Collins

But even a partial match on name ranks higher:
    >>> lifeless3 = factory.makePerson(name="robertc2", displayname="RobertC")
    >>> for person in vocab.search("robertc"):
    ...     print(person.name)
    ...
    robertc2
    nolife
    lifeless

    >>> login(ANONYMOUS)
    >>> vocab.LIMIT
    100

Search for names with '%' and '?' is supported.

    >>> symbolic_person = factory.makePerson(name="symbolic")
    >>> irc_id = ircid_set.new(
    ...     symbolic_person, "chat.freenode.net", "%percent"
    ... )
    >>> irc_id = ircid_set.new(symbolic_person, "irc.fnord.net", "question?")

    >>> for person in vocab.search("%percent"):
    ...     print(person.name)
    ...
    symbolic

    >>> for person in vocab.search("question?"):
    ...     print(person.name)
    ...
    symbolic

ValidOwner
..........

All valid persons and teams are also valid owners.

    >>> login(ANONYMOUS)
    >>> vocab = get_naked_vocab(None, "ValidOwner")
    >>> vocab.displayname
    'Select a Person or Team'

    >>> list(vocab.search(None))
    []

Almost all teams have the word 'team' as part of their names, so a
search for 'team' will give us some of them. There's also the ircperson
created earlier with an icr nickname of 'team':

    >>> for person in sorted(vocab.search("team"), key=attrgetter("name")):
    ...     print(person.name)
    ...
    hwdb-team
    ircperson
    name18
    name20
    name21
    no-team-memberships
    otherteam
    simple-team
    testing-spanish-team
    ubuntu-security
    ubuntu-team
    warty-gnome

ValidPillarOwner
..........

Valid persons and exclusive teams are valid pillar owners.

    >>> login(ANONYMOUS)
    >>> vocab = get_naked_vocab(None, "ValidPillarOwner")
    >>> vocab.step_title
    'Search for a restricted team, a moderated team, or a person'

    >>> list(vocab.search(None))
    []

Almost all teams have the word 'team' as part of their names, so a
search for 'team' will give us some of them. Only restricted or moderated
teams will be returned in the search results. There's also the ircperson
created earlier with an icr nickname of 'team':

    >>> for person in sorted(vocab.search("team"), key=attrgetter("name")):
    ...     print(person.name)
    ...
    hwdb-team
    ircperson
    name18
    name20
    name21
    no-team-memberships
    otherteam
    simple-team
    testing-spanish-team
    ubuntu-team
    warty-gnome

ValidTeam
.........

The valid team vocabulary is just like the ValidPersonOrTeam vocabulary,
except that its terms are limited only to teams.  No non-team Persons
will be returned.

    >>> vocab = get_naked_vocab(None, "ValidTeam")
    >>> vocab.displayname
    'Select a Team'

    >>> for team in sorted(vocab.search(None), key=attrgetter("displayname")):
    ...     print("%s: %s" % (team.displayname, team.teamowner.displayname))
    ...
    Bass Players: David Allouche
    Canonical Partner Developers: Celso Providelo
    Commercial Subscription Admins: Commercial Member
    Commercial Subscription Approvers: Brad Crittenden
    Drummers: David Allouche
    Flautists: David Allouche
    GuadaMen: Foo Bar
    Guitar Players: David Allouche
    HWDB Team: Foo Bar
    Hoary Gnome Team: Mark Shuttleworth
    Landscape Developers: Sample Person
    Launchpad Administrators: Mark Shuttleworth
    Launchpad Beta Testers: Launchpad Beta Testers Owner
    Launchpad Buildd Admins: Foo Bar
    Launchpad Developers: Foo Bar
    Launchpad PPA Admins: Commercial Subscription Admins
    Launchpad PPA Self Admins: Commercial Subscription Admins
    Launchpad Users: Sample Person
    Mailing List Experts: Launchpad Administrators
    Mirror Administrators: Mark Shuttleworth
    Other Team: Owner
    Registry Administrators: Mark Shuttleworth
    Rosetta Administrators: Launchpad Administrators
    Simple Team: One Membership
    Ubuntu Gnome Team: Mark Shuttleworth
    Ubuntu Security Team: Colin Watson
    Ubuntu Team: Mark Shuttleworth
    Ubuntu Technical Board: Techboard Owner
    Ubuntu Translators: Rosetta Administrators
    VCS imports: Robert Collins
    Warty Gnome Team: Mark Shuttleworth
    Warty Security Team: Mark Shuttleworth
    testing Spanish team: Carlos Perelló Marín

Like with ValidPersonOrTeam, you can narrow your search down by
providing some text to match against the team name.  Still, you only get
teams back.

    >>> for team in sorted(
    ...     vocab.search("spanish"), key=attrgetter("displayname")
    ... ):
    ...     print("%s: %s" % (team.displayname, team.teamowner.displayname))
    testing Spanish team: Carlos Perelló Marín

    >>> for team in sorted(
    ...     vocab.search("spanish OR ubuntu"), key=attrgetter("displayname")
    ... ):
    ...     print("%s: %s" % (team.displayname, team.teamowner.displayname))
    Mirror Administrators: Mark Shuttleworth
    Ubuntu Gnome Team: Mark Shuttleworth
    Ubuntu Security Team: Colin Watson
    Ubuntu Team: Mark Shuttleworth
    Ubuntu Technical Board: Techboard Owner
    Ubuntu Translators: Rosetta Administrators
    testing Spanish team: Carlos Perelló Marín

    >>> for team in sorted(
    ...     vocab.search("team"), key=attrgetter("displayname")
    ... ):
    ...     print("%s: %s" % (team.displayname, team.teamowner.displayname))
    HWDB Team: Foo Bar
    Hoary Gnome Team: Mark Shuttleworth
    Other Team: Owner
    Simple Team: One Membership
    Ubuntu Gnome Team: Mark Shuttleworth
    Ubuntu Security Team: Colin Watson
    Ubuntu Team: Mark Shuttleworth
    Warty Gnome Team: Mark Shuttleworth
    Warty Security Team: Mark Shuttleworth
    testing Spanish team: Carlos Perelló Marín

A user who is a member of a private team will see that team in their
search.

    >>> login("no-priv@canonical.com")
    >>> for team in sorted(
    ...     vocab.search("team"), key=attrgetter("displayname")
    ... ):
    ...     print("%s: %s" % (team.displayname, team.teamowner.displayname))
    HWDB Team: Foo Bar
    Hoary Gnome Team: Mark Shuttleworth
    Other Team: Owner
    Private Team: No Privileges Person
    Simple Team: One Membership
    Ubuntu Gnome Team: Mark Shuttleworth
    Ubuntu Security Team: Colin Watson
    Ubuntu Team: Mark Shuttleworth
    Warty Gnome Team: Mark Shuttleworth
    Warty Security Team: Mark Shuttleworth
    testing Spanish team: Carlos Perelló Marín

You can also search for an email address and get the teams with a match.

    >>> for team in sorted(
    ...     vocab.search("support@"), key=attrgetter("displayname")
    ... ):
    ...     print("%s: %s" % (team.displayname, team.teamowner.displayname))
    Ubuntu Team: Mark Shuttleworth


ValidPerson
...........

All 'valid' persons who are not a team.

    >>> login("foo.bar@canonical.com")
    >>> vocab = get_naked_vocab(None, "ValidPerson")
    >>> vocab.displayname
    'Select a Person'

    >>> people = vocab.search(None)
    >>> people.is_empty()
    False

    >>> invalid_people = [
    ...     person for person in people if not person.is_valid_person
    ... ]
    >>> print(len(invalid_people))
    0

There are two 'Carlos' in the sample data but only one is a valid
person.

    >>> carlos_people = vocab.search("Carlos")
    >>> print(len(list(carlos_people)))
    1

    >>> invalid_carlos = [
    ...     person for person in carlos_people if not person.is_valid_person
    ... ]
    >>> print(len(invalid_carlos))
    0

ValidPerson does not include teams.

    >>> carlos = getUtility(IPersonSet).getByName("carlos")
    >>> carlos_team = factory.makeTeam(owner=carlos, name="carlos-team")
    >>> person_or_team_vocab = get_naked_vocab(None, "ValidPersonOrTeam")
    >>> carlos_people_or_team = person_or_team_vocab.search("carlos")
    >>> print(len(list(carlos_people_or_team)))
    2

    >>> carlos_team in carlos_people_or_team
    True

    >>> carlos_people = vocab.search("carlos")
    >>> print(len(list(carlos_people)))
    1

    >>> carlos_team in carlos_people
    False


DistributionOrProductVocabulary
...............................

All products and distributions. Note that the value type is
heterogeneous.

    >>> vocab = get_naked_vocab(None, "DistributionOrProduct")
    >>> for term in vocab:
    ...     if "buntu" in term.title:
    ...         print(term.title, "- class", term.value.__class__.__name__)
    ...
    Kubuntu - class Distribution
    Ubuntu - class Distribution
    ubuntutest - class Distribution

They can be looked up by their aliases too.

    >>> vocab.getTermByToken("firefox").token
    'firefox'

    >>> login("mark@example.com")
    >>> product_set["firefox"].setAliases(["iceweasel"])
    >>> current_user = launchbag.user
    >>> ignored = login_person(current_user)
    >>> vocab.getTermByToken("iceweasel").token
    'firefox'

    >>> [term.token for term in vocab.searchForTerms(query="iceweasel")]
    ['firefox']

Aliases are not among the terms when their name does not match the
token/name.

    >>> [term.token for term in vocab.searchForTerms(query="ubuntu")]
    ['ubuntu', 'kubuntu', 'ubuntutest']

    >>> vocab.getTermByToken("ubuntu").token
    'ubuntu'

Inactive projects and project groups are not available.

    >>> for term in vocab:
    ...     if "Tomcat" in term.title:
    ...         print(term.title, "- class", term.value.__class__.__name__)
    ...
    Tomcat - class Product

    >>> tomcat = product_set.getByName("tomcat")
    >>> tomcat in vocab
    True

    >>> tomcat.active = False
    >>> flush_database_updates()
    >>> vocab = get_naked_vocab(None, "DistributionOrProduct")
    >>> tomcat in vocab
    False

    >>> tomcat.active = True
    >>> flush_database_updates()
    >>> vocab = get_naked_vocab(None, "DistributionOrProduct")
    >>> tomcat in vocab
    True

Project groups are not contained in this vocabulary:

    >>> apache = getUtility(IProjectGroupSet).getByName("apache")
    >>> apache in vocab
    False


DistributionOrProductOrProjectGroupVocabulary
.............................................

All products, project groups and distributions. Note that the value type
is heterogeneous.

    >>> vocab = get_naked_vocab(None, "DistributionOrProductOrProjectGroup")
    >>> for term in vocab:
    ...     if "buntu" in term.title:
    ...         print(term.title, "- class", term.value.__class__.__name__)
    ...
    Kubuntu - class Distribution
    Ubuntu - class Distribution
    ubuntutest - class Distribution

They can be looked up by their aliases too.

    >>> vocab.getTermByToken("ubuntu").token
    'ubuntu'

    >>> from lp.registry.interfaces.distribution import IDistributionSet
    >>> login("mark@example.com")
    >>> getUtility(IDistributionSet)["ubuntu"].setAliases(["ubantoo"])
    >>> ignored = login_person(current_user)
    >>> vocab.getTermByToken("ubantoo").token
    'ubuntu'

    >>> [term.token for term in vocab.searchForTerms(query="ubantoo")]
    ['ubuntu']

Inactive projects and project groups are not available.

    >>> tomcat = product_set.getByName("tomcat")
    >>> tomcat in vocab
    True

    >>> tomcat.active = False
    >>> tomcat in vocab
    False

    >>> apache = getUtility(IProjectGroupSet).getByName("apache")
    >>> apache in vocab
    True

    >>> apache.active = False
    >>> apache in vocab
    False

    >>> vocab = get_naked_vocab(None, "DistributionOrProductOrProjectGroup")
    >>> for term in vocab:
    ...     if "Apache" in term.title:
    ...         print(term.title, "- class", term.value.__class__.__name__)
    ...
    >>> for term in vocab:
    ...     if "Tomcat" in term.title:
    ...         print(term.title, "- class", term.value.__class__.__name__)
    ...
    >>> product_set.getByName("tomcat").active = True
    >>> getUtility(IProjectGroupSet).getByName("apache").active = True
    >>> flush_database_updates()
    >>> vocab = get_naked_vocab(None, "DistributionOrProductOrProjectGroup")
    >>> for term in vocab:
    ...     if "Apache" in term.title:
    ...         print(term.title, "- class", term.value.__class__.__name__)
    ...
    Apache - class ProjectGroup

    >>> for term in vocab:
    ...     if "Tomcat" in term.title:
    ...         print(term.title, "- class", term.value.__class__.__name__)
    ...
    Tomcat - class Product


FeaturedProjectVocabulary
-------------------------

The featured project vocabulary contains all the projects that are
featured on Launchpad. It is a subset of the
DistributionOrProductOrProjectGroupVocabulary (defined using the
_clauseTables).

    >>> featured_project_vocabulary = get_naked_vocab(None, "FeaturedProject")
    >>> len(featured_project_vocabulary)
    9

    >>> for term in featured_project_vocabulary:
    ...     print(term.token, term.title)
    ...
    applets         Gnome Applets
    bazaar          Bazaar
    firefox         Mozilla Firefox
    gentoo          Gentoo
    gnome           GNOME
    gnome-terminal  GNOME Terminal
    mozilla         The Mozilla Project
    thunderbird     Mozilla Thunderbird
    ubuntu          Ubuntu

    >>> ubuntu = getUtility(ILaunchpadCelebrities).ubuntu
    >>> ubuntu in featured_project_vocabulary
    True

    >>> debian = getUtility(ILaunchpadCelebrities).debian
    >>> debian in featured_project_vocabulary
    False
