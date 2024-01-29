Display of filesize and mime type of attachments
------------------------------------------------

File size and mime type are displayed for each attachment

    >>> from io import BytesIO
    >>> foo_file = BytesIO(b"123456789" * 30)

    >>> user_browser.open(
    ...     "http://bugs.launchpad.test/firefox/+bug/1/+addcomment"
    ... )

    >>> user_browser.getControl("Attachment").add_file(
    ...     foo_file, "text/plain", "foo.txt"
    ... )
    >>> user_browser.getControl("Description").value = "description text"
    >>> user_browser.getControl(name="field.comment").value = (
    ...     "comment comment"
    ... )
    >>> user_browser.getControl("Post Comment").click()
    >>> user_browser.url
    'http://bugs.launchpad.test/firefox/+bug/1'

    >>> last_comment = find_tags_by_class(
    ...     user_browser.contents, "boardCommentBody"
    ... )[-1]
    >>> fileinfo = "(270 bytes, text/plain)"
    >>> for attachment in last_comment("li", "download-attachment"):
    ...     print(extract_text(attachment))
    ...
    description text Edit
    (270 bytes, text/plain)

A filesize of 2700 byte is displayed in 'KiB'

    >>> from lp.services.config import config
    >>> max_size_data = """
    ...     [launchpad]
    ...     max_attachment_size: 5000
    ...     """
    >>> config.push("max_size_data", max_size_data)

    >>> foo_file = BytesIO(b"123456789" * 300)

    >>> user_browser.open(
    ...     "http://bugs.launchpad.test/firefox/+bug/1/+addcomment"
    ... )

    >>> user_browser.getControl("Attachment").add_file(
    ...     foo_file, "text/plain", "foo.txt"
    ... )
    >>> user_browser.getControl("Description").value = "description text"
    >>> user_browser.getControl(name="field.comment").value = (
    ...     "comment comment"
    ... )
    >>> user_browser.getControl("Post Comment").click()
    >>> user_browser.url
    'http://bugs.launchpad.test/firefox/+bug/1'

    >>> last_comment = find_tags_by_class(
    ...     user_browser.contents, "boardCommentBody"
    ... )[-1]
    >>> fileinfo = "(270 bytes, text/plain)"
    >>> for attachment in last_comment("li", "download-attachment"):
    ...     print(extract_text(attachment))
    ...
    description text Edit
    (2.6 KiB, text/plain)

    >>> config_data = config.pop("max_size_data")
