Adding attachments when filing a bug
====================================

It is possible to add attachments when filing a bug. The tests in this
file will cover this functionality for both the guided and advanced
filebug forms.


Guided filebug form
-------------------

Adding an attachment to a new bug is part of the second step of the
guided filebug form.

    >>> user_browser.open("http://bugs.launchpad.test/firefox/+filebug")
    >>> user_browser.getControl("Summary", index=0).value = (
    ...     "A totally new " "bug with attachments"
    ... )
    >>> user_browser.getControl("Continue").click()
    >>> user_browser.getControl("Bug Description").value = (
    ...     "We can now add attachments!"
    ... )

No Privileges Person chooses to add an attachment to the bug. We create
a file-like object to demonstrate this.

    >>> from io import BytesIO
    >>> example_file = BytesIO(b"Traceback...")
    >>> _ = example_file.seek(0)

    >>> user_browser.getControl("Attachment").add_file(
    ...     example_file, "text/plain", "example.txt"
    ... )
    >>> user_browser.getControl("Description", index=1).value = (
    ...     "A description " "of the attachment"
    ... )
    >>> user_browser.getControl("Submit Bug Report").click()
    >>> user_browser.title
    'Bug #... : Bugs : Mozilla Firefox'

No Privileges Person sees a notice on the bug page stating that the file
was attached.

    >>> print_feedback_messages(user_browser.contents)
    Thank you for your bug report.
    The file "example.txt" was attached to the bug report.

No Privileges Person can see the attachment in the attachments portlet.

    >>> attachments = find_portlet(user_browser.contents, "Bug attachments")
    >>> for li_tag in attachments.find_all("li", "download-attachment"):
    ...     print(li_tag.a.decode_contents())
    ...
    A description of the attachment

    >>> user_browser.getLink("A description of the attachment").url
    'http://bugs.launchpad.test/firefox/+bug/.../+attachment/.../+files/ex...'


Empty Attachment Fields
-----------------------

Sometimes browsers submit values empty fields, leading them to being
treated as non-empty by the receiving view. The attachment form will
treat all empty-equivalent values equally.

    >>> print(
    ...     http(
    ...         rb"""
    ... POST /firefox/+filebug HTTP/1.1
    ... Authorization: Basic test@canonical.com:test
    ... Referer: https://launchpad.test/
    ... Content-Type: multipart/form-data; boundary=---------------------------2051078912280543729816242321
    ...
    ... -----------------------------2051078912280543729816242321
    ... Content-Disposition: form-data; name="field.title"
    ...
    ... A title of some description
    ... -----------------------------2051078912280543729816242321
    ... Content-Disposition: form-data; name="field.tags"
    ...
    ...
    ... -----------------------------2051078912280543729816242321
    ... Content-Disposition: form-data; name="field.comment"
    ...
    ... A description, which explains things.
    ... -----------------------------2051078912280543729816242321
    ... Content-Disposition: form-data; name="field.filecontent.used"
    ...
    ...
    ... -----------------------------2051078912280543729816242321
    ... Content-Disposition: form-data; name="field.filecontent"; filename=""
    ... Content-Type: application/octet-stream
    ...
    ...
    ... -----------------------------2051078912280543729816242321
    ... Content-Disposition: form-data; name="field.patch.used"
    ...
    ...
    ... -----------------------------2051078912280543729816242321
    ... Content-Disposition: form-data; name="field.attachment_description"
    ...
    ...
    ... -----------------------------2051078912280543729816242321
    ... Content-Disposition: form-data; name="field.security_related.used"
    ...
    ...
    ... -----------------------------2051078912280543729816242321
    ... Content-Disposition: form-data; name="field.actions.submit_bug"
    ...
    ... Submit Bug Report
    ... -----------------------------2051078912280543729816242321--
    ... """
    ...     )
    ... )  # noqa
    HTTP/1.1 303 See Other...
    Location: http://bugs.launchpad.test/firefox/+bug/...
