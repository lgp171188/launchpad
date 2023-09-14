It is possible for anybody to upload a BLOB to Launchpad which will be
stored for a short period of time, and deleted if unused.

    >>> anon_browser.open("http://launchpad.test/+storeblob")
    >>> anon_browser.url
    'http://launchpad.test/+storeblob'

And we test the ability to upload a blob. We have a \0 character in the
middle of the data so we can ensure binary data is handled correctly.

    >>> from io import BytesIO
    >>> blob_file = BytesIO(b"abcd\0efg")
    >>> anon_browser.getControl("BLOB").add_file(
    ...     blob_file, "ignored/mimetype", "ignored.filename"
    ... )
    >>> anon_browser.getControl("Continue").click()

    >>> import re
    >>> match = re.search(
    ...     r"Your ticket is &quot;([\w-]+)&quot;", anon_browser.contents
    ... )
    >>> match is not None
    True
    >>> ticket = six.ensure_text(match.group(1))

For easy access to the token in scripts, it's also stored in a HTTP
header in the response: X-Launchpad-Blob-Token

    >>> anon_browser.headers["X-Launchpad-Blob-Token"] == ticket
    True

Retrieve the blob and make sure it got stored correctly.

    >>> from lp.testing import login, logout, ANONYMOUS
    >>> login(ANONYMOUS)
    >>> from zope.component import getUtility
    >>> from lp.services.temporaryblobstorage.interfaces import (
    ...     ITemporaryStorageManager,
    ... )
    >>> blob = getUtility(ITemporaryStorageManager).fetch(ticket)
    >>> blob.blob == b"abcd\x00efg"
    True
    >>> logout()
