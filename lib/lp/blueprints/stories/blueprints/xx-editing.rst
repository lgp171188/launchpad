Editing Specifications
======================

Now, we are not happy with the summary and title of the spec on extension
manager support, so lets go and edit those.

First, we need to load the +edit page.

    >>> browser.addHeader("Authorization", "Basic carlos@canonical.com:test")
    >>> features_domain = "http://blueprints.launchpad.test"
    >>> spec_path = "/firefox/+spec/extension-manager-upgrades"
    >>> browser.open(features_domain + spec_path)
    >>> browser.getLink("Change details").click()
    >>> browser.url  # noqa
    'http://blueprints.launchpad.test/firefox/+spec/extension-manager-upgrades/+edit'

The page links back to the blueprint page, in case we change our minds.

    >>> back_link = browser.getLink("Extension Manager Upgrades")
    >>> back_link.url  # noqa
    'http://blueprints.launchpad.test/firefox/+spec/extension-manager-upgrades'

Launchpad won't let us use an URL already used in another blueprint.

    >>> url = "https://wiki.ubuntu.com/MediaIntegrityCheck"
    >>> browser.getControl("Specification URL").value = url
    >>> browser.getControl("Change").click()

    >>> message = (
    ...     "https://wiki.ubuntu.com/MediaIntegrityCheck is already "
    ...     "registered by"
    ... )
    >>> message in browser.contents
    True

Test the name validator filling a name of a existing specification for that
product.

    >>> browser.getControl("Name").value = "e4x"
    >>> url = "http://wiki.mozilla.org/Firefox:1.1_Product_Team"
    >>> browser.getControl("Specification URL").value = url
    >>> browser.getControl("Change").click()

    >>> message = "e4x is already in use by another blueprint"
    >>> message in browser.contents
    True

Now, let's POST the resulting changes. We should be redirected to the
specification home page.

    >>> browser.getControl("Name").value = "extension-manager-upgrades"
    >>> browser.getControl("Title").value = (
    ...     "Extension Manager System Upgrades"
    ... )
    >>> browser.getControl("Specification URL").value = url
    >>> summary = (
    ...     "Simplify the way extensions are installed and registered "
    ...     "so that: 1. third party applications can easily register "
    ...     "and deregister extensions that live with their code. 2. "
    ...     "developers can easily register extensions that they are "
    ...     "developing out of a location apart from their build (e.g."
    ...     " their home directory), and  3. developers can easily "
    ...     "install extensions for testing."
    ... )
    >>> browser.getControl("Summary").value = summary
    >>> browser.getControl("Status Whiteboard").value = "XXX"
    >>> browser.getControl("Change").click()
    >>> browser.url  # noqa
    'http://blueprints.launchpad.test/firefox/+spec/extension-manager-upgrades'

Also, we would like to assign these to someone other than Carlos, and we
would also like to have a drafter associated with it.

    >>> browser.getLink(url="+people").click()
    >>> browser.url  # noqa
    'http://blueprints.launchpad.test/firefox/+spec/extension-manager-upgrades/+people'
    >>> back_link = browser.getLink("Extension Manager System Upgrades")
    >>> back_link.url  # noqa
    'http://blueprints.launchpad.test/firefox/+spec/extension-manager-upgrades'
    >>> browser.getControl("Assignee").value = "tsukimi@quaqua.net"
    >>> browser.getControl("Drafter").value = "daf@canonical.com"
    >>> browser.getControl("Approver").value = "stuart.bishop@canonical.com"
    >>> browser.getControl("Status Whiteboard").value = "YYY"
    >>> browser.getControl("Change").click()
    >>> browser.url  # noqa
    'http://blueprints.launchpad.test/firefox/+spec/extension-manager-upgrades'

Finally, we should be able to change the status metadata (definition status,
implementation status, estimated man days etc) of the specification.

    >>> browser.getLink(url="+status").click()
    >>> back_link = browser.getLink("Extension Manager System Upgrades")
    >>> back_link.url  # noqa
    'http://blueprints.launchpad.test/firefox/+spec/extension-manager-upgrades'
    >>> browser.getControl("Definition Status").value = ["DRAFT"]
    >>> browser.getControl("Implementation Status").value = ["SLOW"]
    >>> browser.getControl("Status Whiteboard").value = "XXX"
    >>> browser.getControl("Change").click()
    >>> browser.url  # noqa
    'http://blueprints.launchpad.test/firefox/+spec/extension-manager-upgrades'

Any logged in user can edit a specification whiteboard.

    >>> user_browser.open(
    ...     "http://blueprints.launchpad.test/kubuntu/"
    ...     "+spec/krunch-desktop-plan"
    ... )
    >>> user_browser.getLink(url="+whiteboard").click()
    >>> back_link = user_browser.getLink("The Krunch Desktop Plan")
    >>> back_link.url
    'http://blueprints.launchpad.test/kubuntu/+spec/krunch-desktop-plan'

    >>> user_browser.getControl("Whiteboard").value = "XXX by Sample Person"
    >>> user_browser.getControl("Change").click()
    >>> user_browser.url
    'http://blueprints.launchpad.test/kubuntu/+spec/krunch-desktop-plan'

    >>> "XXX by Sample Person" in user_browser.contents
    True

Regular users can't access the change status page.

    >>> user_browser.getLink(url="+status")
    Traceback (most recent call last):
    ...
    zope.testbrowser.browser.LinkNotFoundError

    >>> user_browser.open(
    ...     "http://blueprints.launchpad.test/kubuntu/"
    ...     "+spec/krunch-desktop-plan/+status"
    ... )
    Traceback (most recent call last):
    ...
    zope.security.interfaces.Unauthorized: ...

Nor can they change a blueprint's priority.

    >>> user_browser.open(
    ...     "http://blueprints.launchpad.test/kubuntu/"
    ...     "+spec/krunch-desktop-plan"
    ... )
    >>> user_browser.getLink(url="+priority")
    Traceback (most recent call last):
    ...
    zope.testbrowser.browser.LinkNotFoundError

But an administrator can.

    >>> admin_browser.open(
    ...     "http://blueprints.launchpad.test/kubuntu/"
    ...     "+spec/krunch-desktop-plan"
    ... )
    >>> admin_browser.getLink(url="+priority").click()
    >>> admin_browser.url  # noqa
    'http://blueprints.launchpad.test/kubuntu/+spec/krunch-desktop-plan/+priority'
    >>> back_link = admin_browser.getLink("The Krunch Desktop Plan")
    >>> back_link.url
    'http://blueprints.launchpad.test/kubuntu/+spec/krunch-desktop-plan'
