Personal Package Archive pages and work-flow
============================================

Activating Personal Package Archives for Users
----------------------------------------------

Personal Package Archives have to be activated before they can be
accessed, in this section we will cover the activation procedure for
an user-PPA by its own user.

A section named 'Personal Package Archives' is presented in the
user/team page.

    >>> anon_browser.open("http://launchpad.test/~cprov")

    >>> print_tag_with_id(anon_browser.contents, "ppas")
    Personal package archives
    PPA for Celso Providelo

There is a link in the body page pointing to Celso's PPA.

    >>> anon_browser.getLink("PPA for Celso Providelo").click()

    >>> print(anon_browser.title)
    PPA for Celso Providelo : Celso Providelo

On the other hand, Sample Person hasn't activated their PPA yet, so they
can quickly activate one via the link in their PPA section.

    >>> sample_browser = setupBrowser(auth="Basic test@canonical.com:test")
    >>> sample_browser.open("http://launchpad.test/~name12")

    >>> print_tag_with_id(sample_browser.contents, "ppas")
    Personal package archives
    Create a new PPA

    >>> sample_browser.getLink("Create a new PPA").click()

    >>> print(sample_browser.title)
    Activate PPA : Sample Person

This page presents a pointer to the current PPA-ToS (terms of service)
with mandatory 'displayname' and checkbox ('accepted') fields. The
former should be a free-form text that will be used as a reference to
the PPA in Launchpad UI and the later indicating that the user has
read and accepted the conditions. The is also an optional 'description'
text-area.

There is also a message, near the form actions, in which the user is
warned about the fact that if the user has any PPAs with published
packages then they will not be able to rename their account.

    >>> print(
    ...     extract_text(
    ...         first_tag_by_class(sample_browser.contents, "actions")
    ...     )
    ... )
    A PPA's URL cannot be changed once it has had packages
    published. You will not be able to rename Sample Person (name12)
    until all such PPAs are deleted.
    ...

'PPA name' and 'Displayname' are required fields.  For the first activated
PPA, the name is pre-filled with a suggestion of "ppa":

    >>> print(sample_browser.getControl(name="field.name").value)
    ppa

    >>> sample_browser.getControl("Activate").click()

    >>> print_feedback_messages(sample_browser.contents)
    There is 1 error.
    Required input is missing.

By submitting the form without acknowledging the PPA-ToS results in a
error with a specific message.

    >>> sample_browser.getControl(name="field.name").value = "sampleppa"
    >>> sample_browser.getControl(name="field.displayname").value = (
    ...     "Sample PPA"
    ... )
    >>> sample_browser.getControl("Activate").click()

    >>> print_feedback_messages(sample_browser.contents)
    There is 1 error.
    PPA Terms of Service must be accepted to activate a PPA.

In order to 'activate' a PPA the user must acknowledge the PPA-ToS.

    >>> sample_browser.getControl(name="field.accepted").value = True
    >>> sample_browser.getControl(name="field.description").value = (
    ...     "Hoohay for PPA."
    ... )
    >>> sample_browser.getControl("Activate").click()

A successful activation redirects to the PPA page

    >>> print(sample_browser.title)
    Sample PPA : Sample Person

Where Sample person user can see the description previously entered.

    >>> print(
    ...     extract_text(
    ...         find_tag_by_id(sample_browser.contents, "edit-description")
    ...     )
    ... )
    Edit PPA description
    Hoohay for PPA.

The PPA owner is able to edit PPA 'displayname' and 'description'.

    >>> sample_browser.getLink("Change details").click()

    >>> sample_browser.getControl(name="field.displayname").value = (
    ...     "Sample testing PPA"
    ... )
    >>> sample_browser.getControl(name="field.description").value = (
    ...     "Howdy, cowboys !"
    ... )

    >>> sample_browser.getControl("Save").click()

After confirming the changes Sample Person is sent to the PPA page
where they can see the updated information.

    >>> print(sample_browser.title)
    Sample testing PPA : Sample Person

    >>> print(
    ...     extract_text(
    ...         find_tag_by_id(sample_browser.contents, "edit-description")
    ...     )
    ... )
    Edit PPA description
    Howdy, cowboys !

Empty 'description' fields are not rendered.

    >>> sample_browser.getLink("Change details").click()
    >>> sample_browser.getControl(name="field.description").value = ""
    >>> sample_browser.getControl("Save").click()

    >>> print(sample_browser.title)
    Sample testing PPA : Sample Person

    >>> print(find_tag_by_id(sample_browser.contents, "description"))
    None

On the other hand, the PPA 'displayname' field is required. Sample
user can't have an empty displayname on their PPA.

    >>> sample_browser.getLink("Change details").click()
    >>> sample_browser.getControl(name="field.displayname").value = ""
    >>> sample_browser.getControl("Save").click()

    >>> print(sample_browser.title)
    Change details : Sample testing PPA...

    >>> print_feedback_messages(sample_browser.contents)
    There is 1 error.
    Required input is missing.


Activating Personal Package Archives for Teams
----------------------------------------------

Similarly to the user PPAs activation, team PPAs can be activated by
anyone with 'launchpad.Edit' permission in the team in question:
/
    >>> cprov_browser = setupBrowser(
    ...     auth="Basic celso.providelo@canonical.com:test"
    ... )
    >>> cprov_browser.open("http://launchpad.test/~landscape-developers")

    >>> print(find_tag_by_id(cprov_browser.contents, "ppas"))
    None

Even if we try the URL directly:

    >>> cprov_browser.open(
    ...     "http://launchpad.test/~landscape-developers/+activate-ppa"
    ... )
    Traceback (most recent call last):
    ...
    zope.security.interfaces.Unauthorized: (..., 'launchpad.Edit')

Let's proceed with the required permissions:

    >>> sample_browser.open("http://launchpad.test/~landscape-developers")

    >>> print_tag_with_id(sample_browser.contents, "ppas")
    Personal package archives
    Create a new PPA

    >>> sample_browser.getLink("Create a new PPA").click()

    >>> print(sample_browser.title)
    Activate PPA : ...

    >>> sample_browser.getControl(name="field.name").value = "develppa"
    >>> sample_browser.getControl(name="field.displayname").value = (
    ...     "Devel PPA"
    ... )
    >>> sample_browser.getControl(name="field.accepted").value = True
    >>> sample_browser.getControl(name="field.description").value = (
    ...     "Hoohay for Team PPA."
    ... )

The user is, again, warned about the fact that activating this PPA
will block renaming of the context team.

    >>> print(
    ...     extract_text(
    ...         first_tag_by_class(sample_browser.contents, "actions")
    ...     )
    ... )
    A PPA's URL cannot be changed once it has had packages
    published. You will not be able to rename Landscape Developers
    (landscape-developers) until all such PPAs are deleted.
    ...

That understood, the PPA gets activated.

    >>> sample_browser.getControl("Activate").click()

    >>> print(sample_browser.title)
    Devel PPA : “Landscape Developers” team

    >>> print(
    ...     extract_text(
    ...         find_tag_by_id(sample_browser.contents, "edit-description")
    ...     )
    ... )
    Edit PPA description
    Hoohay for Team PPA.

Any team administrator can edit the description contents,
exactly the same as for a user-PPA, see above:

    >>> sample_browser.getLink("Change details").click()

    >>> sample_browser.title
    'Change details : Devel PPA...

    >>> sample_browser.getControl(name="field.description").value = (
    ...     "Yay, I can change it."
    ... )
    >>> sample_browser.getControl("Save").click()

    >>> print(sample_browser.title)
    Devel PPA : “Landscape Developers” team

    >>> print(
    ...     extract_text(
    ...         find_tag_by_id(sample_browser.contents, "edit-description")
    ...     )
    ... )
    Edit PPA description
    Yay, I can change it.

Cancelling the 'Edit' form will redirect the user to the PPA overview
page and discard the changes.

    >>> sample_browser.getLink("Change details").click()
    >>> sample_browser.getControl(name="field.description").value = (
    ...     "Discarded ..."
    ... )
    >>> sample_browser.getLink("Cancel").click()

    >>> print(sample_browser.title)
    Devel PPA : “Landscape Developers” team

    >>> print(
    ...     extract_text(
    ...         find_tag_by_id(sample_browser.contents, "edit-description")
    ...     )
    ... )
    Edit PPA description
    Yay, I can change it.

Create a publication in the team's PPA.

    >>> from zope.component import getUtility
    >>> from lp.registry.interfaces.person import IPersonSet
    >>> from lp.registry.interfaces.distribution import IDistributionSet
    >>> login("admin@canonical.com")
    >>> devs = getUtility(IPersonSet).getByName("landscape-developers")
    >>> ubuntu = getUtility(IDistributionSet).getByName("ubuntu")
    >>> archive = devs.getPPAByName(ubuntu, "develppa")
    >>> ignore = factory.makeSourcePackagePublishingHistory(archive=archive)
    >>> logout()

Similarly to users, teams with active PPAs cannot be renamed either.

    >>> sample_browser.open(
    ...     "http://launchpad.test/~landscape-developers/+edit"
    ... )
    >>> sample_browser.getControl(name="field.name").value = "duderinos"
    Traceback (most recent call last):
    ...
    LookupError: name ...'field.name'
    ...

    >>> print(
    ...     extract_text(first_tag_by_class(sample_browser.contents, "form"))
    ... )
    Name: landscape-developers
    This team has an active PPA with packages published and may not be
    renamed.
    ...


Activating someone else's Personal Package Archives
---------------------------------------------------

We also allow LP-admins to create Personal Package Archives in the
name of other users or teams:

    >>> admin_browser.open("http://launchpad.test/~jblack")
    >>> print_tag_with_id(admin_browser.contents, "ppas")
    Personal package archives
    Create a new PPA

    >>> admin_browser.getLink("Create a new PPA").click()
    >>> admin_browser.getControl(name="field.name").value = "ppa"
    >>> admin_browser.getControl(name="field.displayname").value = "Hack PPA"
    >>> admin_browser.getControl(name="field.accepted").value = True
    >>> admin_browser.getControl(name="field.description").value = (
    ...     "Go for it, you lazy !"
    ... )
    >>> admin_browser.getControl("Activate").click()

    >>> print(admin_browser.title)
    Hack PPA : James Blackwell

    >>> print(
    ...     extract_text(
    ...         find_tag_by_id(admin_browser.contents, "edit-description")
    ...     )
    ... )
    Edit PPA description
    Go for it, you lazy !

LP-admins can also 'edit' PPAs of other people:

    >>> admin_browser.getLink("Change details") is not None
    True

But more importantly, administering Personal Package Archives is restricted
to LP administrators, LP commercial administrators, and LP PPA
administrators, as they need to be able to make PPAs private, change their
virtualisation settings, and so on.

    >>> sample_browser.open("http://launchpad.test/~jblack/+archive")
    >>> print(sample_browser.getLink("Administer archive"))
    Traceback (most recent call last):
    ...
    zope.testbrowser.browser.LinkNotFoundError

    >>> admin_browser.open("http://launchpad.test/~jblack/+archive")
    >>> admin_browser.getLink("Administer archive").click()
    >>> print(admin_browser.title)
    Administer : Hack PPA...

    >>> commercial_browser = setupBrowser(
    ...     auth="Basic commercial-member@canonical.com:test"
    ... )
    >>> commercial_browser.open("http://launchpad.test/~jblack/+archive")
    >>> commercial_browser.getLink("Administer archive") is not None
    True

    >>> login("admin@canonical.com")
    >>> ppa_admin = getUtility(IPersonSet).getByName("launchpad-ppa-admins")
    >>> ppa_admin_member = factory.makePerson(
    ...     email="ppa-member@canonical.com", member_of=[ppa_admin]
    ... )
    >>> logout()
    >>> ppa_admin_browser = setupBrowser(
    ...     auth="Basic ppa-member@canonical.com:test"
    ... )
    >>> ppa_admin_browser.open("http://launchpad.test/~jblack/+archive")
    >>> ppa_admin_browser.getLink("Administer archive") is not None
    True


Trying to shortcut the URL as a non-privileged user does not work:

    >>> sample_browser.open(
    ...     "http://launchpad.test/~jblack/+archive/ppa/+admin"
    ... )
    Traceback (most recent call last):
    ...
    zope.security.interfaces.Unauthorized: ...

The administration procedure allows administrators to:

 * Enable/Disable: disabled PPA that won't accept uploads (not
   implemented yet)
 * Make the PPA private or public.
 * For private PPAs, set the buildd secret.
 * Set whether the archive should be built on a virtualized machine.
 * Set a maximum disk size: uploads will be rejected if the resulting
   PPA size is exceeding the authorized size.
 * Set a per-archive build score delta.
 * Set external archive dependencies

In this case, the administrator may wish to amend the PPA so that it is
set up like the ubuntu security PPA, which is private but does not
build on a virtualized builder.

    >>> admin_browser.getControl(name="field.enabled").value
    True
    >>> bool(admin_browser.getControl(name="field.private").value)
    False
    >>> bool(
    ...     admin_browser.getControl(
    ...         name="field.suppress_subscription_notifications"
    ...     ).value
    ... )
    False
    >>> admin_browser.getControl(name="field.require_virtualized").value
    True
    >>> admin_browser.getControl(name="field.relative_build_score").value
    '0'
    >>> admin_browser.getControl(name="field.external_dependencies").value
    ''

    >>> admin_browser.getControl(name="field.enabled").value = False
    >>> admin_browser.getControl(name="field.private").value = True
    >>> admin_browser.getControl(
    ...     name="field.suppress_subscription_notifications"
    ... ).value = True
    >>> admin_browser.getControl(name="field.require_virtualized").value = (
    ...     True
    ... )
    >>> admin_browser.getControl(name="field.authorized_size").value = "1"
    >>> admin_browser.getControl(name="field.relative_build_score").value = (
    ...     "199"
    ... )
    >>> admin_browser.getControl(name="field.external_dependencies").value = (
    ...     "deb http://my.spethial.repo.com/ %(series)s main"
    ... )
    >>> admin_browser.getControl("Save").click()

Once confirmed the administrator is sent to the PPA page where they can
see some of the updated information.

    >>> print(admin_browser.title)
    Hack PPA : James Blackwell

    >>> print_feedback_messages(admin_browser.contents)
    This PPA has been disabled.

We need go back to the "Administer archive" page to see the build score and
external dependencies changes that were made:

    >>> admin_browser.getLink("Administer archive").click()
    >>> admin_browser.getControl(name="field.relative_build_score").value
    '199'
    >>> admin_browser.getControl(name="field.external_dependencies").value
    'deb http://my.spethial.repo.com/ %(series)s main'

The external dependencies field is validated to make sure it looks like
a sources.list entry.  If the field fails validation an error is displayed.

    >>> admin_browser.getControl(name="field.external_dependencies").value = (
    ...     "deb not_a_url"
    ... )
    >>> admin_browser.getControl("Save").click()
    >>> print_feedback_messages(admin_browser.contents)
    There is 1 error.
    'deb not_a_url' is not a complete and valid sources.list entry


There is a maximum value allowed for `IArchive.authorized_size`, it is
currently 2147483647 and the unit used in code is MiB, so in practice
the size limit is 2 PiB.

    >>> limit = 2**31 - 1

    >>> admin_browser.open(
    ...     "http://launchpad.test/~jblack/+archive/ppa/+admin"
    ... )
    >>> admin_browser.getControl(name="field.authorized_size").value = str(
    ...     limit
    ... )
    >>> admin_browser.getControl("Save").click()

    >>> admin_browser.getLink("Administer archive").click()
    >>> print(admin_browser.getControl(name="field.authorized_size").value)
    2147483647

Submitting the form with an authorized_size value that is too large
will result in an error:

    >>> admin_browser.getControl(name="field.authorized_size").value = str(
    ...     limit + 1
    ... )
    >>> admin_browser.getControl("Save").click()

    >>> print_feedback_messages(admin_browser.contents)
    There is 1 error.
    Value is too big

Cancelled changes in the administration form redirects the user to the
PPA overview page and discards the changes.

    >>> admin_browser.getLink("Cancel").click()

    >>> print(admin_browser.title)
    Hack PPA : James Blackwell

    >>> admin_browser.getLink("Administer archive").click()
    >>> admin_browser.getLink("Cancel").click()

    >>> print(admin_browser.title)
    Hack PPA : James Blackwell


Double submission
-----------------

If two browser windows are open at the same time on the activation page
then when the second activation is clicked after already
activating on the first, then it will just go to the archive page.

Set up two browsers (waiting for bug #68655):

    >>> browser1 = setupBrowser(auth="Basic foo.bar@canonical.com:test")
    >>> browser1.open("http://launchpad.test/~name16/+activate-ppa")

    >>> browser2 = setupBrowser(auth="Basic foo.bar@canonical.com:test")
    >>> browser2.open("http://launchpad.test/~name16/+activate-ppa")

Prepare the forms in both browsers to activate the default PPA for the
user 'Foo Bar'.

    >>> browser1.getControl(name="field.name").value = "boomppa"
    >>> browser1.getControl(name="field.displayname").value = "Boom PPA"
    >>> browser1.getControl(name="field.accepted").value = True
    >>> browser1.getControl(name="field.description").value = "PPA rocks!"

    >>> browser2.getControl(name="field.name").value = "boomppa"
    >>> browser2.getControl(name="field.displayname").value = "Boom PPA"
    >>> browser2.getControl(name="field.accepted").value = True
    >>> browser2.getControl(name="field.description").value = (
    ...     "PPA does not explode!"
    ... )

Activate the PPA in the first browser:

    >>> browser1.getControl("Activate").click()

    >>> print(browser1.title)
    Boom PPA : Foo Bar

    >>> print(
    ...     extract_text(
    ...         find_tag_by_id(browser1.contents, "edit-description")
    ...     )
    ... )
    Edit PPA description
    PPA rocks!

Activating the default PPA in the second browser results in an error
and the rendered form contains the 'name' field.

    >>> browser2.getControl("Activate").click()

    >>> print_feedback_messages(browser2.contents)
    There is 1 error.
    You already have a PPA for Ubuntu named 'boomppa'.

    >>> print(browser2.getControl(name="field.name").value)
    boomppa


Activating an additional PPA
----------------------------

Users who already have a PPA may activate a second one.  That's the case for
Celso.

    >>> cprov_browser.open("http://launchpad.test/~cprov")

    >>> print_tag_with_id(cprov_browser.contents, "ppas")
    Personal package archives
    PPA for Celso Providelo
    Create a new PPA

Celso can simply click on 'Create a new PPA' and will be presented to
the usual PPA activation form where the checkbox for acknowledging the
PPA-ToS is no longer present and a list of 'Existing PPAs' is presented.
Launchpad requires a user to acknowledge the PPA-ToS only once for
all their PPAs.

    >>> cprov_browser.getLink("Create a new PPA").click()

    >>> print(cprov_browser.title)
    Activate PPA : Celso Providelo

    >>> print_tag_with_id(cprov_browser.contents, "ppas")
    Existing PPAs
    PPA for Celso Providelo

    >>> cprov_browser.getControl(name="field.accepted")
    Traceback (most recent call last):
    ...
    LookupError: name ...'field.accepted'
    ...

    >>> print(
    ...     extract_text(first_tag_by_class(cprov_browser.contents, "form"))
    ... )
    URL:
      http://ppa.launchpad.test/cprov/
      At least one lowercase letter or number, followed by letters, numbers,
      dots, hyphens or pluses. Keep this name short; it is used in URLs.
    Display name:
      A short title for the archive.
    Description: (Optional)
      A short description of the archive. URLs are allowed and will be
      rendered as links.

The 'PPA name' field is not pre-filled and if Celso does not fill it then
an error is raised.

    >>> print(cprov_browser.getControl(name="field.name").value)
    <BLANKLINE>

    >>> cprov_browser.getControl(name="field.displayname").value = "Edge PPA"
    >>> cprov_browser.getControl("Activate").click()

    >>> print_feedback_messages(cprov_browser.contents)
    There is 1 error.
    Required input is missing.

An error is raised if Celso sets an invalid PPA name. Notice that the widget
automatically lowercases its input, as valid names must be lowercase. This is
also enforced by the widget in the browser.

    >>> cprov_browser.getControl(name="field.name").value = "ExPeRiMeNtAl!"
    >>> cprov_browser.getControl("Activate").click()

    >>> print_feedback_messages(cprov_browser.contents)
    There is 1 error.
    Invalid name 'experimental!'. Names must be at least two characters ...

If Celso, by mistake, uses the same name of one of his existing PPAs
(the default one is named 'ppa') an error is raised.

    >>> cprov_browser.getControl(name="field.name").value = "ppa"
    >>> cprov_browser.getControl("Activate").click()

    >>> print_feedback_messages(cprov_browser.contents)
    There is 1 error.
    You already have a PPA for Ubuntu named 'ppa'.

If the PPA is named as the distribution it is targeted for it cannot
be created, mainly because of the way we publish repositories
including the distribution name automatically.

    >>> cprov_browser.getControl(name="field.name").value = "ubuntu"
    >>> cprov_browser.getControl("Activate").click()

    >>> print_feedback_messages(cprov_browser.contents)
    There is 1 error.
    A PPA cannot have the same name as its distribution.

Providing a new name, 'edge', Celso can create a new PPA and it
immediately sent to it.

    >>> cprov_browser.getControl(name="field.name").value = "edge"
    >>> cprov_browser.getControl("Activate").click()

    >>> print(cprov_browser.title)
    Edge PPA : Celso Providelo

Back to his profile page Celso and anyone can his multiple PPAs.

    >>> cprov_browser.getLink("Celso Providelo").click()

    >>> print_tag_with_id(cprov_browser.contents, "ppas")
    Personal package archives
    Edge PPA
    PPA for Celso Providelo
    Create a new PPA

PPAs can be disabled due to ToS violations or simply because the owner
requested it. An administrator can disable Celso's 'edge' PPA.

    >>> ppa_url = cprov_browser.getLink("Edge PPA").url
    >>> admin_browser.open(ppa_url)
    >>> admin_browser.getLink("Administer archive").click()
    >>> admin_browser.getControl(name="field.enabled").value = False
    >>> admin_browser.getControl("Save").click()

Anonymous users or others with no special permissions on the disabled PPA
are unable to see it on Celso's profile page.

    >>> anon_browser.open("http://launchpad.test/~cprov")
    >>> print_tag_with_id(anon_browser.contents, "ppas")
    Personal package archives
    PPA for Celso Providelo

    >>> browser.open("http://launchpad.test/~cprov")
    >>> print_tag_with_id(browser.contents, "ppas")
    Personal package archives
    PPA for Celso Providelo

Celso himself can see the PPA, and it's linked so he can re-enable it if
required.

    >>> cprov_browser.open("http://launchpad.test/~cprov")
    >>> print_tag_with_id(cprov_browser.contents, "ppas")
    Personal package archives
    Edge PPA
    PPA for Celso Providelo
    Create a new PPA

    >>> print(cprov_browser.getLink("Edge PPA"))
    <Link ...>

And direct access to the PPA page is also denied.

    >>> anon_browser.open("http://launchpad.test/~cprov/+archive/edge")
    Traceback (most recent call last):
    ...
    zope.security.interfaces.Unauthorized: ...

    >>> browser.open("http://launchpad.test/~cprov/+archive/edge")
    Traceback (most recent call last):
    ...
    zope.security.interfaces.Unauthorized: ...

Deleted PPAs don't even show up for the owner.

    >>> from lp.soyuz.enums import ArchiveStatus
    >>> login("admin@canonical.com")
    >>> cprov = getUtility(IPersonSet).getByName("cprov")
    >>> cprov.getPPAByName(ubuntu, "edge").status = ArchiveStatus.DELETED
    >>> logout()

    >>> cprov_browser.open("http://launchpad.test/~cprov")
    >>> print_tag_with_id(cprov_browser.contents, "ppas")
    Personal package archives
    PPA for Celso Providelo
    Create a new PPA


Enabling or disabling of PPAs by the owner
------------------------------------------

Users with 'launchpad.Edit' permission for a PPA may disable or enable it.
They may also change whether the PPA is published to disk or not.

    >>> no_priv_browser = setupBrowser(
    ...     auth="Basic no-priv@canonical.com:test"
    ... )
    >>> no_priv_browser.open(
    ...     "http://launchpad.test/~no-priv/+archive/ppa/+edit"
    ... )

Initially, the PPA is enabled and publishes.

    >>> print(no_priv_browser.getControl(name="field.enabled").value)
    True
    >>> print(no_priv_browser.getControl(name="field.publish").value)
    True

After disabling the PPA a warning message is displayed on its page.

    >>> no_priv_browser.getControl(name="field.enabled").value = False
    >>> no_priv_browser.getControl(name="field.publish").value = False
    >>> no_priv_browser.getControl("Save").click()
    >>> print(
    ...     extract_text(
    ...         first_tag_by_class(
    ...             no_priv_browser.contents, "warning message"
    ...         )
    ...     )
    ... )
    This PPA has been disabled.

Going back to the edit page, we can see the publish flag was cleared:

    >>> no_priv_browser.open(
    ...     "http://launchpad.test/~no-priv/+archive/ppa/+edit"
    ... )
    >>> bool(no_priv_browser.getControl(name="field.publish").value)
    False

Once we re-enable the PPA the "disabled" warning message will be gone.

    >>> bool(no_priv_browser.getControl(name="field.enabled").value)
    False

    >>> no_priv_browser.getControl(name="field.enabled").value = True
    >>> no_priv_browser.getControl("Save").click()
    >>> (
    ...     first_tag_by_class(no_priv_browser.contents, "warning message")
    ...     is None
    ... )
    True


Deleting a PPA
--------------

Users with launchpad.Edit permission see a "Delete PPA" link in the
navigation menu.

    >>> anon_browser.open("http://launchpad.test/~no-priv/+archive/ppa")
    >>> print(anon_browser.getLink("Delete PPA"))
    Traceback (most recent call last):
    ...
    zope.testbrowser.browser.LinkNotFoundError

    >>> no_priv_browser.open("http://launchpad.test/~no-priv/+archive/ppa")
    >>> no_priv_browser.getLink("Delete PPA").click()

Clicking this link takes the user to a page that allows deletion of a PPA:

    >>> print(no_priv_browser.title)
    Delete “PPA for No Privileges Person” : PPA for No Privileges Person :
        No Privileges Person

The page contains a stern warning that this action is final and irreversible:

    >>> print(extract_text(find_main_content(no_priv_browser.contents)))
    Delete “PPA for No Privileges Person”
    ...
    Deleting a PPA will destroy all of its packages, files and the
    repository area.
    This deletion is PERMANENT and cannot be undone.
    Are you sure ?
    ...

If the user changes their mind, they can click on the cancel link to go back
a page:

    >>> print(no_priv_browser.getLink("Cancel").url)
    http://launchpad.test/~no-priv/+archive/ubuntu/ppa

Otherwise, they have a button to press to confirm the deletion.

    >>> no_priv_browser.getControl("Permanently delete PPA").click()

This action will redirect the user back to their profile page, which will
contain a notification message that the deletion is in progress.

    >>> print(no_priv_browser.url)
    http://launchpad.test/~no-priv

    >>> print_feedback_messages(no_priv_browser.contents)
    Deletion of 'PPA for No Privileges Person' has been
    requested and the repository will be removed shortly.

The deleted PPA is still available to browse via a link on the profile page
so you can see its build history, etc.:

    >>> no_priv_browser.getLink("PPA for No Privileges Person").click()

However, most of the action links are removed for deleted PPAs, so you can
no longer "Delete packages", "Edit PPA dependencies", or "Change details".

    >>> print(no_priv_browser.getLink("Change details"))
    Traceback (most recent call last):
    ...
    zope.testbrowser.browser.LinkNotFoundError

    >>> print(no_priv_browser.getLink("Edit PPA dependencies"))
    Traceback (most recent call last):
    ...
    zope.testbrowser.browser.LinkNotFoundError

    >>> no_priv_browser.getLink("View package details").click()
    >>> print(no_priv_browser.getLink("Delete packages"))
    Traceback (most recent call last):
    ...
    zope.testbrowser.browser.LinkNotFoundError

Even if someone URL-hacks to the edit form, it's not possible to
re-enable the PPA or turn on publishing.

    >>> no_priv_browser.open(
    ...     "http://launchpad.test/~no-priv/+archive/ppa/+edit"
    ... )
    >>> no_priv_browser.getControl(name="field.enabled").value = True
    >>> no_priv_browser.getControl("Save").click()
    >>> "Deleted PPAs can&#x27;t be enabled." in no_priv_browser.contents
    True
    >>> no_priv_browser.open(
    ...     "http://launchpad.test/~no-priv/+archive/ppa/+edit"
    ... )
    >>> no_priv_browser.getControl(name="field.publish").value = True
    >>> no_priv_browser.getControl("Save").click()
    >>> "Deleted PPAs can&#x27;t be enabled." in no_priv_browser.contents
    True
    >>> no_priv_browser.getLink("Cancel").click()
    >>> print(
    ...     extract_text(
    ...         first_tag_by_class(
    ...             no_priv_browser.contents, "warning message"
    ...         )
    ...     )
    ... )
    This PPA has been deleted.
