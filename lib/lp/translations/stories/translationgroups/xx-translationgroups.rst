Translation Groups
==================

Make sure we can actually display the Translation Groups page.

    >>> anon_browser.open("http://translations.launchpad.test/")
    >>> print(anon_browser.url)
    http://translations.launchpad.test/

    >>> anon_browser.getLink("translation groups").click()
    >>> print(anon_browser.url)
    http://translations.launchpad.test/+groups

    >>> print(anon_browser.title)
    Translation groups

Only Rosetta experts and Launchpad administrators can create translation
groups.  Unprivileged users do not have access to the group creation
page.

    >>> anon_browser.open("http://translations.launchpad.test/+groups/+new")
    Traceback (most recent call last):
    ...
    zope.security.interfaces.Unauthorized: ...

Same for a regular, unprivileged user.

    >>> user_browser.open("http://translations.launchpad.test/+groups/+new")
    Traceback (most recent call last):
    ...
    zope.security.interfaces.Unauthorized: ...

OK, best we try again, with administrator rights!

    >>> admin_browser.open("http://translations.launchpad.test/+groups/+new")
    >>> print(
    ...     find_main_content(admin_browser.contents)
    ...     .find("h1")
    ...     .decode_contents()
    ... )
    Create a new translation group

Translation group names must meet certain conditions.  For example, they
may not contain any upper-case letters.

    >>> admin_browser.getControl("Name").value = "PolYglot"
    >>> admin_browser.getControl("Title").value = (
    ...     "The PolyGlot Translation Group"
    ... )
    >>> admin_browser.getControl("Summary").value = (
    ...     "The PolyGlots are a well organised translation group that "
    ...     "handles the work of translating a number of Ubuntu and upstream "
    ...     "projects. It consists of a large number of translation teams, "
    ...     "each specialising in their own language."
    ... )
    >>> admin_browser.getControl("Create").click()
    >>> for message in find_tags_by_class(admin_browser.contents, "message"):
    ...     print(message.decode_contents())
    ...
    There is 1 error.
    Invalid name 'PolYglot'. Names must be at least two characters ...

Neither we can use the name of an already existing group like testing-
translation-team.

    >>> browser.open("http://translations.launchpad.test/+groups")
    >>> print(browser.url)
    http://translations.launchpad.test/+groups

    >>> print(browser.getLink("Just a testing team").url)
    http://translations.launchpad.test/+groups/testing-translation-team

    >>> admin_browser.getControl("Name").value = "testing-translation-team"
    >>> admin_browser.getControl("Create").click()
    >>> print(admin_browser.url)
    http://translations.launchpad.test/+groups/+new

    >>> for message in find_tags_by_class(admin_browser.contents, "message"):
    ...     print(message.decode_contents())
    ...
    There is 1 error.
    There is already a translation group with such name

The same request will be accepted if the group is given a saner name,
such as just "polyglot" (no upper-case letters).

    >>> admin_browser.getControl("Name").value = "polyglot"
    >>> admin_browser.getControl("Translation instructions").value = (
    ...     "https://help.launchpad.net/Translations/PolyglotPolicies"
    ... )
    >>> admin_browser.getControl("Create").click()
    >>> print(admin_browser.url)
    http://translations.launchpad.test/+groups/polyglot

After creating a translation group, the user automatically ends up on
that group's page.

    >>> admin_browser.url
    'http://translations.launchpad.test/+groups/polyglot'

    >>> admin_browser.title
    '...The PolyGlot Translation Group...'

    >>> docs = find_tag_by_id(admin_browser.contents, "documentation")
    >>> print(extract_text(docs))
    Please read the translation instructions...
    >>> docs_url = docs.find("a")
    >>> print(extract_link_from_tag(docs_url))
    https://help.launchpad.net/Translations/PolyglotPolicies

A Rosetta administrator is also allowed to create groups.

    >>> browser.addHeader("Authorization", "Basic jordi@ubuntu.com:test")
    >>> browser.open("http://translations.launchpad.test/+groups/+new")
    >>> browser.getControl("Name").value = "monolingua"
    >>> browser.getControl("Title").value = "Single-language Translators"
    >>> browser.getControl("Summary").value = (
    ...     "Since each of us only speaks one language, we work out software "
    ...     "translations through drawings and hand signals."
    ... )
    >>> browser.getControl("Create").click()
    >>> print(browser.url)
    http://translations.launchpad.test/+groups/monolingua

    >>> browser.title
    '...Single-language Translators...'

By default, when a group is created, the creator is its owner.

    >>> for t in find_tags_by_class(browser.contents, "link"):
    ...     print(t.decode_contents())
    ...
    Jordi Mallach

The Rosetta administrator assigns ownership of the group to Sample
Person.

    >>> browser.getLink(id="link-reassign").click()
    >>> browser.url
    'http://translations.launchpad.test/+groups/monolingua/+reassign'

    >>> browser.getControl(name="field.owner").value = "name12"
    >>> browser.getControl("Change").click()
    >>> browser.url
    'http://translations.launchpad.test/+groups/monolingua'

The Rosetta administrator is still able to administer this group:

    >>> browser.getLink("Appoint a new translation team")
    <...+appoint'>

But Sample Person is now listed as its owner:

    >>> for t in find_tags_by_class(browser.contents, "link"):
    ...     print(t.decode_contents())
    ...
    Sample Person

That means that Sample Person is allowed to administer "their" group.

    >>> browser.addHeader("Authorization", "Basic test@canonical.com:test")
    >>> browser.open(
    ...     "http://translations.launchpad.test/"
    ...     "translations/groups/monolingua/"
    ... )
    >>> browser.getLink("Appoint a new translation team")
    <...+appoint'>

The new groups should show up on the "Translation groups" page.

    >>> anon_browser.open("http://translations.launchpad.test/+groups")
    >>> print(anon_browser.url)
    http://translations.launchpad.test/+groups

    >>> groups_table = find_tag_by_id(
    ...     anon_browser.contents, "translation-groups"
    ... )
    >>> groups = groups_table.find("tbody").find_all("tr")
    >>> for group_row in groups:
    ...     group = group_row.find_next("td")
    ...     print("%s: %s" % (group.a.string, group.a["href"]))
    ...
    Just a testing team: ...testing-translation-team
    Single-language Translators: ...monolingua
    The PolyGlot Translation Group: ...polyglot

When editing translation group details, we could rename the translation
group.

    >>> admin_browser.open("http://translations.launchpad.test/+groups")
    >>> print(admin_browser.url)
    http://translations.launchpad.test/+groups

We can see that the translation group that we are going to duplicate
exists already:

    >>> print(admin_browser.getLink("The PolyGlot Translation Group").url)
    http://translations.launchpad.test/+groups/polyglot

Navigate to the one we are going to rename.

    >>> admin_browser.getLink("Just a testing team").click()
    >>> print(admin_browser.url)
    http://translations.launchpad.test/+groups/testing-translation-team

And select to edit its details.

    >>> admin_browser.getLink("Change details").click()
    >>> print(admin_browser.url)
    http://translations.launchpad.test/+groups/testing-translation-team/+edit

Change the name.

    >>> admin_browser.getControl("Name").value = "polyglot"
    >>> admin_browser.getControl("Change").click()

The system detected that we tried to use an already existing name, so we
didn't move away from this form.

    >>> print(admin_browser.url)
    http://translations.launchpad.test/+groups/testing-translation-team/+edit

    >>> for tag in find_tags_by_class(admin_browser.contents, "message"):
    ...     print(tag.decode_contents())
    ...
    There is 1 error.
    There is already a translation group with this name

Choosing another name should work though.

    >>> admin_browser.getControl("Name").value = "renamed-group"
    >>> admin_browser.getControl("Change").click()
    >>> print(admin_browser.url)
    http://translations.launchpad.test/+groups/renamed-group

    >>> for tag in find_tags_by_class(admin_browser.contents, "message"):
    ...     print(tag.decode_contents())
    ...

You can also edit the generic translation instructions for the team

    >>> admin_browser.getLink("Change details").click()
    >>> admin_browser.getControl("Translation instructions").value = (
    ...     "https://help.launchpad.net/Translations/RenamedGroup"
    ... )
    >>> admin_browser.getControl("Change").click()

Now, let's go have a look at where we can use these translation groups.
We want to check out the distro side first.

Ubuntu is using Launchpad for translations. Ubuntu doesn't have
TranslationGroup and uses open permissions. We can see that from the
translations page.

    >>> anon_browser.open("http://launchpad.test/ubuntu")
    >>> anon_browser.getLink("Translations").click()
    >>> print(anon_browser.title)
    Translations : Ubuntu

    >>> print(
    ...     extract_text(
    ...         find_tag_by_id(
    ...             anon_browser.contents, "translation-permissions"
    ...         )
    ...     )
    ... )
    Ubuntu is translated with Open permissions...

And now make sure we can see the form to change the translation group
and permissions on a project. For that, we are going to use Colin
Watson's account, he's one of the owners of Ubuntu.

    >>> ubuntu_owner_browser = setupBrowser(
    ...     auth="Basic colin.watson@ubuntulinux.com:test"
    ... )
    >>> ubuntu_owner_browser.open(anon_browser.url)
    >>> ubuntu_owner_browser.getLink("Configure translations").click()
    >>> print(ubuntu_owner_browser.title)
    Settings : Translations : Ubuntu

Other users cannot access this page, nor see the menu link to it.

    >>> user_browser.open(anon_browser.url)
    >>> user_browser.getLink("Configure Translations").click()
    Traceback (most recent call last):
    ...
    zope.testbrowser.browser.LinkNotFoundError

    >>> user_browser.open(ubuntu_owner_browser.url)
    Traceback (most recent call last):
    ...
    zope.security.interfaces.Unauthorized: ...

Let's post to the form, setting the translation group to polyglot and
closed permissions.

    >>> ubuntu_owner_browser.getControl(
    ...     "Translation permissions policy"
    ... ).displayValue = ["Closed"]
    >>> print(
    ...     ubuntu_owner_browser.getControl(
    ...         "Translation group"
    ...     ).displayOptions
    ... )
    ['(nothing selected)', 'Single-language Translators',
     'The PolyGlot Translation Group', 'Just a testing team']

    >>> ubuntu_owner_browser.getControl("Translation group").displayValue = [
    ...     "The PolyGlot Translation Group"
    ... ]
    >>> ubuntu_owner_browser.getControl("Change").click()
    >>> print(ubuntu_owner_browser.title)
    Translations : Ubuntu

    >>> print(
    ...     extract_text(
    ...         find_tag_by_id(
    ...             ubuntu_owner_browser.contents, "translation-permissions"
    ...         )
    ...     )
    ... )
    Ubuntu is translated by The PolyGlot Translation Group...

These changes are now reflected in the Ubuntu translations page for
everybody else as well.

    >>> anon_browser.reload()
    >>> print(anon_browser.title)
    Translations : Ubuntu

    >>> print(
    ...     extract_text(
    ...         find_tag_by_id(
    ...             anon_browser.contents, "translation-permissions"
    ...         )
    ...     )
    ... )
    Ubuntu is translated by The PolyGlot Translation Group
    with Closed permissions...

We should also be able to set a translation group and translation
permissions on a product. We'll use the Netapplet product for this test.
First make sure it uses Launchpad for translations.

    >>> netapplet_owner_browser = setupBrowser(
    ...     auth="Basic test@canonical.com:test"
    ... )
    >>> netapplet_owner_browser.open("http://launchpad.test/netapplet")
    >>> netapplet_owner_browser.getLink("Translations", index=1).click()
    >>> print(netapplet_owner_browser.title)
    Configure translations : Translations : NetApplet

    >>> netapplet_owner_browser.getControl("Launchpad").click()
    >>> netapplet_owner_browser.getControl("Change").click()
    >>> print(netapplet_owner_browser.title)
    NetApplet in Launchpad

Netapplet doesn't have TranslationGroup and uses open permissions. We
can see that from the translations page.

    >>> netapplet_owner_browser.open("http://launchpad.test/netapplet")
    >>> netapplet_owner_browser.getLink("Translations").click()
    >>> print(netapplet_owner_browser.title)
    Translations : NetApplet

    >>> print(
    ...     extract_text(
    ...         find_tag_by_id(
    ...             netapplet_owner_browser.contents,
    ...             "translation-permissions",
    ...         )
    ...     )
    ... )
    NetApplet is translated with Open permissions.

Now let's make sure we can see the page to let us change translation
group and permissions.

    >>> translations_page_url = netapplet_owner_browser.url
    >>> netapplet_owner_browser.getLink("Configure Translations").click()
    >>> change_translators_url = netapplet_owner_browser.url

    >>> print(netapplet_owner_browser.title)
    Configure translations : Translations : NetApplet

    >>> print(
    ...     netapplet_owner_browser.getControl(
    ...         "Translation group"
    ...     ).displayOptions
    ... )
    ['(nothing selected)', 'Single-language Translators',
     'The PolyGlot Translation Group', 'Just a testing team']

    >>> print(
    ...     netapplet_owner_browser.getControl(
    ...         "Translation group"
    ...     ).displayValue
    ... )
    ['(nothing selected)']

Ordinary users cannot see the "Configure Translations" link or the page it
leads to.

    >>> user_browser.open(translations_page_url)
    >>> user_browser.getLink("Configure Translations").click()
    Traceback (most recent call last):
    ...
    zope.testbrowser.browser.LinkNotFoundError

    >>> user_browser.open(change_translators_url)
    Traceback (most recent call last):
    ...
    zope.security.interfaces.Unauthorized: ...

Now let's post to the form. We should be redirected to the product page.

    >>> netapplet_owner_browser.getControl(
    ...     "Translation group"
    ... ).displayValue = ["The PolyGlot Translation Group"]
    >>> netapplet_owner_browser.getControl("Change").click()
    >>> print(netapplet_owner_browser.title)
    Translations : NetApplet

Now these changes show up in the product page. (XXX mpt 20070126:
Launchpad should be fixed so that you can't set translation
group/permissions without using Translations.)

Lastly, we should be able to set the translation group on a project.
We'll use the Gnome project as an example. First make sure we can see
the Gnome project page and that it has no translation group assigned.

    >>> gnome_owner_browser = setupBrowser(
    ...     auth="Basic test@canonical.com:test"
    ... )
    >>> gnome_owner_browser.open("http://launchpad.test/gnome")
    >>> gnome_owner_browser.getLink("Translations").click()
    >>> translations_page_url = gnome_owner_browser.url
    >>> print(gnome_owner_browser.title)
    Translations : GNOME

And now make sure we can see the form to change the translation group
and permissions on a project.

    >>> gnome_owner_browser.getLink("Change permissions").click()
    >>> print(gnome_owner_browser.title)
    Permissions and policies...

Other users don't see the "Change translators" link and aren't allowed
to access the page it leads to.

    >>> user_browser.open(translations_page_url)
    >>> user_browser.getLink("Change permissions").click()
    Traceback (most recent call last):
    ...
    zope.testbrowser.browser.LinkNotFoundError

    >>> user_browser.open(gnome_owner_browser.url)
    Traceback (most recent call last):
    ...
    zope.security.interfaces.Unauthorized: ...

Let's post to the form, setting the translation group to polyglot and
closed permissions.

    >>> gnome_owner_browser.getControl(
    ...     "Translation permissions policy"
    ... ).displayValue = ["Closed"]
    >>> print(
    ...     gnome_owner_browser.getControl("Translation group").displayOptions
    ... )
    ['(nothing selected)', 'Single-language Translators',
     'The PolyGlot Translation Group', 'Just a testing team']

    >>> gnome_owner_browser.getControl("Translation group").displayValue = [
    ...     "The PolyGlot Translation Group"
    ... ]
    >>> gnome_owner_browser.getControl("Change").click()

And make sure these changes are now reflected in the Gnome project page
in the relevant portlet.

    >>> gnome_owner_browser.url
    'http://translations.launchpad.test/gnome'
    >>> print(gnome_owner_browser.title)
    Translations : GNOME

We should now see the various distro's, projects and products that the
group has been assigned as the translator for.

    >>> browser.open("http://translations.launchpad.test/+groups/polyglot")
    >>> print(browser.url)
    http://translations.launchpad.test/+groups/polyglot

    >>> def find_projects_portlet(browser):
    ...     """Find the portlet with projects/distros this group works with."""
    ...     return find_tag_by_id(browser.contents, "related-projects")
    ...

    >>> portlet = find_projects_portlet(browser)
    >>> for link in portlet.find_all("a"):
    ...     print("%s: %s" % (link.find(text=True), link["href"]))
    ...
    Ubuntu: http://launchpad.test/ubuntu
    GNOME: http://launchpad.test/gnome
    NetApplet: http://launchpad.test/netapplet

If we disable some of these projects...

    >>> admin_browser.open("http://launchpad.test/gnome/+review")
    >>> admin_browser.getControl("Active").click()
    >>> admin_browser.getControl("Change").click()
    >>> admin_browser.url
    'http://launchpad.test/projectgroups'

    # Unlink the source packages so the project can be deactivated.
    >>> from zope.component import getUtility
    >>> from lp.registry.interfaces.product import IProductSet
    >>> from lp.testing import unlink_source_packages
    >>> login("admin@canonical.com")
    >>> unlink_source_packages(getUtility(IProductSet).getByName("netapplet"))
    >>> logout()
    >>> admin_browser.open("http://launchpad.test/netapplet/+admin")
    >>> admin_browser.getControl("Active").click()
    >>> admin_browser.getControl("Change").click()
    >>> admin_browser.url
    'http://launchpad.test/projects'

They disappear from the listing:

    >>> browser.open("http://translations.launchpad.test/+groups/polyglot")
    >>> print(browser.url)
    http://translations.launchpad.test/+groups/polyglot

    >>> portlet = find_projects_portlet(browser)
    >>> for link in portlet.find_all("a"):
    ...     print("%s: %s" % (link.string, link["href"]))
    ...
    Ubuntu: http://launchpad.test/ubuntu

Let's undo this so we don't get in trouble with other tests in this
story!

    >>> admin_browser.open("http://launchpad.test/gnome/+review")
    >>> admin_browser.getControl("Active").click()
    >>> admin_browser.getControl("Change").click()
    >>> admin_browser.open("http://launchpad.test/netapplet/+admin")
    >>> admin_browser.getControl("Active").click()
    >>> admin_browser.getControl("Change").click()



Appointing translators in a translation group
---------------------------------------------

No translators have been appointed in the polyglot group so far.

A user can have rights to appoint or remove members on any of three
grounds: owning the group, being a Rosetta expert, or being a Launchpad
administrator.

Jordi Mallach is a Rosetta administrator ("expert").  He does not own
polyglot nor is he a Launchpad administrator.  That is enough to allow
him to appoint a translator.

    >>> browser.addHeader("Authorization", "Basic jordi@ubuntu.com:test")
    >>> browser.open("http://translations.launchpad.test/+groups/polyglot/")
    >>> print(find_tag_by_id(browser.contents, "translation-teams-listing"))
    <...
    No translation teams or supervisors have been appointed in this
    group yet.
    ...

Verify that the appointments form displays, and offers the option to
appoint a translator.

    >>> browser.getLink("Appoint a new translation team").click()
    >>> browser.url
    'http://translations.launchpad.test/+groups/polyglot/+appoint'

Appoint a translator. Hoary Gnome Team will translate into Abkhazian.

    >>> browser.getControl("Language").value = ["ab"]
    >>> browser.getControl("Translator").value = "name21"
    >>> browser.getControl("Appoint").click()

We should get redirected back to the group page.

    >>> browser.url
    'http://translations.launchpad.test/+groups/polyglot'

    >>> browser.getLink("Appoint a new translation team").click()
    >>> browser.url
    'http://translations.launchpad.test/+groups/polyglot/+appoint'

And let's appoint No Privileges user for Afrikaans too.

    >>> browser.getControl("Language").value = ["af"]
    >>> browser.getControl("Translator").value = "no-priv"
    >>> browser.getControl("Appoint").click()

Now we should see both of those appointments on the polyglot page:

    >>> find_main_content(browser.contents)
    <...Abkhazian...Hoary Gnome Team...
    ...Afrikaans...No Privileges Person...

    >>> browser.url
    'http://translations.launchpad.test/+groups/polyglot'

Appointing a new Abkhazian translator must fail gracefully, not crash as
it used to do (Bug #52991).

    >>> browser.getLink("Appoint a new translation team").click()
    >>> browser.getControl("Language").value = ["ab"]
    >>> browser.getControl("Translator").value = "name12"
    >>> browser.getControl("Appoint").click()

The error means we stay on the appoint page:

    >>> browser.url
    'http://translations.launchpad.test/+groups/polyglot/+appoint'

    >>> for message in find_tags_by_class(browser.contents, "message"):
    ...     print(message.decode_contents())
    ...
    There is 1 error.
    There is already a translator for this language

Launchpad administrators, are allowed too to manage translation group
membership.

    >>> admin_browser.open(
    ...     "http://translations.launchpad.test/+groups/polyglot/"
    ... )
    >>> admin_browser.getLink("Appoint a new translation team").click()
    >>> admin_browser.url
    'http://translations.launchpad.test/+groups/polyglot/+appoint'

Even to edit details of the translation group.

    >>> admin_browser.open(
    ...     "http://translations.launchpad.test/+groups/polyglot/"
    ... )
    >>> admin_browser.getLink("Change details").click()
    >>> admin_browser.url
    'http://translations.launchpad.test/+groups/polyglot/+edit'

Normal users, however, are not.

    >>> user_browser.open(
    ...     "http://translations.launchpad.test/+groups/polyglot/"
    ... )
    >>> user_browser.url
    'http://translations.launchpad.test/+groups/polyglot/'

    >>> user_browser.getLink("Appoint a new translation team")
    Traceback (most recent call last):
    ...
    zope.testbrowser.browser.LinkNotFoundError

    >>> user_browser.open(
    ...     "http://translations.launchpad.test/+groups/polyglot/"
    ... )
    >>> user_browser.url
    'http://translations.launchpad.test/+groups/polyglot/'

    >>> user_browser.getLink("Change details").click()
    Traceback (most recent call last):
    ...
    zope.testbrowser.browser.LinkNotFoundError


Change a translator in a translation group
------------------------------------------

The system allows us to change the translator for a concrete language

    # Let's see the list of languages we have right now:

    >>> anon_browser.open(
    ...     "http://translations.launchpad.test/+groups/polyglot"
    ... )
    >>> print(anon_browser.url)
    http://translations.launchpad.test/+groups/polyglot

    >>> portlet = find_tag_by_id(
    ...     anon_browser.contents, "translation-teams-listing"
    ... )
    >>> language_rows = portlet.find("tbody").find_all("tr")
    >>> for language_row in language_rows:
    ...     cell = language_row.find_next("td")
    ...     lang_name = extract_text(cell)
    ...     lang_team = extract_text(cell.find_next("td").find_next("a"))
    ...     print("%s: %s" % (lang_name, lang_team))
    ...
    Abkhazian (ab): Hoary Gnome Team
    Afrikaans (af): No Privileges Person

    >>> browser.addHeader("Authorization", "Basic jordi@ubuntu.com:test")
    >>> browser.open("http://translations.launchpad.test/+groups/polyglot/")
    >>> print(browser.url)
    http://translations.launchpad.test/+groups/polyglot/

    # We are going to change the Afrikaans (af) translator.

    >>> browser.getLink(id="edit-af-translator").click()
    >>> print(browser.url)
    http://translations.launchpad.test/+groups/polyglot/af

Let's change the language it translates to Afrikaans, which already
exist.

    # Abkhazian URL exists.

    >>> admin_browser.open(
    ...     "http://translations.launchpad.test/+groups/polyglot/ab"
    ... )
    >>> print(admin_browser.url)
    http://translations.launchpad.test/+groups/polyglot/ab

    # And we change the one we are editing from Afrikaans to Abkhazian

    >>> browser.getControl("Language").value = ["ab"]
    >>> browser.getControl("Change").click()

    # We stay in the same page (+admin is the default view for
    # polyglot/af/).

    >>> print(browser.url)
    http://translations.launchpad.test/+groups/polyglot/af/+admin

the system detects it and notify the user that is not possible.

    >>> for message in find_tags_by_class(browser.contents, "message"):
    ...     print(message.decode_contents())
    ...
    There is 1 error.
    <a href="http://translations.launchpad.test/~name21">Hoary Gnome Team</a>
    is already a translator for this language

However, if the language selected doesn't have yet a translator, for
instance Welsh (cy), the change will work.

    >>> admin_browser.open(
    ...     "http://translations.launchpad.test/+groups/polyglot/cy"
    ... )
    Traceback (most recent call last):
    ...
    zope.publisher.interfaces.NotFound: ...

    >>> browser.getControl("Language").value = ["cy"]
    >>> browser.getControl("Change").click()

    # We are back to the translation group summary page.

    >>> print(browser.url)
    http://translations.launchpad.test/+groups/polyglot

    # And the 'Translation Teams' portlet shows the new information.

    >>> portlet = find_tag_by_id(
    ...     browser.contents, "translation-teams-listing"
    ... )
    >>> language_rows = portlet.find("tbody").find_all("tr")
    >>> for language_row in language_rows:
    ...     cell = language_row.find_next("td")
    ...     lang_name = extract_text(cell)
    ...     lang_team = extract_text(cell.find_next("td").find_next("a"))
    ...     print("%s: %s" % (lang_name, lang_team))
    ...
    Abkhazian (ab): Hoary Gnome Team
    Welsh (cy): No Privileges Person


Let's remove the Hoary Gnome Team, they are not really translators. We
should be redirected to the polyglot page.

    >>> admin_browser.open(
    ...     "http://translations.launchpad.test/+groups/"
    ...     + "polyglot/ab/+remove"
    ... )
    >>> print(admin_browser.url)
    http://translations.launchpad.test/+groups/polyglot/ab/+remove

    >>> admin_browser.getControl("Remove").click()
    >>> print(admin_browser.url)
    http://translations.launchpad.test/+groups/polyglot

And on that page, we should see the removal message.

    >>> for tag in find_tags_by_class(admin_browser.contents, "message"):
    ...     print(tag.decode_contents())
    ...
    Removed Hoary Gnome Team as the Abkhazian translator for The PolyGlot
    Translation Group.


So now No Privileges Person is the Welsh translator for the PolyGlot
translation group, and they are the translation group for Ubuntu, which
uses the Closed translation mode. This means that No Privileges Person
should be able to translate any strings in Ubuntu to Welsh. In other
languages, they will not be able to add or change translations.

Let's see if No Privileges Person can see the translated strings in
Southern Sotho. We expect them to see a readonly form:

    >>> browser.addHeader("Authorization", "Basic no-priv@canonical.com:test")
    >>> browser.open(
    ...     "http://translations.launchpad.test/"
    ...     "ubuntu/hoary/+source/evolution/"
    ...     "+pots/evolution-2.2/st/+translate"
    ... )
    >>> print(browser.url)
    http://.../ubuntu/.../evolution/+pots/evolution-2.2/st/+translate

We are in read only mode, so there shouldn't be any textareas:

    >>> main_content = find_tag_by_id(
    ...     browser.contents, "messages_to_translate"
    ... )
    >>> for textarea in main_content.find_all("textarea"):
    ...     print("Found textarea:\n%s" % textarea)
    ...

Neither any input widget:

    >>> for input in main_content.find_all("input"):
    ...     print("Found input:\n%s" % input)
    ...

However, in Welsh, No Privileges Person does have the ability to edit
directly.

    >>> browser.open(
    ...     "http://translations.launchpad.test/"
    ...     "ubuntu/hoary/+source/evolution/"
    ...     "+pots/evolution-2.2/cy/19/+translate"
    ... )
    >>> print(browser.url)
    http://.../ubuntu/.../evolution/+pots/evolution-2.2/cy/19/+translate

No Privileges is going to do some translation here.  Right now, message
number 148 is not translated.

    >>> tag = find_tag_by_id(browser.contents, "msgset_148_cy_translation_0")
    >>> print(tag.decode_contents())
    (no translation yet)

After No posts a translation, however, it is.

    >>> browser.getControl(
    ...     name="msgset_148_cy_translation_0_radiobutton"
    ... ).value = ["msgset_148_cy_translation_0_new"]
    >>> browser.getControl(name="msgset_148_cy_translation_0_new").value = (
    ...     "foo\n%i%i%i\n"
    ... )
    >>> browser.getControl("Save & Continue").click()
    >>> print(browser.url)
    http://.../ubuntu/.../evolution/+pots/evolution-2.2/cy/20/+translate

And finally, let's take a look again, and we should have a translation
added (with some extra html code, but the same content we wanted to add)

    >>> browser.getLink("Previous").click()
    >>> print(browser.url)
    http://.../ubuntu/.../evolution/+pots/evolution-2.2/cy/19/+translate

    >>> tag = find_tag_by_id(browser.contents, "msgset_148_cy_translation_0")
    >>> print(tag.decode_contents())
    foo<img alt="" src="/@@/translation-newline"/><br/>
    %i%i%i


Now No Privileges Person is still the Welsh translator for the PolyGlot
translation group, and they are the translation group for Ubuntu, which
we are going to set as having Restricted translations. This means that
No Privileges Person should be able to translate any strings in Ubuntu
to Welsh. In other languages, No Privileges Person should be warned that
they are not a designated translator.

    >>> browser.addHeader("Authorization", "Basic no-priv@canonical.com:test")

    >>> admin_browser.open(
    ...     "http://translations.launchpad.test/ubuntu/"
    ...     "+configure-translations"
    ... )

    >>> admin_browser.getControl("Translation permissions policy").value = [
    ...     "RESTRICTED"
    ... ]
    >>> admin_browser.getControl("Change").click()
    >>> print(admin_browser.url)
    http://translations.launchpad.test/ubuntu

    >>> print(
    ...     extract_text(
    ...         find_tag_by_id(
    ...             admin_browser.contents, "translation-permissions"
    ...         )
    ...     )
    ... )
    Ubuntu is translated by ... with Restricted permissions...

The translation group does not assign anyone to tend to the Southern
Sotho translation, so for that language, No Privileges can't even make
suggestions.

    >>> def find_translation_input_label(contents):
    ...     """Find first "New suggestion:" or "New translation:" label."""
    ...     labels = find_tags_by_class(contents, "translation-input-label")
    ...     if not labels:
    ...         return None
    ...     else:
    ...         return labels[0].decode_contents()
    ...

    >>> def get_detail_tag(browser, tag_class):
    ...     """Find tag of given class in translation page."""
    ...     tag = find_tag_by_id(browser.contents, tag_class)
    ...     if not tag:
    ...         return None
    ...     else:
    ...         return tag.decode_contents()
    ...

    >>> def print_menu_option(contents, option):
    ...     """Print given navigation menu on given page, if present."""
    ...     found = False
    ...     for item in find_tags_by_class(contents, "menu-link-%s" % option):
    ...         print(item.decode_contents())
    ...         found = True
    ...     if not found:
    ...         print("Not found.")
    ...

    >>> browser.open(
    ...     "http://translations.launchpad.test/"
    ...     "ubuntu/hoary/+source/evolution/"
    ...     "+pots/evolution-2.2/"
    ... )

    >>> print_menu_option(browser.contents, "edit")
    Not found.

    >>> print_menu_option(browser.contents, "upload")
    Not found.

    >>> browser.open(
    ...     "http://translations.launchpad.test/"
    ...     "ubuntu/hoary/+source/evolution/"
    ...     "+pots/evolution-2.2/st/+translate"
    ... )

    >>> print(find_translation_input_label(browser.contents))
    None

    >>> managers = get_detail_tag(browser, "translation-managers")
    >>> print(managers)
    This translation is managed by <...> translation group
    <...>polyglot<...>.

    >>> print(get_detail_tag(browser, "translation-access"))
    There is nobody to manage translation into this particular language.  If
    you are interested in working on it, please contact the translation group.

    >>> print_menu_option(browser.contents, "upload")
    Not found.

The Polyglot translation group now assigns a Southern Sotho translation
team, of which No Privileges however is not a member.

    >>> admin_browser.open(
    ...     "http://translations.launchpad.test/+groups/polyglot/+appoint"
    ... )
    >>> admin_browser.getControl("Language").value = ["st"]
    >>> admin_browser.getControl("Translator").value = "name21"
    >>> admin_browser.getControl("Appoint").click()

No Privileges Person can now enter text, but the page does warn that it
will only accept suggestions.

    >>> browser.open(
    ...     "http://translations.launchpad.test/"
    ...     "ubuntu/hoary/+source/evolution/"
    ...     "+pots/evolution-2.2/st/+translate"
    ... )

    >>> print(find_translation_input_label(browser.contents))
    New suggestion:

    >>> managers = get_detail_tag(browser, "translation-managers")
    >>> print(managers)
    This translation is managed by <...>...Hoary Gnome Team<...>, assigned
    by <...>The PolyGlot Translation Group<...>.

The ability to upload files is restricted to those with full edit
privileges.

    >>> print_menu_option(browser.contents, "upload")
    Not found.

The translation-managers detail may use ", and" to separate items, but
since there is only one item in this case, we don't see that.

    >>> import re
    >>> print(re.search(r"\band\b", managers))
    None

    >>> print(get_detail_tag(browser, "translation-access"))
    Your suggestions will be held for review...

In Welsh, No Privileges Person does have the ability to edit directly,
as well as to upload files.

    >>> def find_no_translation_marker(contents):
    ...     """Find first "no translation yet" marker in contents."""
    ...     markers = find_tags_by_class(contents, "no-translation")
    ...     if not markers:
    ...         return None
    ...     else:
    ...         return markers[0].decode_contents()
    ...

    >>> browser.open(
    ...     "http://translations.launchpad.test/"
    ...     "ubuntu/hoary/+source/evolution/"
    ...     "+pots/evolution-2.2/cy/+translate"
    ... )

    >>> print_menu_option(browser.contents, "upload")
    Upload translation

No Privileges person is going to translate here.  Message number 137 is
not yet translated.

    >>> browser.open(
    ...     "http://translations.launchpad.test/"
    ...     "ubuntu/hoary/+source/evolution/"
    ...     "+pots/evolution-2.2/cy/8/+translate"
    ... )

    >>> print(get_detail_tag(browser, "translation-managers"))
    This translation is managed by <...No Privileges Person<...>, assigned by
    <...>The PolyGlot Translation Group<...>.

    >>> print(get_detail_tag(browser, "translation-access"))
    You have full access to this translation.

    >>> print(find_no_translation_marker(browser.contents))
    (no translation yet)

Now, we need to show that it is translated after a post. Let's go ahead and
POST and see that all goes well:

    >>> browser.getControl(
    ...     name="msgset_137_cy_translation_0_radiobutton"
    ... ).value = ["msgset_137_cy_translation_0_new"]
    >>> msg_137 = browser.getControl(name="msgset_137_cy_translation_0_new")
    >>> msg_137.value = "evolution minikaart"

    >>> browser.getControl(name="submit_translations").click()
    >>> print(browser.url)
    http://.../ubuntu/.../+pots/evolution-2.2/cy/9/+translate

And finally, let's take a look again, and we see that the translation
has been added.

    >>> browser.getLink("Previous").click()
    >>> print(find_no_translation_marker(browser.contents))
    None

    >>> print(find_main_content(browser.contents).decode_contents())
    <...evolution minikaart...

First, we verify that netapplet is using Launchpad Translations.

    >>> admin_browser.open("http://launchpad.test/netapplet")
    >>> admin_browser.getLink("Translations", index=1).click()
    >>> print_radio_button_field(admin_browser.contents, "translations_usage")
    ( ) Unknown
    (*) Launchpad
    ( ) External
    ( ) Not Applicable
    >>> admin_browser.getLink("Cancel").click()
    >>> print(admin_browser.title)
    NetApplet in Launchpad

We set the 'Structured' permission and select the 'Just a testing team'
as the translation group for the netapplet product...

    >>> admin_browser.getLink("Translations").click()
    >>> admin_browser.getLink("Configure Translations").click()
    >>> admin_browser.getControl("Translation group").displayOptions
    ['(nothing selected)', 'Single-language Translators',
     'The PolyGlot Translation Group', 'Just a testing team']

    >>> admin_browser.getControl("Translation group").displayValue = [
    ...     "Just a testing team"
    ... ]
    >>> admin_browser.getControl(
    ...     "Translation permissions policy"
    ... ).displayValue = ["Structured"]
    >>> admin_browser.getControl("Change").click()
    >>> print(admin_browser.title)
    Translations : NetApplet

... and its associated project, GNOME.

    >>> admin_browser.open(
    ...     "http://translations.launchpad.test/gnome/+settings"
    ... )
    >>> admin_browser.getControl("Translation group").displayValue = [
    ...     "Just a testing team"
    ... ]
    >>> admin_browser.getControl(
    ...     "Translation permissions policy"
    ... ).displayValue = ["Structured"]
    >>> admin_browser.getControl("Change").click()
    >>> admin_browser.url
    'http://translations.launchpad.test/gnome'

Now, we test that a member of a translation team is able to translate
directly, in this example, we are using 'tsukimi' account.

    >>> tsukimi_browser = setupBrowser(auth="Basic tsukimi@quaqua.net:test")
    >>> tsukimi_browser.open(
    ...     "http://translations.launchpad.test/netapplet/trunk/+pots/"
    ...     + "netapplet/es/+translate"
    ... )
    >>> content = find_main_content(tsukimi_browser.contents)
    >>> print(content)
    <...
    ...Translating into Spanish...
    ...Dial-up connection...

Next test is with a non member of that translation team, the 'No
Privileges' account. We check that we get the warning that we are not
members of the team.

    >>> no_priv_browser = setupBrowser(
    ...     auth="Basic no-priv@canonical.com:test"
    ... )
    >>> no_priv_browser.open(
    ...     "http://translations.launchpad.test/netapplet/trunk/+pots/"
    ...     + "netapplet/es/+translate"
    ... )
    >>> content = find_main_content(no_priv_browser.contents)
    >>> print(content)
    <...
    ...Translating into Spanish...
    ...Your suggestions will be held for review...

And finally, we test that a language without a team lets anyone (in this
case, the 'No Privileges' account) to translate directly.

    >>> no_priv_browser.open(
    ...     "http://translations.launchpad.test/netapplet/trunk/+pots/"
    ...     + "netapplet/fr/+translate"
    ... )
    >>> content = find_main_content(no_priv_browser.contents)
    >>> print(content)
    <...
    ...Translating into French...

First, make sure we can see the page.

Try to get the page when unauthenticated.

    >>> browser.open(
    ...     "http://translations.launchpad.test/ubuntu/hoary/+source/"
    ...     + "evolution/+pots/evolution-2.2/af/+upload"
    ... )
    Traceback (most recent call last):
    ...
    zope.security.interfaces.Unauthorized: ...

And now with valid credentials.

    >>> admin_browser.open(
    ...     "http://translations.launchpad.test/ubuntu/hoary/+source/"
    ...     + "evolution/+pots/evolution-2.2/af/+upload"
    ... )
    >>> print(admin_browser.url)
    http://.../ubuntu/hoary/+source/evolution/+pots/evolution-2.2/af/+upload

Now hit the upload button, but without giving a file for upload. We get
an error message back.

    >>> admin_browser.getControl("Upload").click()
    >>> print(admin_browser.url)
    http://.../ubuntu/hoary/+source/evolution/+pots/evolution-2.2/af/+upload

    >>> for tag in find_tags_by_class(admin_browser.contents, "error"):
    ...     print(tag.decode_contents())
    ...
    Ignored your upload because you didn't select a file to upload.

Uploading files with an unknown file format notifies the user that it
cannot be handled.

    >>> from io import BytesIO
    >>> af_file = '''
    ... # Afrikaans translation for Silky
    ... # Copyright (C) 2004 Free Software Foundation, Inc.
    ... # This file is distributed under the same license as the silky package.
    ... # Hanlie Pretorius <hpretorius@pnp.co.za>, 2004.
    ... #
    ... msgid ""
    ... msgstr ""
    ... "Project-Id-Version: hello-ycp-0.13.1\n"
    ... "Report-Msgid-Bugs-To: bug-gnu-gettext@gnu.org\n"
    ... "PO-Revision-Date: 2003-12-31 10:30+2\n"
    ... "Last-Translator: Ysbeer <ysbeer@af.org.za>\n"
    ... "Language-Team: Afrikaans <i18n@af.org.za>\n"
    ... "MIME-Version: 1.0\n"
    ... "Content-Type: text/plain; charset=UTF-8\n"
    ... "Content-Transfer-Encoding: 8bit\n"
    ...
    ... #: hello.ycp:16
    ... msgid "Hello, world!"
    ... msgstr "Hallo wêreld!"
    ...
    ... #: hello.ycp:20
    ... #, ycp-format
    ... msgid "This program is running as process number %1."
    ... msgstr "Hierdie program loop as prosesnommer %1."'''.encode(
    ...     "UTF-8"
    ... )
    ... # noqa

    >>> upload = admin_browser.getControl(name="file")
    >>> upload.add_file(BytesIO(af_file), "application/msword", "af.doc")
    >>> admin_browser.getControl("Upload").click()
    >>> print(admin_browser.url)  # noqa
    http://translations.launchpad.test/ubuntu/hoary/+source/evolution/+pots/evolution-2.2/af/+upload

    >>> for tag in find_tags_by_class(admin_browser.contents, "error"):
    ...     print(tag.decode_contents())
    ...
    Ignored your upload because the file you uploaded was not recognised as
    a file that can be imported.

With all the correct information, a file can be uploaded.

    >>> upload = admin_browser.getControl(name="file")
    >>> upload.add_file(BytesIO(af_file), "application/x-po", "af.po")
    >>> admin_browser.getControl("Upload").click()
    >>> print(admin_browser.url)  # noqa
    http://translations.launchpad.test/ubuntu/hoary/+source/evolution/+pots/evolution-2.2/af/+upload

    >>> for tag in find_tags_by_class(admin_browser.contents, "message"):
    ...     print(tag.decode_contents())
    ...
    Thank you for your upload.  It will be automatically reviewed...


We are going to test the system by which rosetta provides alternative
translation suggestions. This will need to be updated when we change the
presentation of these items.

This test is going to work with evolution source package for Ubuntu
Hoary.  As part of this history, we have Hoary distro release with
RESTRICTED permissions and with the Polyglot translation team in charge
of its translations.

Polyglot has someone assigned for Spanish translations, and though No
Privileges is not that person, this does make it possible to enter
suggestions in Spanish.

    >>> from zope.component import getUtility
    >>> from lp.testing import login, logout
    >>> from lp.registry.interfaces.distribution import IDistributionSet
    >>> from lp.registry.interfaces.person import IPersonSet
    >>> from lp.services.worlddata.interfaces.language import ILanguageSet
    >>> from lp.translations.interfaces.potemplate import IPOTemplateSet
    >>> from lp.translations.interfaces.translator import ITranslatorSet

    >>> login("foo.bar@canonical.com")
    >>> ubuntu = getUtility(IDistributionSet).getByName("ubuntu")
    >>> spanish = getUtility(ILanguageSet)["es"]
    >>> carlos = getUtility(IPersonSet).getByName("carlos")
    >>> ubuntu_spanish_reviewer = getUtility(ITranslatorSet).new(
    ...     translationgroup=ubuntu.translationgroup,
    ...     language=spanish,
    ...     translator=carlos,
    ... )

    >>> utility = getUtility(IPOTemplateSet)
    >>> _ = utility.populateSuggestivePOTemplatesCache()

    >>> logout()

Let's add a new suggestion as a person without privileges.

    >>> browser.addHeader("Authorization", "Basic no-priv@canonical.com:test")
    >>> browser.open(
    ...     "http://translations.launchpad.test/"
    ...     "ubuntu/hoary/+source/evolution/"
    ...     "+pots/evolution-2.2/es/+translate"
    ... )
    >>> browser.getControl(
    ...     name="msgset_134_es_translation_0_new_checkbox"
    ... ).value = True
    >>> browser.getControl(name="msgset_134_es_translation_0_new").value = (
    ...     "new suggestion"
    ... )
    >>> browser.getControl(name="submit_translations").click()
    >>> print(browser.url)
    http://.../ubuntu/.../evolution/+pots/evolution-2.2/es/+translate?...

    >>> browser.getLink("Previous").click()

Now, we can see the added suggestion + others from the sample data.

    >>> for suggestion in find_main_content(browser.contents).find_all(
    ...     True, {"id": re.compile("msgset_134_es_suggestion_.*")}
    ... ):
    ...     print(suggestion)
    <...<samp> </samp>new suggestion...
    <...
    ...Suggested by...No Privileges Person...
    <...<samp> </samp>Srprise! (non-editor)...
    <...
    ...Suggested by...Valentina Commissari...2005-06-06...
    <...<samp> </samp>bang bang in evo hoary...
    <...
    ...Suggested in...evolution-2.2 in Evolution trunk...
    ...Mark Shuttleworth</a>...2005-06-06...

And there's also a separate translation coming from upstream:

    >>> print(find_tag_by_id(browser.contents, "msgset_134_other"))
    <...<samp> </samp>tarjetas...

    >>> print(find_tag_by_id(browser.contents, "msgset_134_other_origin"))
    <...
    ...Suggested by...Carlos Perelló Marín...2005-05-06...
