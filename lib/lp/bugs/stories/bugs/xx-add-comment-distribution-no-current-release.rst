Add a comment on a bug on a distribution with no current release
================================================================

If a bug is reported distribution with no current release, like Gentoo,
it's still possible to add comments to the bug.

    >>> user_browser.open("http://launchpad.test/gentoo/+filebug")
    >>> user_browser.getControl("Summary", index=0).value = "Test bug"
    >>> user_browser.getControl("Continue").click()
    >>> user_browser.getControl("Bug Description").value = "A test bug."
    >>> user_browser.getControl("Submit Bug Report").click()
    >>> user_browser.url
    'http://bugs.launchpad.test/gentoo/+bug/...'

    >>> user_browser.getControl(name="field.comment").value = "A new comment."
    >>> user_browser.getControl("Post Comment", index=-1).click()

    >>> for comment_div in find_tags_by_class(
    ...     user_browser.contents, "boardCommentBody"
    ... ):
    ...     print(comment_div.div.decode_contents())
    <div...><p>A new comment.</p></div>
