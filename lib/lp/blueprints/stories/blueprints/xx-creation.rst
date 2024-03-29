Creating Blueprints
===================

Set Up
------
A number of tests in this need a product with blueprints enabled, so we'll
enable them on bazaar, firefox, and jokosher.

    >>> from zope.component import getUtility
    >>> from lp.app.enums import ServiceUsage
    >>> from lp.registry.interfaces.product import IProductSet
    >>> login("admin@canonical.com")
    >>> bazaar = getUtility(IProductSet).getByName("bzr")
    >>> bazaar.blueprints_usage = ServiceUsage.LAUNCHPAD
    >>> firefox = getUtility(IProductSet).getByName("firefox")
    >>> firefox.blueprints_usage = ServiceUsage.LAUNCHPAD
    >>> jokosher = getUtility(IProductSet).getByName("jokosher")
    >>> jokosher.blueprints_usage = ServiceUsage.LAUNCHPAD
    >>> transaction.commit()
    >>> logout()

Introduction
------------

Users can register blueprints from many locations in Launchpad. To start with,
it's possible to register a blueprint from the Blueprints home page. However,
users can also register blueprints from any of the following locations:

 * a distribution
 * a distribution series
 * a product
 * a product series
 * a project
 * a sprint


The blueprint registration form
-------------------------------


Launchpad provides a dedicated form page for users to register blueprints.
Generally speaking, users can navigate to this form from each of the supported
locations in the same way, by following either of two links provided:

 * a graphical "Register a blueprint" button in the main area.
 * a textual "Register a blueprint" link, for locations with an action panel.

Since these two types of links always share a common textual representation,
we'll use extra care when its necessary to demonstrate that they both exist.


Navigating to the blueprint registration form
---------------------------------------------

We'll start by demonstrating that users can navigate to the blueprint
registration form from each of the supported locations.


From the Blueprints home page
.............................

Starting from the Blueprints home page:

    >>> user_browser.open("http://blueprints.launchpad.test/")

Users can press the graphical "Register a blueprint" button:

    >>> print(find_tag_by_id(user_browser.contents, "addspec"))
    <a href="+new" id="addspec"> <img alt="Register a blueprint"...


From a distribution
...................

Starting from the Ubuntu distribution page:

    >>> user_browser.open("http://blueprints.launchpad.test/ubuntu")

Users can use the ISpecificationTarget involvement menu to register a
blueprint.

    >>> print(
    ...     extract_text(
    ...         find_tag_by_id(user_browser.contents, "involvement").a
    ...     )
    ... )
    Register a blueprint

Users can also follow the textual "Register a blueprint" link:

    >>> for tag in find_tags_by_class(user_browser.contents, "menu-link-new"):
    ...     print(tag)
    ...
    <a class="menu-link-new..."
       href="http://blueprints.launchpad.test/ubuntu/+addspec">Register
       a blueprint</a>


From a distribution series
..........................

Starting from the Ubuntu Hoary distribution series page:

    >>> user_browser.open("http://blueprints.launchpad.test/ubuntu/hoary")

Users can also follow the textual "Register a blueprint" link:

    >>> for tag in find_tags_by_class(user_browser.contents, "menu-link-new"):
    ...     print(tag)
    ...
    <a class="menu-link-new..."
       href="http://blueprints.launchpad.test/ubuntu/hoary/+addspec">Register
       a blueprint</a>


From a product
..............

Starting from the Bazaar product page:

    >>> user_browser.open("http://blueprints.launchpad.test/bzr")


Users can also follow the textual "Register a blueprint" link:

    >>> for tag in find_tags_by_class(user_browser.contents, "menu-link-new"):
    ...     print(tag)
    ...
    <a class="menu-link-new..."
       href="http://blueprints.launchpad.test/bzr/+addspec">Register
       a blueprint</a>

For products without any blueprints, users can follow the special "register
it here as a blueprint" link:

    >>> user_browser.getLink("register it here as a blueprint").click()
    >>> print(user_browser.url)
    http://blueprints.launchpad.test/bzr/+addspec
    >>> print(user_browser.title)
    Register a blueprint in...
    >>> print(extract_text(find_main_content(user_browser.contents)))
    Register a new blueprint...

From a product series
.....................

Starting from the Mozilla Firefox product series page:

    >>> user_browser.open("http://blueprints.launchpad.test/firefox/1.0")


Users can also follow the textual "Register a blueprint" link:

    >>> for tag in find_tags_by_class(user_browser.contents, "menu-link-new"):
    ...     print(tag)
    ...
    <a class="menu-link-new..."
       href="http://blueprints.launchpad.test/firefox/1.0/+addspec">Register
       a blueprint</a>


From a project
..............

Starting from the Mozilla project page:

    >>> user_browser.open("http://blueprints.launchpad.test/mozilla")

Users can follow the textual "Register a blueprint" link:

    >>> for tag in find_tags_by_class(user_browser.contents, "menu-link-new"):
    ...     print(tag)
    ...
    <a class="menu-link-new..."
       href="http://blueprints.launchpad.test/mozilla/+addspec">Register
       a blueprint</a>


From a sprint
.............

Starting from the Future Mega Meeting sprint page:

    >>> from datetime import datetime, timedelta, timezone

    >>> login("test@canonical.com")
    >>> _ = factory.makeSprint(
    ...     name="futurista",
    ...     title="Future Mega Meeting",
    ...     time_starts=datetime.now(timezone.utc) + timedelta(days=1),
    ... )
    >>> logout()

    >>> user_browser.open(
    ...     "http://blueprints.launchpad.test/sprints/futurista"
    ... )

Users can also follow the textual "Register a blueprint" link:

    >>> for tag in find_tags_by_class(user_browser.contents, "menu-link-new"):
    ...     print(tag)  # noqa
    ...
    <a class="menu-link-new..."
     href="http://blueprints.launchpad.test/sprints/futurista/+addspec">Register
       a blueprint</a>


Registering a blueprint
-----------------------

The blueprint registration form allows users to register a blueprint. The
appearance and behaviour of the form depends on where the user has navigated
from.


Registering a blueprint from the Blueprints home page
.....................................................

We'll start from the default blueprint registration form:

    >>> user_browser.open("http://blueprints.launchpad.test/specs/+new")

Canceling creation, brings one back to the blueprints home page.

    >>> user_browser.getLink("Cancel").url
    'http://blueprints.launchpad.test/'

When a blueprint is registered from the Blueprints home page, Launchpad
requires the user to specify a target for the new blueprint. This target
must be an existing distribution or product in Launchpad.

We'll choose Ubuntu as a target for the new blueprint:

    >>> control = user_browser.getControl
    >>> control("For").value = "ubuntu"

By default, new blueprints have the 'New' status:

    >>> control("Status").value
    ['NEW']

Let's continue by completing the rest of the form:

    >>> summary = (
    ...     "Users are increasingly using multiple networks. Being able to "
    ...     "seamlessly move between networks whilst remembering the correct "
    ...     "settings for each network would greatly enhance Ubuntu's "
    ...     "usability for mobile professionals. Many network dependent "
    ...     "services should only be run when the system is positive that it "
    ...     "has a network. This would greatly enhance the system's "
    ...     "flexibility and responsiveness."
    ... )
    >>> control("Name").value = "networkmagic"
    >>> control("Title").value = "Network Magic: Auto Network Detection"
    >>> control("URL").value = "http://wiki.ubuntu.com/NetworkMagic"
    >>> control("Status").value = ["APPROVED"]
    >>> control("Summary").value = summary
    >>> control("Assignee").value = "daf@canonical.com"
    >>> control("Drafter").value = "carlos@canonical.com"
    >>> control("Approver").value = "tsukimi@quaqua.net"

Pressing the "Register Blueprint" button creates a blueprint targeted to the
Ubuntu distribution, then redirects the user to the new blueprint's page:

    >>> control("Register Blueprint").click()
    >>> user_browser.url
    'http://blueprints.launchpad.test/ubuntu/+spec/networkmagic'
    >>> print(user_browser.title)
    Network Magic: Auto Network Detection...


Registering a blueprint from a distribution
...........................................

When a blueprint is registered from a distribution, the new blueprint is
automatically targeted to the distribution.

Let's register a blueprint from the Ubuntu distribution:

    >>> user_browser.open("http://blueprints.launchpad.test/ubuntu/+addspec")
    >>> control("Name").value = "networkmagic-1"
    >>> control("Title").value = "Network Magic: Auto Network Detection"
    >>> control("URL").value = "http://wiki.ubuntu.com/NetworkMagic-1"
    >>> control("Summary").value = summary

Pressing the "Register Blueprint" button creates a blueprint targeted to the
Ubuntu distribution, then redirects the user to the new blueprint's page:

    >>> control("Register Blueprint").click()
    >>> user_browser.url
    'http://blueprints.launchpad.test/ubuntu/+spec/networkmagic-1'
    >>> print(user_browser.title)
    Network Magic: Auto Network Detection...


Registering a blueprint from a distribution series
..................................................

When a blueprint is registered from a distribution series, the new blueprint
is automatically targeted to the parent distribution. In addition, Launchpad
allows (but does not require) the user to propose the blueprint as a goal for
the series.

Let's register a blueprint from the Ubuntu Hoary distribution series:

    >>> user_browser.open(
    ...     "http://blueprints.launchpad.test/ubuntu/hoary/+addspec"
    ... )
    >>> control("Name").value = "networkmagic-2"
    >>> control("Title").value = "Network Magic: Auto Network Detection"
    >>> control("URL").value = "http://wiki.ubuntu.com/NetworkMagic2"
    >>> control("Summary").value = summary

Canceling creation, brings one back to the blueprints Hoary home.

    >>> user_browser.getLink("Cancel").url
    'http://blueprints.launchpad.test/ubuntu/hoary'

By default, blueprints are not proposed as series goals:

    >>> bool(control("series goal").control.value)
    False

Pressing the "Register Blueprint" button creates a blueprint targeted to the
Ubuntu distribution, then redirects the user to the new blueprint's page:

    >>> control("Register Blueprint").click()
    >>> user_browser.url
    'http://blueprints.launchpad.test/ubuntu/+spec/networkmagic-2'
    >>> print(user_browser.title)
    Network Magic: Auto Network Detection...

The new blueprint is not proposed as a series goal:

    >>> print(user_browser.getLink("Propose as goal"))
    <Link ...Propose as goal...

Let's register another blueprint from the Mozilla Firefox 1.0 product series:

    >>> user_browser.open(
    ...     "http://blueprints.launchpad.test/ubuntu/hoary/+addspec"
    ... )
    >>> control("Name").value = "networkmagic-3"
    >>> control("Title").value = "Network Magic: Auto Network Detection"
    >>> control("URL").value = "http://wiki.ubuntu.com/NetworkMagic3"
    >>> control("Summary").value = summary

This time, we'll nominate the blueprint as a series goal:

    >>> control("series goal").control.value = True

Pressing the "Register Blueprint" button creates a blueprint targeted to the
Ubuntu distribution, then redirects the user to the new blueprint's page:

    >>> control("Register Blueprint").click()
    >>> user_browser.url
    'http://blueprints.launchpad.test/ubuntu/+spec/networkmagic-3'
    >>> print(user_browser.title)
    Network Magic: Auto Network Detection...

As requested, the new blueprint is proposed as a series goal:

    >>> print(
    ...     extract_text(find_tag_by_id(user_browser.contents, "series-goal"))
    ... )
    Series goal: Proposed for hoary

If the registration is performed by a user with permission to accept goals
for the series, the new blueprint is automatically accepted as a series goal:

    >>> admin_browser.open(
    ...     "http://blueprints.launchpad.test/ubuntu/hoary/+addspec"
    ... )
    >>> control = admin_browser.getControl
    >>> control("Name").value = "networkmagic-4"
    >>> control("Title").value = "Network Magic: Auto Network Detection"
    >>> control("URL").value = "http://wiki.ubuntu.com/NetworkMagic4"
    >>> control("Summary").value = summary
    >>> control("series goal").control.value = True
    >>> control("Register Blueprint").click()
    >>> print(admin_browser.title)
    Network Magic: Auto Network Detection...
    >>> print(
    ...     extract_text(
    ...         find_tag_by_id(admin_browser.contents, "series-goal")
    ...     )
    ... )
    Series goal: Accepted for hoary


Registering a blueprint from a product
......................................

When a blueprint is registered from a product, the new blueprint is
automatically targeted to the product.

Let's register a blueprint from the Mozilla Firefox product:

    >>> user_browser.open("http://blueprints.launchpad.test/firefox/+addspec")
    >>> control = user_browser.getControl
    >>> control("Name").value = "svg-support-1"
    >>> control("Title").value = "SVG Support"
    >>> control("URL").value = "http://wiki.firefox.com/SvgSupport1"
    >>> control("Summary").value = summary

Canceling creation, brings one back to the blueprints Firefox home.

    >>> user_browser.getLink("Cancel").url
    'http://blueprints.launchpad.test/firefox'

Pressing the "Register Blueprint" button creates a blueprint targeted to the
Mozilla Firefox product, then redirects the user to the new blueprint's page:

    >>> control("Register Blueprint").click()
    >>> user_browser.url
    'http://blueprints.launchpad.test/firefox/+spec/svg-support-1'
    >>> print(user_browser.title)
    SVG Support...


Registering a blueprint from a product series
.............................................

When a blueprint is registered from a product series, the new blueprint is
automatically targeted to the parent product. In addition, Launchpad allows
(but does not require) the user to propose the blueprint as a goal for the
series.

Let's register a blueprint from the Mozilla Firefox 1.0 product series:

    >>> user_browser.open(
    ...     "http://blueprints.launchpad.test/firefox/1.0/+addspec"
    ... )
    >>> control("Name").value = "svg-support-2"
    >>> control("Title").value = "SVG Support"
    >>> control("URL").value = "http://wiki.firefox.com/SvgSupport2"
    >>> control("Summary").value = summary

By default, blueprints are not proposed as series goals:

    >>> bool(control("series goal").control.value)
    False

Pressing the "Register Blueprint" button creates a blueprint targeted to the
Mozilla Firefox product, then redirects the user to the new blueprint's page:

    >>> control("Register Blueprint").click()
    >>> user_browser.url
    'http://blueprints.launchpad.test/firefox/+spec/svg-support-2'
    >>> print(user_browser.title)
    SVG Support...

The new blueprint is not proposed as a series goal:

    >>> print(user_browser.getLink("Propose as goal"))
    <Link ...Propose as goal...

Let's register another blueprint from the Mozilla Firefox 1.0 product series:

    >>> user_browser.open(
    ...     "http://blueprints.launchpad.test/firefox/1.0/+addspec"
    ... )
    >>> control("Name").value = "svg-support-3"
    >>> control("Title").value = "SVG Support"
    >>> control("URL").value = "http://wiki.firefox.com/SvgSupport3"
    >>> control("Summary").value = summary

This time, we'll nominate the blueprint as a series goal:

    >>> control("series goal").control.value = True

Pressing the "Register Blueprint" button creates a blueprint targeted to the
Mozilla Firefox product, then redirects the user to the new blueprint's page:

    >>> control("Register Blueprint").click()
    >>> user_browser.url
    'http://blueprints.launchpad.test/firefox/+spec/svg-support-3'
    >>> print(user_browser.title)
    SVG Support...

As requested, the new blueprint is proposed as a series goal:

    >>> content = find_main_content(user_browser.contents)
    >>> print(extract_text(find_tag_by_id(content, "series-goal")))
    Series goal: Proposed for 1.0

If the registration is performed by a user with permission to accept goals
for the series, the new blueprint is automatically accepted as a series goal:

    >>> admin_browser.open(
    ...     "http://blueprints.launchpad.test/firefox/1.0/+addspec"
    ... )
    >>> control = admin_browser.getControl
    >>> control("Name").value = "svg-support-4"
    >>> control("Title").value = "SVG Support"
    >>> control("URL").value = "http://wiki.firefox.com/SvgSupport4"
    >>> control("Summary").value = summary
    >>> control("series goal").control.value = True
    >>> control("Register Blueprint").click()
    >>> content = find_main_content(admin_browser.contents)
    >>> print(extract_text(content.h1))
    SVG Support...
    >>> print(extract_text(find_tag_by_id(content, "series-goal")))
    Series goal: Accepted for 1.0


Registering a blueprint from a project
......................................

Let's register a blueprint from the Mozilla project:

    >>> user_browser.open("http://blueprints.launchpad.test/mozilla/+addspec")

When a blueprint is registered from a project, Launchpad requires the user to
provide a target for the new blueprint. This target must be an existing
product that belongs to the project in Launchpad.

We'll choose Mozilla Firefox, a product of the Mozilla project, as a target
for the new blueprint:

    >>> control = user_browser.getControl
    >>> control("For").value = ["firefox"]

Let's continue by completing the rest of the form:

    >>> control("Name").value = "svg-support-5"
    >>> control("Title").value = "SVG Support"
    >>> control("URL").value = "http://wiki.firefox.com/SvgSupport5"
    >>> control("Summary").value = summary

Pressing the "Register Blueprint" button creates a blueprint targeted to the
Mozilla Firefox project, then redirects the user to the new blueprint's page:

    >>> control("Register Blueprint").click()
    >>> user_browser.url
    'http://blueprints.launchpad.test/firefox/+spec/svg-support-5'
    >>> print(user_browser.title)
    SVG Support...


Registering a blueprint from a sprint
.....................................

When a blueprint is registered from a sprint, the new blueprint is
automatically proposed as a topic for discussion at the sprint.

Let's register a blueprint from the Future Mega Meeting sprint:

    >>> user_browser.open(
    ...     "http://blueprints.launchpad.test/sprints/futurista/+addspec"
    ... )

Since sprints by themselves are not directly related to distributions or
products, Launchpad requires the user to specify a target for the new
blueprint. This target must be an existing distribution or product.

We'll choose Bazaar as a target for the new blueprint:

    >>> control("For").value = "bzr"

Let's continue by completing the rest of the form:

    >>> control("Name").value = "darcs-imports"
    >>> control("Title").value = "Importing from Darcs"
    >>> control("URL").value = "http://bazaar-vcs.org/DarcsImports"
    >>> control("Summary").value = summary

Pressing the "Register blueprint" button creates a blueprint targeted to the
Bazaar project. In the special case of registering a blueprint from a sprint,
the user is then redirected back to the sprint page:

    >>> control("Register Blueprint").click()
    >>> user_browser.url
    'http://blueprints.launchpad.test/sprints/futurista'
    >>> print(extract_text(find_main_content(user_browser.contents)))
    Blueprints for Future Mega Meeting...

In addition, the new blueprint is automatically proposed as a topic for
discussion at the sprint:

    >>> admin_browser.open(
    ...     "http://blueprints.launchpad.test/sprints/futurista/+settopics"
    ... )
    >>> print(find_tag_by_id(admin_browser.contents, "speclisting"))
    <...darcs-imports...

If the registration is performed by a user with permission to accept topics
for discussion at the sprint, the new blueprint is automatically accepted as
a sprint topic:

    >>> admin_browser.open(
    ...     "http://blueprints.launchpad.test/sprints/futurista/+addspec"
    ... )
    >>> control = admin_browser.getControl
    >>> control("For").value = "bzr"
    >>> control("Name").value = "darcs-imports-2"
    >>> control("Title").value = "Importing from Darcs"
    >>> control("URL").value = "http://bazaar-vcs.org/DarcsImports2"
    >>> control("Summary").value = summary
    >>> control("Register Blueprint").click()
    >>> print(extract_text(find_main_content(admin_browser.contents)))
    Blueprints for Future Mega Meeting...
    >>> print(find_tag_by_id(admin_browser.contents, "speclisting"))
    <...darcs-imports-2...


Proposing any blueprint as a sprint topic during registration
.............................................................

While blueprints can be registered from sprints directly, it's also possible
to propose any blueprint for discussion at a sprint during registration.

When registering a blueprint, users can specify the ''sprint'' field to
propose the blueprint as a topic for discussion at the sprint. If the user has
permission, the blueprint will be automatically added to the sprint agenda:

    >>> from lp.registry.interfaces.person import IPersonSet
    >>> login("test@canonical.com")
    >>> rome_sprint = factory.makeSprint(name="rome")
    >>> logout()
    >>> ignored = login_person(rome_sprint.owner)
    >>> rome_sprint.time_ends = datetime.now(timezone.utc) + timedelta(30)
    >>> rome_sprint.time_starts = datetime.now(timezone.utc) + timedelta(20)
    >>> sample_person = getUtility(IPersonSet).getByName("name12")
    >>> rome_sprint.driver = sample_person
    >>> logout()

    >>> sample_browser = setupBrowser("Basic test@canonical.com:test")
    >>> sample_browser.open("http://blueprints.launchpad.test/jokosher")
    >>> sample_browser.getLink("Register a blueprint").click()
    >>> sample_browser.getControl("Name").value = "spec-for-sprint"
    >>> sample_browser.getControl("Title").value = "Spec for Sprint"
    >>> summary = "A spec to be discussed at a sprint"
    >>> sample_browser.getControl("Summary").value = summary
    >>> sample_browser.getControl("Propose for sprint").value = ["rome"]
    >>> sample_browser.getControl("Register Blueprint").click()
    >>> sample_browser.url
    'http://blueprints.launchpad.test/jokosher/+spec/spec-for-sprint'
    >>> print(sample_browser.title)
    Spec for Sprint...
    >>> sample_browser.open("http://blueprints.launchpad.test/sprints/rome")
    >>> find_tag_by_id(sample_browser.contents, "speclisting")
    <...spec-for-sprint...>


Restrictions when registering blueprints
----------------------------------------

Names must be unique
....................

It's not possible to register a blueprint with the same name as an existing
blueprint.

Attempting to register a duplicate blueprint from a target context produces
an error:

    >>> user_browser.open("http://blueprints.launchpad.test/ubuntu/+addspec")
    >>> control = user_browser.getControl
    >>> control("Name").value = "networkmagic"
    >>> control("Title").value = "Network Magic: Automatic Network Detection"
    >>> control("URL").value = "http://wiki.ubuntu.com/NetworkMagicNew"
    >>> control("Summary").value = summary
    >>> control("Register Blueprint").click()
    >>> user_browser.url
    'http://blueprints.launchpad.test/ubuntu/+addspec'
    >>> for message in find_tags_by_class(user_browser.contents, "message"):
    ...     print(message.decode_contents())
    ...
    There is 1 error...already in use by another blueprint...

Attempting to register a duplicate blueprint from a non-target context
produces the same error:

    >>> url = "http://blueprints.launchpad.test/sprints/rome/+addspec"
    >>> user_browser.open(url)
    >>> user_browser.getControl("For").value = "ubuntu"
    >>> user_browser.getControl("Name").value = "media-integrity-check"
    >>> user_browser.getControl("Title").value = (
    ...     "A blueprint with a name that already exists"
    ... )
    >>> user_browser.getControl("Summary").value = (
    ...     "There is already a blueprint with this name"
    ... )
    >>> user_browser.getControl("Register Blueprint").click()
    >>> print(user_browser.url)
    http://blueprints.launchpad.test/sprints/rome/+addspec
    >>> for message in find_tags_by_class(user_browser.contents, "message"):
    ...     print(message.decode_contents())
    ...
    There is 1 error...already in use by another blueprint...


Names must be valid
...................

Blueprint names must conform to a set pattern:

    >>> user_browser.open("http://blueprints.launchpad.test/ubuntu/+addspec")
    >>> control("Name").value = "NetworkMagic!"
    >>> control("Title").value = "Network Magic: Automatic Network Detection"
    >>> control("URL").value = "http://wiki.ubuntu.com/NetworkMagicBang"
    >>> control("Summary").value = summary
    >>> control("Register Blueprint").click()
    >>> user_browser.url
    'http://blueprints.launchpad.test/ubuntu/+addspec'
    >>> for message in find_tags_by_class(user_browser.contents, "message"):
    ...     print(message.decode_contents())
    ...
    There is 1 error...Invalid name...

However, some invalid names can be transformed into valid names. When it is
clear that a valid name can be produced by removing trailing spaces or by
converting upper case characters to their lower case equivalents, this is done
automatically for the user:

    >>> user_browser.open("http://blueprints.launchpad.test/ubuntu/+addspec")
    >>> control("Name").value = "New-Network-Magic"
    >>> control("Title").value = "Network Magic: Automatic Network Detection"
    >>> control("URL").value = "http://wiki.ubuntu.com/NewNetworkMagic"
    >>> control("Summary").value = summary
    >>> control("Register Blueprint").click()
    >>> user_browser.url
    'http://blueprints.launchpad.test/ubuntu/+spec/new-network-magic'
    >>> print(user_browser.title)
    Network Magic: Automatic Network Detection...


URLs must be unique
...................

It's not possible to register a blueprint with the same URL as an existing
blueprint:

    >>> user_browser.open("http://blueprints.launchpad.test/ubuntu/+addspec")
    >>> control("Name").value = "dupenetworkmagic"
    >>> control("Title").value = "This is a dupe Network Magic Spec"
    >>> control("URL").value = "http://wiki.ubuntu.com/NetworkMagic"
    >>> control("Summary").value = summary
    >>> control("Register Blueprint").click()
    >>> user_browser.url
    'http://blueprints.launchpad.test/ubuntu/+addspec'
    >>> for message in find_tags_by_class(user_browser.contents, "message"):
    ...     print(message.decode_contents())
    ...
    There is 1 error...is already registered by...
    ...Network Magic: Auto Network Detection...


Registering blueprints from other locations
...........................................

There are some locations in Launchpad from which it's not possible to register
a blueprint. To start with, it's not possible to register a blueprint from an
individual user's blueprint listing page:

    >>> user_browser.open("http://blueprints.launchpad.test/~mark")
    >>> print(user_browser.getLink("Register a blueprint"))
    Traceback (most recent call last):
        ...
    zope.testbrowser.browser.LinkNotFoundError

It's also not possible to register a blueprint from a group's blueprint
listing page:

    >>> user_browser.open("http://blueprints.launchpad.test/~admins")
    >>> print(user_browser.getLink("Register a blueprint"))
    Traceback (most recent call last):
        ...
    zope.testbrowser.browser.LinkNotFoundError
