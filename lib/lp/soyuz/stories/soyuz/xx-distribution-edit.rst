Editing distributions
=====================

Change some details of the Ubuntu distribution that were incorrect.

    >>> admin_browser.open("http://launchpad.test/ubuntu")
    >>> admin_browser.getLink("Change details").click()
    >>> admin_browser.url
    'http://launchpad.test/ubuntu/+edit'

    >>> admin_browser.getControl("Display Name").value
    'Ubuntu'
    >>> admin_browser.getControl("Display Name").value = "Test Distro"

    >>> admin_browser.getControl("Summary").value = "Test Distro Summary"
    >>> admin_browser.getControl("Description").value = (
    ...     "Test Distro Description"
    ... )

    >>> admin_browser.getControl("Change", index=3).click()
    >>> admin_browser.url
    'http://launchpad.test/ubuntu'

The changed values can be seen on the distribution's +edit page.

    >>> admin_browser.getLink("Change details").click()

    >>> admin_browser.getControl("Display Name").value
    'Test Distro'
