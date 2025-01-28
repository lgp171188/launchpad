Uploading templates
===================

An upstream maintainer can use Launchpad to submit their initial
template uploads.

    >>> ff_owner_browser = setupBrowser(auth="Basic test@canonical.com:test")
    >>> ff_owner_browser.open(
    ...     "http://translations.launchpad.test/firefox/1.0/"
    ...     "+translations-upload"
    ... )
    >>> "Here you can upload translation files" in ff_owner_browser.contents
    True

The upload consists of a tarball containing templates and/or
translations.

    >>> import lp.translations
    >>> import os.path
    >>> test_file_name = os.path.join(
    ...     os.path.dirname(lp.translations.__file__),
    ...     "stories/importqueue/xx-translation-import-queue.tar.gz",
    ... )
    >>> tarball = open(test_file_name, "rb")
    >>> upload = ff_owner_browser.getControl("File")
    >>> upload
    <Control name='file' type='file'>
    >>> upload.add_file(tarball, "application/x-gzip", test_file_name)
    >>> ff_owner_browser.getControl("Upload").click()
    >>> ff_owner_browser.url
    'http://translations.launchpad.test/firefox/1.0/+translations-upload'
    >>> "Upload translation files" in ff_owner_browser.contents
    True
    >>> for tag in find_tags_by_class(
    ...     ff_owner_browser.contents, "informational message"
    ... ):
    ...     print(extract_text(tag.decode_contents()))
    Thank you for your upload. 2 files from the tarball will be automatically
    reviewed in the next few hours...

The confirmation form shows the user the link where they could track the
import status:

    >>> ff_owner_browser.getLink("Translation Import Queue").click()
    >>> print(ff_owner_browser.url)
    http://translations.launchpad.test/firefox/1.0/+imports

Once the upload has completed, its templates and translations show up on
the translation import queue page.  If we're not logged in, status is
shown as static HTML.

    >>> anon_browser.open(
    ...     "http://translations.launchpad.test/firefox/1.0/+imports"
    ... )
    >>> print(anon_browser.url)
    http://translations.launchpad.test/firefox/1.0/+imports
    >>> row = find_tags_by_class(anon_browser.contents, "import_entry_row")[1]
    >>> print(extract_text(row.find(class_="import_source")))
    po/es.po in Mozilla Firefox 1.0 series
    >>> print(extract_text(row.find(class_="import_status")))
    Needs Review

Some tarballs contain files whose names look like PO or POT files, but
that are really editor backups whose name begin with a dot.  These are
ignored, as well as empty files, and things whose names end in .po or
.pot that aren't regular files such as directories or devices.

    >>> import tarfile
    >>> tarball = tarfile.open(test_file_name)
    >>> "device.po" in tarball.getnames()
    True
    >>> "device.po" in anon_browser.contents
    False
    >>> ".dotfile.po" in tarball.getnames()
    True
    >>> ".dotfile.po" in anon_browser.contents
    False
    >>> "po/.nested-dotfile.po" in tarball.getnames()
    True
    >>> "po/.nested-dotfile.po" in anon_browser.contents
    False
    >>> "empty.po" in tarball.getnames()
    True
    >>> "empty.po" in anon_browser.contents
    False
    >>> "directory.po" in tarball.getnames()
    True
    >>> "directory.po" in anon_browser.contents
    False
    >>> "directory.po/.another-dotfile.po" in tarball.getnames()
    True
    >>> "directory.po/.another-dotfile.po" in anon_browser.contents
    False

If we are logged in as an administrator, the same page provides a link
to where we can edit imports.

    >>> browser = setupBrowser(auth="Basic jordi@ubuntu.com:test")
    >>> browser.open("http://translations.launchpad.test/+imports")
    >>> "po/es.po" in browser.contents
    True
    >>> "Mozilla Firefox 1.0 series" in browser.contents
    True
    >>> link = browser.getLink("Change this entry", index=2)
    >>> link
    <Link text='Change this entry'
          url='http://translations.launchpad.test/+imports/...'>
    >>> qid = int(link.url.rsplit("/", 1)[-1])
    >>> browser.getControl(name="field.status_%d" % qid).displayValue
    ['Needs Review']

Now, we attach a new file to an already existing translation resource.

    >>> browser.open(
    ...     "http://translations.launchpad.test/ubuntu/hoary/+source/"
    ...     "evolution/+pots/evolution-2.2/+upload"
    ... )
    >>> upload = browser.getControl("File")
    >>> upload
    <Control name='file' type='file'>
    >>> from io import BytesIO
    >>> upload.add_file(
    ...     BytesIO(b"# foo\n"),
    ...     "text/x-gettext-translation-template",
    ...     "evolution.pot",
    ... )
    >>> browser.getControl("Upload").click()
    >>> print(browser.url)  # noqa
    http://translations.launchpad.test/ubuntu/hoary/+source/evolution/+pots/evolution-2.2/+upload
    >>> for tag in find_tags_by_class(browser.contents, "message"):
    ...     print(tag.decode_contents())
    ...
    Thank you for your upload.  It will be automatically reviewed...

The import queue should have three additional entries with the last upload as
the last entry.

    >>> anon_browser.open("http://translations.launchpad.test/+imports")
    >>> nav_index = first_tag_by_class(
    ...     anon_browser.contents, "batch-navigation-index"
    ... )
    >>> print(extract_text(nav_index, formatter="html"))
    1 &rarr; 5 of 5 results
    >>> rows = find_tags_by_class(anon_browser.contents, "import_entry_row")
    >>> print(extract_text(rows[4]))
    evolution.pot in
    evolution in Ubuntu Hoary
    Needs Review

Open the edit form for the third entry.

    >>> browser.open("http://translations.launchpad.test/+imports")
    >>> browser.getLink(url="imports/%d" % qid).click()

And provide information for this IPOTemplate to be newly created. Invalid
names for the template are rejected.

    >>> browser.getControl("File Type").value = ["POT"]
    >>> browser.getControl("Path").value = "pkgconf-mozilla.pot"
    >>> browser.getControl("Name").value = ".InvalidName"
    >>> browser.getControl("Translation domain").value = "pkgconf-mozilla"
    >>> browser.getControl("Approve").click()
    >>> print(browser.url)
    http://translations.launchpad.test/+imports/.../+index
    >>> message = find_tags_by_class(browser.contents, "message")[1]
    >>> print(message.string)
    Please specify a valid name...

So we'd better specify a valid name.

    >>> browser.getControl("Name").value = "pkgconf-mozilla"
    >>> browser.getControl("Approve").click()
    >>> print(browser.url)
    http://translations.launchpad.test/+imports

Open the edit form for the fourth entry.

XXX DaniloSegan 2009-09-01: it seems we are hitting Zope testbrowser
bug, so we need to reopen the page we are currently at to set 'referer'
header properly.  This seems similar to #98437 but the fix proposed
there doesn't help.

    >>> browser.open("http://translations.launchpad.test/+imports")
    >>> browser.getLink(url="imports/%d" % (qid + 1)).click()

And provide information for this IPOFile to be newly created.

    >>> browser.getControl("File Type").value = ["PO"]
    >>> browser.getControl(name="field.potemplate").displayValue = [
    ...     "pkgconf-mozilla"
    ... ]
    >>> browser.getControl("Language").value = ["es"]
    >>> browser.getControl("Approve").click()
    >>> print(browser.url)
    http://translations.launchpad.test/+imports

The entries are approved, and now have the place where they will be
imported assigned.

    >>> anon_browser.open("http://translations.launchpad.test/+imports")
    >>> imports_table = find_tag_by_id(
    ...     anon_browser.contents, "import-entries-list"
    ... )
    >>> print(extract_text(imports_table))
    pkgconf-mozilla.pot in
    Mozilla Firefox 1.0 series
    Approved
    ...
    Template "pkgconf-mozilla" in Mozilla Firefox 1.0
    po/es.po in
    Mozilla Firefox 1.0 series
    Approved
    ...
    Spanish (es) translation of pkgconf-mozilla in Mozilla Firefox 1.0
    ...

Removing from the import queue
------------------------------

There is an option to remove entries from the queue.

No Privileges Person tries to remove entries but to no effect.

    >>> from urllib.parse import urlencode
    >>> post_data = urlencode(
    ...     {
    ...         "field.filter_target": "all",
    ...         "field.filter_status": "all",
    ...         "field.filter_extension": "all",
    ...         "field.status_1": "DELETED",
    ...         "field.status_2": "DELETED",
    ...         "field.status_3": "DELETED",
    ...         "field.status_4": "DELETED",
    ...         "field.status_5": "DELETED",
    ...         "field.actions.change_status": "Change status",
    ...     }
    ... )
    >>> user_browser.addHeader("Referer", "http://launchpad.test")
    >>> user_browser.open(
    ...     "http://translations.launchpad.test/+imports", data=post_data
    ... )
    >>> for status in find_tags_by_class(
    ...     user_browser.contents, "import_status"
    ... ):
    ...     print(extract_text(status))
    Approved
    Approved
    Imported
    Imported
    Needs Review

But Jordi, a Rosetta expert, will be allowed to remove it.

    >>> jordi_browser = setupBrowser(auth="Basic jordi@ubuntu.com:test")
    >>> jordi_browser.open("http://translations.launchpad.test/+imports")
    >>> jordi_browser.getControl(name="field.status_1").value = ["DELETED"]
    >>> jordi_browser.getControl("Change status").click()
    >>> jordi_browser.url
    'http://translations.launchpad.test/+imports/+index'

    >>> print(find_main_content(jordi_browser.contents))
    <...po/evolution-2.2-test.pot...
    ...Evolution trunk series...
    ...field.status_1...
    ...selected="selected" value="DELETED"...
    ...Foo Bar...
    ...Template "evolution-2.2-test" in Evolution trunk...

Foo Bar Person is a launchpad admin and they're allowed to remove an entry.

    >>> admin_browser.open("http://translations.launchpad.test/+imports")
    >>> admin_browser.getControl(name="field.status_2").value = ["DELETED"]
    >>> admin_browser.getControl("Change status").click()
    >>> admin_browser.url
    'http://translations.launchpad.test/+imports/+index'

    >>> print(find_main_content(admin_browser.contents))
    <...po/pt_BR.po...
    ...Evolution trunk series...
    ...field.status_2...
    ...selected="selected" value="DELETED"...
    ...Foo Bar...
    ...Portuguese (Brazil) (pt_BR) translation of evolution-2.2-test
      in Evolution trunk...

And finally, we make sure that the importer is also allowed to remove their
own imports.

    >>> ff_owner_browser.open("http://translations.launchpad.test/+imports")
    >>> status = ff_owner_browser.getControl(
    ...     name="field.status_%d" % (qid + 1)
    ... )
    >>> status.value
    ['APPROVED']
    >>> status.value = ["DELETED"]
    >>> ff_owner_browser.getControl("Change status").click()

The entry now appears deleted.

    >>> print(find_main_content(ff_owner_browser.contents))
    <...po/es.po...
    ...Mozilla Firefox 1.0 series...
    ...field.status_...
    ...selected="selected" value="DELETED"...
    ...Sample Person...
    ...Spanish (es) translation of pkgconf-mozilla in Mozilla Firefox 1.0...


Ubuntu uploads
--------------

As a special case, the owners of Ubuntu's translation group are allowed
to manage Ubuntu uploads.

    >>> from zope.component import getUtility
    >>> from lp.registry.interfaces.distribution import IDistributionSet
    >>> from lp.translations.model.translationimportqueue import (
    ...     TranslationImportQueue,
    ... )
    >>> login("admin@canonical.com")
    >>> queue = TranslationImportQueue()
    >>> ubuntu = getUtility(IDistributionSet)["ubuntu"]
    >>> hoary = ubuntu["hoary"]

There is a translation group for Ubuntu.  Its owner has no special
privileges or roles other than running the group.

Somebody else has uploaded a translation template for an Ubuntu package.

    >>> package = factory.makeSourcePackageName()
    >>> group_owner = factory.makePerson(
    ...     email="go@example.com", name="groupowner"
    ... )
    >>> uploader = factory.makePerson()
    >>> ubuntu.translationgroup = factory.makeTranslationGroup(group_owner)

    >>> login(ANONYMOUS)
    >>> ubuntu_upload = queue.addOrUpdateEntry(
    ...     "messages.pot",
    ...     b"(content)",
    ...     False,
    ...     uploader,
    ...     sourcepackagename=package,
    ...     distroseries=hoary,
    ... )
    >>> logout()

The owner of Ubuntu's translation group, despite not being the owner or
having any special privileges, is permitted to approve it.

    >>> group_owner_browser = setupBrowser(auth="Basic go@example.com:test")
    >>> group_owner_browser.open(
    ...     "http://translations.launchpad.test/+imports/%d"
    ...     % ubuntu_upload.id
    ... )
    >>> group_owner_browser.getControl(name="field.name").value = "f918"
    >>> group_owner_browser.getControl(
    ...     name="field.translation_domain"
    ... ).value = "f918"
    >>> group_owner_browser.getControl(name="field.actions.approve").click()


Corner cases
------------

Let's check tar.bz2 uploads. They work ;-)

    >>> evo_owner_browser = ff_owner_browser
    >>> evo_owner_browser.open(
    ...     "http://translations.launchpad.test/evolution/trunk/"
    ...     "+translations-upload"
    ... )

    >>> test_file_name = os.path.join(
    ...     os.path.dirname(lp.translations.__file__),
    ...     "stories/importqueue/xx-translation-import-queue.tar.bz2",
    ... )
    >>> tarball = open(test_file_name, "rb")

    >>> evo_owner_browser.getControl("File").add_file(
    ...     tarball, "application/x-bzip", test_file_name
    ... )
    >>> evo_owner_browser.getControl("Upload").click()
    >>> evo_owner_browser.url
    'http://translations.launchpad.test/evolution/trunk/+translations-upload'
    >>> for tag in find_tags_by_class(evo_owner_browser.contents, "message"):
    ...     print(extract_text(tag))
    ...
    Thank you for your upload. 2 files from the tarball will be automatically
    reviewed...

Let's try breaking the form by not supplying a file object. It give us a
decent error message:

    >>> browser.open(
    ...     "http://translations.launchpad.test/ubuntu/hoary/"
    ...     "+source/evolution/+pots/evolution-2.2/+upload"
    ... )
    >>> browser.getControl("Upload").click()
    >>> for tag in find_tags_by_class(browser.contents, "message"):
    ...     print(tag)
    ...
    <div...Your upload was ignored because you didn't select a file....
    ...Please select a file and try again.</div>...

Let's try now a tarball upload. Should work:

    >>> evo_owner_browser.open(
    ...     "http://translations.launchpad.test/evolution/trunk/"
    ...     "+translations-upload"
    ... )

    >>> test_file_name = os.path.join(
    ...     os.path.dirname(lp.translations.__file__),
    ...     "stories/importqueue/xx-translation-import-queue.tar",
    ... )
    >>> tarball = open(test_file_name, "rb")

    >>> evo_owner_browser.getControl("File").add_file(
    ...     tarball, "application/x-gzip", test_file_name
    ... )
    >>> evo_owner_browser.getControl("Upload").click()
    >>> evo_owner_browser.url
    'http://translations.launchpad.test/evolution/trunk/+translations-upload'
    >>> for tag in find_tags_by_class(evo_owner_browser.contents, "message"):
    ...     print(extract_text(tag))
    ...
    Thank you for your upload. 1 file from the tarball will be automatically
    reviewed...

We can handle an empty file disguised as a bzipped tarfile:

    >>> evo_owner_browser.open(
    ...     "http://translations.launchpad.test/evolution/trunk/"
    ...     "+translations-upload"
    ... )

    >>> test_file_name = os.path.join(
    ...     os.path.dirname(lp.translations.__file__),
    ...     "stories/importqueue/empty.tar.bz2",
    ... )
    >>> tarball = open(test_file_name, "rb")

    >>> evo_owner_browser.getControl("File").add_file(
    ...     tarball, "application/x-gzip", test_file_name
    ... )
    >>> evo_owner_browser.getControl("Upload").click()
    >>> evo_owner_browser.url
    'http://translations.launchpad.test/evolution/trunk/+translations-upload'
    >>> for tag in find_tags_by_class(evo_owner_browser.contents, "message"):
    ...     print(extract_text(tag))
    ...
    Upload ignored.  The tarball you uploaded did not contain...

And also a truncated tarball inside a bzip2 wrapper:

    >>> evo_owner_browser.open(
    ...     "http://translations.launchpad.test/evolution/trunk/"
    ...     "+translations-upload"
    ... )

    >>> test_file_name = os.path.join(
    ...     os.path.dirname(lp.translations.__file__),
    ...     "stories/importqueue/truncated.tar.bz2",
    ... )
    >>> tarball = open(test_file_name, "rb")

    >>> evo_owner_browser.getControl("File").add_file(
    ...     tarball, "application/x-gzip", test_file_name
    ... )
    >>> evo_owner_browser.getControl("Upload").click()
    >>> evo_owner_browser.url
    'http://translations.launchpad.test/evolution/trunk/+translations-upload'
    >>> for tag in find_tags_by_class(evo_owner_browser.contents, "message"):
    ...     print(extract_text(tag))
    ...
    Upload ignored.  The tarball you uploaded did not contain...

Or even files that are not really tar.gz files even if the filename
says that.

    >>> evo_owner_browser.open(
    ...     "http://translations.launchpad.test/evolution/trunk/"
    ...     "+translations-upload"
    ... )
    >>> evo_owner_browser.getControl("File").add_file(
    ...     BytesIO(b"foo"), "application/x-gzip", test_file_name
    ... )
    >>> evo_owner_browser.getControl("Upload").click()
    >>> evo_owner_browser.url
    'http://translations.launchpad.test/evolution/trunk/+translations-upload'
    >>> print_feedback_messages(evo_owner_browser.contents)
    Upload ignored.  The tarball you uploaded did not contain...

Bad filter_extension
~~~~~~~~~~~~~~~~~~~~

Very often robots attempt to request URLs with garbage appended to the end.
In at least one case it seems to have happened because someone on IRC closed a
parenthesis right after the URL, and an IRC log site linkified the URL with
the erroneous parenthesis included.

Here we'll simulate such a request and show that the resulting unrecognized
filter_extension values do not generate an error.  See bug 388997.

    >>> post_data = urlencode(
    ...     {
    ...         "field.filter_target": "all",
    ...         "field.filter_status": "all",
    ...         "field.filter_extension": "potlksajflkasj",
    ...         "field.actions.change_status": "Change status",
    ...     }
    ... )
    >>> user_browser.open(
    ...     "http://translations.launchpad.test/+imports", data=post_data
    ... )
