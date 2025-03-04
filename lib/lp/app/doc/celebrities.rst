Launchpad Celebrities
=====================

https://web.archive.org/web/20220627104653/https://dev.launchpad.net \
    /LaunchpadCelebrities

There are a number of special objects, some of which exist in the
database, which we want to give easy access to in the code. To this end,
there is an ILaunchpadCelebrities utility available that gives access to
these well-known objects through attributes.

    >>> from lp.app.interfaces.launchpad import ILaunchpadCelebrities
    >>> from lp.services.worlddata.interfaces.language import ILanguageSet
    >>> from lp.registry.interfaces.person import IPerson, IPersonSet
    >>> celebs = getUtility(ILaunchpadCelebrities)

    >>> from lp.testing import verifyObject
    >>> verifyObject(ILaunchpadCelebrities, celebs)
    True


admin
-----

The 'admins' team contain the user who have super-power over all of
Launchpad. This team is accessible through the admin attribute.

    >>> personset = getUtility(IPersonSet)
    >>> admins = personset.getByName("admins")
    >>> celebs.admin == admins
    True


vcs-imports
-----------

The vcs-imports celebrity owns the branches created by importd.

    >>> vcs_imports = personset.getByName("vcs-imports")
    >>> celebs.vcs_imports == vcs_imports
    True


english
-------

The English language is used in many places.  It's the native language
for translation, as well as for Launchpad itself.

    >>> english = getUtility(ILanguageSet).getLanguageByCode("en")
    >>> english == celebs.english
    True


registry_experts
----------------

The registry_experts celebrity has permissions to perform registry
gardening operations.

    >>> registry = personset.getByName("registry")
    >>> celebs.registry_experts == registry
    True


buildd_admin
------------

The buildd_admin celebrity has permission to perform routine task in the
buildfarm.

    >>> buildd_admin = personset.getByName("launchpad-buildd-admins")
    >>> celebs.buildd_admin == buildd_admin
    True


bug_watch_updater
-----------------

The bug_watch_updater celebrity updates the bug watches.

    >>> bug_watch_updater = personset.getByName("bug-watch-updater")
    >>> celebs.bug_watch_updater == bug_watch_updater
    True


sourceforge_tracker
-------------------

For all the products using SourceForge, we have a single registered
tracker

    >>> from lp.bugs.interfaces.bugtracker import IBugTrackerSet
    >>> sf_tracker = getUtility(IBugTrackerSet).getByName("sf")
    >>> celebs.sourceforge_tracker == sf_tracker
    True


janitor
-------

We have the Launchpad Janitor which takes care of expiring old
questions, team memberships when they reach their expiry date, and old
incomplete bugtasks.

    >>> janitor = personset.getByName("janitor")
    >>> celebs.janitor == janitor
    True


launchpad
---------

The Launchpad product itself.

    >>> from lp.registry.interfaces.product import IProductSet
    >>> launchpad = getUtility(IProductSet).getByName("launchpad")
    >>> celebs.launchpad == launchpad
    True


obsolete_junk
-------------

The 'Obsolete Junk' project is used to hold undeletable objects like
productseries that other projects no longer want.

    >>> obsolete_junk = getUtility(IProductSet).getByName("obsolete-junk")
    >>> celebs.obsolete_junk == obsolete_junk
    True


commercial_admin
----------------

There is a 'Commercial Subscription Admins' team that has administrative
power over the licence review process and has the ability to de-activate
projects.

    >>> commercial_admin = personset.getByName("commercial-admins")
    >>> celebs.commercial_admin == commercial_admin
    True


Savannah bug tracker
--------------------

There is a 'Savannah Bug Tracker' bugtracker which represents the bug
tracker for all registered Savannah projects.

    >>> from lp.bugs.interfaces.bugtracker import IBugTrackerSet
    >>> savannah_tracker = getUtility(IBugTrackerSet).getByName("savannah")
    >>> celebs.savannah_tracker == savannah_tracker
    True

The Savannah bug tracker also has a BugTrackerAlias with the URL
http://savannah.nognu.org/

    >>> for alias in celebs.savannah_tracker.aliases:
    ...     print(alias)
    ...
    http://savannah.nognu.org/


Gnome Bugzilla
--------------

There is a 'Gnome Bugzilla' celebrity, which is used to represent the
Gnome Bugzilla instance by the checkwatches script.

    >>> gnome_bugzilla = getUtility(IBugTrackerSet).getByName("gnome-bugs")
    >>> celebs.gnome_bugzilla == gnome_bugzilla
    True


PPA key guard
-------------

There is a 'PPA key guard' celebrity which owns all PPA 'signing_keys'.

    >>> ppa_key_guard = personset.getByName("ppa-key-guard")
    >>> celebs.ppa_key_guard == ppa_key_guard
    True


Ubuntu technical board
----------------------

There's a celebrity for the Ubuntu technical board, the 'techboard'
team. It's used for determining who is allowed to create new package
sets.

    >>> ubuntu_techboard = personset.getByName("techboard")
    >>> print(ubuntu_techboard.name)
    techboard

    >>> celebs.ubuntu_techboard == ubuntu_techboard
    True


Person celebrities
------------------

Each person celebrity has a corresponding "in_" attribute in
IPersonRoles, to check if a person has that role. If the attributes
differ, IPersonRoles needs to be synced to ILaunchpadCelebrities by
adding/removing the appropriate "in_" attribute(s).

    >>> from lp.registry.interfaces.role import IPersonRoles
    >>> def get_person_celebrity_names():
    ...     for name in ILaunchpadCelebrities.names():
    ...         if IPerson.providedBy(getattr(celebs, name)):
    ...             yield "in_" + name
    ...
    >>> def get_person_roles_names():
    ...     for name in IPersonRoles.names():
    ...         if name.startswith("in_"):
    ...             yield name
    ...

Treating the lists as sets and determining their difference gives us a
clear picture of what is missing where.

    >>> person_celebrity_names = set(get_person_celebrity_names())
    >>> person_roles_names = set(get_person_roles_names())
    >>> print(
    ...     "Please add to IPersonRoles: "
    ...     + (", ".join(list(person_celebrity_names - person_roles_names)))
    ... )
    Please add to IPersonRoles:

    >>> print(
    ...     "Please remove from IPersonRoles: "
    ...     + (", ".join(list(person_roles_names - person_celebrity_names)))
    ... )
    Please remove from IPersonRoles:


Detecting if a person is a celebrity
------------------------------------

We can ask if a person has celebrity status.

    >>> celebs.isCelebrityPerson(ubuntu_techboard.name)
    True

    >>> celebs.isCelebrityPerson(obsolete_junk.name)
    False

    >>> celebs.isCelebrityPerson("admins")
    True

    >>> celebs.isCelebrityPerson("admin")
    False

    >>> celebs.isCelebrityPerson("janitor")
    True


