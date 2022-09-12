TranslationImportQueueEntry page
================================

Submission and cancellation links
---------------------------------

If we load an import queue entry directly from the global import queue and
approve it, we end up back on the global translations import queue.

    >>> admin_browser.open("http://translations.launchpad.test/+imports")
    >>> admin_browser.getLink(url="imports/1").click()
    >>> print(admin_browser.getLink("Cancel").url)
    http://translations.launchpad.test/+imports
    >>> admin_browser.getControl("Approve").click()
    >>> print(admin_browser.url)
    http://translations.launchpad.test/+imports

Going to the same entry from the Evolution import queue, and then approving
it, brings us back to the Evolution import queue.

    >>> admin_browser.open(
    ...     "http://translations.launchpad.test/evolution/+imports"
    ... )
    >>> admin_browser.getLink(url="imports/1").click()
    >>> print(admin_browser.getLink("Cancel").url)
    http://translations.launchpad.test/evolution/+imports
    >>> admin_browser.getControl("Approve").click()
    >>> print(admin_browser.url)
    http://translations.launchpad.test/evolution/+imports

Similarly, if we go to an import queue entry through the user's import
queue, after approving the entry we are back looking at user's import queue.

    >>> admin_browser.open(
    ...     "http://translations.launchpad.test/~name16/+imports"
    ... )
    >>> admin_browser.getLink(url="imports/1").click()
    >>> print(admin_browser.getLink("Cancel").url)
    http://translations.launchpad.test/~name16/+imports
    >>> admin_browser.getControl("Approve").click()
    >>> print(admin_browser.url)
    http://translations.launchpad.test/~name16/+imports
