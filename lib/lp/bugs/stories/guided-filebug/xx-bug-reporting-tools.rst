Bug Reporting Tools
===================

In order to produce better bug reports, a bug reporting tool on the
user's computer can upload a message containing extra information about
the bug to Launchpad.

There is no API for uploading blobs, thus they need to do a HTTP POST to
a web form to upload debug data. There are several versions of Apport out
there depending on the field names on +storeblob, so it's important that
those names (including the name of the button) doesn't change. The lines
that are important not to change are marked with a "Don't change!"
comment.

    >>> import os.path
    >>> from lp.services.config import config
    >>> testfiles = os.path.join(config.root, "lib/lp/bugs/tests/testfiles")
    >>> extra_filebug_data = open(
    ...     os.path.join(testfiles, "extra_filebug_data.msg"), "rb"
    ... )

    NOTE: The form names are used instead of their labels here, because
          external tools depend on them.
    >>> anon_browser.open("http://launchpad.test/+storeblob")
    >>> anon_browser.getControl(name="field.blob").add_file(  # Don't change!
    ...     extra_filebug_data, "not/important", "not.important"
    ... )
    >>> anon_browser.getControl(name="FORM_SUBMIT").click()  # Don't change!

After the file has been uploaded, the tool is given a token it can use
to give the data to the +filebug page.

    >>> for message in find_tags_by_class(anon_browser.contents, "message"):
    ...     print(message.decode_contents())
    ...
    Your ticket is "..."

To avoid having the tool from parsing the HTML page, the token is
returned as a X-Launchpad-Blob-Token header in the response as well:

    >>> blob_token = six.ensure_text(
    ...     anon_browser.headers["X-Launchpad-Blob-Token"]
    ... )

This token we can now pass to the +filebug page by appending it to the
URL as an extra path component, like '+filebug/12345abcde'.

We'll define a helper method here to make processing the uploaded blob
easier.

    >>> from zope.component import getUtility
    >>> from lp.bugs.interfaces.apportjob import IProcessApportBlobJobSource

    >>> def process_blob(token):
    ...     login("foo.bar@canonical.com")
    ...     job = getUtility(IProcessApportBlobJobSource).getByBlobUUID(token)
    ...     job.job.start()
    ...     job.run()
    ...     job.job.complete()
    ...     logout()
    ...

Guided +filebug
===============

The most common case will be that the user is sent to the guided
+filebug page and the user goes through the workflow there.

    >>> filebug_host = "launchpad.test"
    >>> filebug_path = (
    ...     "/ubuntu/+source/mozilla-firefox/+filebug/%s" % blob_token
    ... )
    >>> filebug_url = "http://%s%s" % (filebug_host, filebug_path)
    >>> contents = str(
    ...     http(
    ...         "GET %s HTTP/1.1\nHostname: %s\n"
    ...         "Authorization: Basic test@canonical.com:test\n\n"
    ...         % (filebug_path, filebug_host)
    ...     )
    ... )

At first, the user will be shown a message telling them that the extra
data is being processed.

    >>> for message in find_tags_by_class(contents, "message"):
    ...     print(message.decode_contents())
    ...
    Please wait while bug data is processed. This page will refresh
    every 10 seconds until processing is complete.

The page header contains a 10-second meta refresh tag.

    >>> '<meta http-equiv="refresh" content="10"' in contents
    True

Once the data has been processed, the +filebug process can continue as
normal.

    >>> process_blob(blob_token)
    >>> user_browser.open(filebug_url)

A notification will be shown to inform the user that additional
information will be added to the bug automatically.

    >>> for message in find_tags_by_class(user_browser.contents, "message"):
    ...     print(message.decode_contents())
    ...
    Extra debug information will be added to the bug report automatically.

After the user fills in the summary and click on the button, we'll still
be on the same URL, with the token present.

    >>> user_browser.getControl("Summary", index=0).value
    ''
    >>> user_browser.getControl("Summary", index=0).value = "A new bug"
    >>> user_browser.getControl("Continue").click()
    >>> user_browser.url == filebug_url
    True

Even if the form has errors the token will be present in the URL.

    >>> user_browser.getControl("Bug Description").value
    ''
    >>> user_browser.getControl("Submit Bug Report").click()
    >>> for error in find_tags_by_class(
    ...     user_browser.contents, "message error"
    ... ):
    ...     print(error.decode_contents())
    There is 1 error.

    >>> user_browser.url == filebug_url
    True

If we go ahead submitting the bug, the bug will have all the extra
information specified in the extra filebug data.

    >>> user_browser.getControl("Bug Description").value = (
    ...     "A bug description."
    ... )
    >>> user_browser.getControl("Submit Bug Report").click()
    >>> user_browser.url
    'http://bugs.launchpad.test/ubuntu/+source/mozilla-firefox/+bug/...'

Two attachments were added.

    >>> attachment_portlet = find_portlet(
    ...     user_browser.contents, "Bug attachments"
    ... )
    >>> for li in attachment_portlet("li", "download-attachment"):
    ...     print(li.a.decode_contents())
    ...
    attachment1
    Attachment description.

And three comments were added, including the empty comment that was
created for the attachments.

    >>> print_comments(user_browser.contents)
    <div...><p>This should be added as a comment.</p></div>
    ----------------------------------------
    <div...><p>This should be added as another comment.</p></div>
    ----------------------------------------
    Attachment: attachment1
    Attachment: Attachment description.
    <div class="comment-text editable-message-text"...></div>
    ----------------------------------------


Initial bug summary
-------------------

If the uploaded message contains a Subject field in the initial headers,
that will be used to automatically fill in a suggested title.

    >>> extra_filebug_data_with_subject = open(
    ...     os.path.join(testfiles, "extra_filebug_data_subject.msg"), "rb"
    ... )
    >>> anon_browser.open("http://launchpad.test/+storeblob")
    >>> anon_browser.getControl(name="field.blob").add_file(  # Don't change!
    ...     extra_filebug_data_with_subject, "not/important", "not.important"
    ... )
    >>> anon_browser.getControl(name="FORM_SUBMIT").click()  # Don't change!
    >>> blob_token = six.ensure_text(
    ...     anon_browser.headers["X-Launchpad-Blob-Token"]
    ... )
    >>> process_blob(blob_token)

    >>> user_browser.open(
    ...     "http://launchpad.test/ubuntu/+source/mozilla-firefox/+filebug/"
    ...     "%s" % blob_token
    ... )

    >>> user_browser.getControl("Summary", index=0).value
    'Initial bug summary'

The user can of course change the summary if they want to.

    >>> user_browser.getControl("Summary", index=0).value = "Another summary"
    >>> user_browser.getControl("Continue").click()
    >>> user_browser.getControl("Summary", index=0).value
    'Another summary'

Tags
----

If the uploaded message contains a Tags field, the tags widget will be
initialized with that value.

    >>> extra_filebug_data_with_subject = open(
    ...     os.path.join(testfiles, "extra_filebug_data_tags.msg"), "rb"
    ... )
    >>> anon_browser.open("http://launchpad.test/+storeblob")
    >>> anon_browser.getControl(name="field.blob").add_file(  # Don't change!
    ...     extra_filebug_data_with_subject, "not/important", "not.important"
    ... )
    >>> anon_browser.getControl(name="FORM_SUBMIT").click()  # Don't change!
    >>> blob_token = six.ensure_text(
    ...     anon_browser.headers["X-Launchpad-Blob-Token"]
    ... )
    >>> process_blob(blob_token)

    >>> user_browser.open(
    ...     "http://launchpad.test/ubuntu/+source/mozilla-firefox/"
    ...     "+filebug/%s" % blob_token
    ... )
    >>> user_browser.getControl("Summary", index=0).value = "Another summary"
    >>> user_browser.getControl("Continue").click()

    >>> user_browser.getControl("Tags").value
    'bar foo'

The user can of course change the tags if they want.

    >>> user_browser.getControl("Tags").value = "bar baz"
    >>> user_browser.getControl("Summary", index=0).value = "Bug Summary"
    >>> user_browser.getControl("Bug Description").value = "Bug description."
    >>> user_browser.getControl("Submit Bug Report").click()
    >>> user_browser.url
    'http://bugs.launchpad.test/ubuntu/+source/mozilla-firefox/+bug/...'

    >>> tags = find_tag_by_id(user_browser.contents, "bug-tags")
    >>> print(extract_text(tags))
    Tags: bar baz...

The normal +filebug page has a hidden tags widget, so bugs filed via
that will get their tags set as well.

    >>> user_browser.open(
    ...     "http://launchpad.test/ubuntu/+source/mozilla-firefox/+filebug/"
    ...     "%s" % blob_token
    ... )
    >>> user_browser.getControl("Summary", index=0).value = "Bug Summary"
    >>> user_browser.getControl("Continue").click()

    >>> user_browser.getControl("Bug Description").value = "Bug description."
    >>> user_browser.getControl("Submit Bug Report").click()
    >>> user_browser.url
    'http://bugs.launchpad.test/ubuntu/+source/mozilla-firefox/+bug/...'

    >>> tags = find_tag_by_id(user_browser.contents, "bug-tags")
    >>> print(extract_text(tags))
    Tags: bar foo...
