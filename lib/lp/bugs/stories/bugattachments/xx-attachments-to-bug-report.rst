File Attachments of the Bug Report
==================================

File attachments of the bug report itself are displayed in the list of
comments. Since the text of this comment is already displayed as the
bug report itself (or is accessible via the link "show original bug
report"), no text content is displayed for this comment.

Without an attachment to the bug report, the first displayed comment
of bug #11 is:

    >>> browser.open("http://bugs.launchpad.test/redfish/+bug/11")
    >>> comment_1 = find_tags_by_class(browser.contents, "boardComment")[0]
    >>> print(extract_text(comment_1))
    Revision history for this message
    Valentina Commissari (tsukimi)
    wrote
    on 2007-03-15:
    #1
    The solution to this is to make Jokosher use autoaudiosink...

If we add an attachment to the bug report...

    >>> from io import BytesIO
    >>> from zope.component import getUtility
    >>> from lp.testing import login, logout
    >>> from lp.services.webapp.interfaces import ILaunchBag
    >>> from lp.bugs.interfaces.bug import IBugSet
    >>> login("test@canonical.com")
    >>> bug_11 = getUtility(IBugSet).get(11)
    >>> launchbag = getUtility(ILaunchBag)
    >>> launchbag.clear()
    >>> attachment = bug_11.addAttachment(
    ...     owner=None,
    ...     data=BytesIO(b"whatever"),
    ...     comment=bug_11.initial_message,
    ...     filename="test.txt",
    ...     is_patch=False,
    ...     content_type="text/plain",
    ...     description="sample data",
    ... )
    >>> logout()

...the first displayed comment shows a link to the attachment, but it
does not display a text message (which would be the same as the text
displayed as the bug report).

    >>> browser.open("http://bugs.launchpad.test/redfish/+bug/11")
    >>> comment_0 = find_tags_by_class(browser.contents, "boardComment")[0]
    >>> print(extract_text(comment_0))
    Revision history for this message
    Daniel Silverstone (kinnison)
    wrote
    on 2007-03-15:
    #0
    sample data Edit
    (8 bytes,
    text/plain)
    >>> link = browser.getLink("sample data")
    >>> print(link.url)  # noqa
    http://bugs.launchpad.test/jokosher/+bug/11/+attachment/.../+files/test.txt
    >>> print(comment_0.find("a", text="Edit"))
    <a class="sprite edit action-icon"
       href="/jokosher/+bug/11/+attachment/...">Edit</a>


Patch attachments are shown before non-patch attachments
--------------------------------------------------------

    >>> login("test@canonical.com")
    >>> launchbag.clear()
    >>> patch_attachment = bug_11.addAttachment(
    ...     owner=None,
    ...     data=BytesIO(b"patchy patch patch"),
    ...     comment=bug_11.initial_message,
    ...     filename="patch.txt",
    ...     is_patch=True,
    ...     content_type="text/plain",
    ...     description="a patch",
    ... )
    >>> logout()
    >>> browser.open("http://bugs.launchpad.test/redfish/+bug/11")
    >>> print(extract_text(browser.contents))
    Bug #11 ...
    ...Patches...
    ...a patch...
    ...Bug attachments...
    ...sample data...
    ...
