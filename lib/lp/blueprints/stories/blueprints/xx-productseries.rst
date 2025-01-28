
Targeting to ProductSeries
==========================

A number of tests in this need a product with blueprints enabled, so we'll
enable them on firefox.

    >>> from zope.component import getUtility
    >>> from lp.app.enums import ServiceUsage
    >>> from lp.registry.interfaces.product import IProductSet
    >>> login("admin@canonical.com")
    >>> firefox = getUtility(IProductSet).getByName("firefox")
    >>> firefox.blueprints_usage = ServiceUsage.LAUNCHPAD
    >>> transaction.commit()
    >>> logout()

In terms of feature management for release series and for distroseriess, we
want to target one of these specs to the 1.0 series. We will use the "e4x"
specification.

First we load the page to target to the series.

    >>> browser.addHeader(
    ...     "Authorization", "Basic celso.providelo@canonical.com:test"
    ... )
    >>> browser.open(
    ...     "http://blueprints.launchpad.test/firefox/+spec/svg-support"
    ... )
    >>> browser.getLink("Propose as goal").click()
    >>> back_link = browser.getLink("Support Native SVG Objects")
    >>> back_link.url
    'http://blueprints.launchpad.test/firefox/+spec/svg-support'
    >>> browser.getLink("Cancel").url
    'http://blueprints.launchpad.test/firefox/+spec/svg-support'

We can see two potential series candidates, the "trunk" and the "1.0" series.

    >>> print(find_main_content(browser.contents))
    <...
    <option selected="selected" value="">(nothing selected)</option>
    <option value="2">firefox 1.0</option>
    <option value="1">firefox trunk</option>
    ...

Now, we POST the form and expect to be redirected to the spec home page.
Note that we use a user who DOES NOT have the "driver" role on that series,
so the targeting should NOT be automatically approved.

    >>> print(
    ...     http(
    ...         r"""
    ... POST /firefox/+spec/svg-support/+setproductseries HTTP/1.1
    ... Authorization: Basic celso.providelo@canonical.com:test
    ... Referer: https://launchpad.test/
    ... Content-Type: multipart/form-data; boundary=---------------------------26999413214087432371486976730
    ...
    ... -----------------------------26999413214087432371486976730
    ... Content-Disposition: form-data; name="field.productseries"
    ...
    ... 2
    ... -----------------------------26999413214087432371486976730
    ... Content-Disposition: form-data; name="field.productseries-empty-marker"
    ...
    ... 1
    ... -----------------------------26999413214087432371486976730
    ... Content-Disposition: form-data; name="field.whiteboard"
    ...
    ... would be great to have, but has high risk
    ... -----------------------------26999413214087432371486976730
    ... Content-Disposition: form-data; name="field.actions.continue"
    ...
    ... Continue
    ... -----------------------------26999413214087432371486976730--
    ... """.replace(
    ...             "\n", "\r\n"
    ...         )  # Necessary to ensure it fits the HTTP standard
    ...     )
    ... )  # noqa
    HTTP/1.1 303 See Other
    ...
    Content-Length: 0
    ...
    Location: http://.../firefox/+spec/svg-support
    ...


When we view that page, we see the targeted product series listed in the
header.

    >>> print(
    ...     http(
    ...         r"""
    ... GET /firefox/+spec/svg-support HTTP/1.1
    ... """
    ...     )
    ... )
    HTTP/1.1 200 Ok
    ...Proposed...
    ...firefox/1.0...


OK, we will also pitch the e4x spec to the same series:

    >>> print(
    ...     http(
    ...         r"""
    ... POST /firefox/+spec/e4x/+setproductseries HTTP/1.1
    ... Authorization: Basic celso.providelo@canonical.com:test
    ... Referer: https://launchpad.test/
    ... Content-Type: multipart/form-data; boundary=---------------------------26999413214087432371486976730
    ...
    ... -----------------------------26999413214087432371486976730
    ... Content-Disposition: form-data; name="field.productseries"
    ...
    ... 2
    ... -----------------------------26999413214087432371486976730
    ... Content-Disposition: form-data; name="field.productseries-empty-marker"
    ...
    ... 1
    ... -----------------------------26999413214087432371486976730
    ... Content-Disposition: form-data; name="field.whiteboard"
    ...
    ... would be great to have, but has high risk
    ... -----------------------------26999413214087432371486976730
    ... Content-Disposition: form-data; name="field.actions.continue"
    ...
    ... Continue
    ... -----------------------------26999413214087432371486976730--
    ... """.replace(
    ...             "\n", "\r\n"
    ...         )  # Necessary to ensure it fits the HTTP standard
    ...     )
    ... )  # noqa
    HTTP/1.1 303 See Other
    ...
    Content-Length: 0
    ...
    Location: http://.../firefox/+spec/e4x
    ...


And now both should show up on the "+setgoals" page for that product series.

    >>> print(
    ...     http(
    ...         r"""
    ... GET /firefox/1.0/+setgoals HTTP/1.1
    ... Authorization: Basic Zm9vLmJhckBjYW5vbmljYWwuY29tOnRlc3Q=
    ... """
    ...     )
    ... )
    HTTP/1.1 200 Ok
    ...Support Native SVG Objects...
    ...Support E4X in EcmaScript...


Now, we will accept one of them, the svg-support one. We expect to be told
that 1 was accepted.

    >>> driver_browser = setupBrowser(auth="Basic test@canonical.com:test")
    >>> driver_browser.open(
    ...     "http://blueprints.launchpad.test/firefox/1.0/+setgoals"
    ... )
    >>> "Support Native SVG" in driver_browser.contents
    True
    >>> driver_browser.getControl("Support Native SVG").selected = True
    >>> driver_browser.getControl("Accept").click()
    >>> "Accepted 1 specification(s)" in driver_browser.contents
    True


We will now decline the remaining one. We expect to be redirected, since
there are none left in the queue.

    >>> driver_browser.open(
    ...     "http://blueprints.launchpad.test/firefox/1.0/+setgoals"
    ... )
    >>> driver_browser.getControl("Support E4X").selected = True
    >>> driver_browser.getControl("Decline").click()
    >>> "Declined 1 specification(s)" in driver_browser.contents
    True

The accepted item should show up in the list of specs for this series:

    >>> print(
    ...     http(
    ...         r"""
    ... GET /firefox/1.0/+specs HTTP/1.1
    ... """
    ...     )
    ... )
    HTTP/1.1 200 Ok
    ...Support Native SVG Objects...


As a final check, we will show that there is that spec in the "Deferred"
listing.

    >>> print(
    ...     http(
    ...         r"""
    ... GET /firefox/1.0/+specs?acceptance=declined HTTP/1.1
    ... """
    ...     )
    ... )
    HTTP/1.1 200 Ok
    ...Support E4X in EcmaScript...


Now, lets make sure that automatic approval works. We will move the accepted
spec to the "trunk" series, where it will be automatically approved
because we are an admin, then we will move it back.

    >>> print(
    ...     http(
    ...         r"""
    ... POST /firefox/+spec/svg-support/+setproductseries HTTP/1.1
    ... Authorization: Basic Zm9vLmJhckBjYW5vbmljYWwuY29tOnRlc3Q=
    ... Referer: https://launchpad.test/
    ... Content-Type: multipart/form-data; boundary=---------------------------26999413214087432371486976730
    ...
    ... -----------------------------26999413214087432371486976730
    ... Content-Disposition: form-data; name="field.productseries"
    ...
    ... 1
    ... -----------------------------26999413214087432371486976730
    ... Content-Disposition: form-data; name="field.productseries-empty-marker"
    ...
    ... 1
    ... -----------------------------26999413214087432371486976730
    ... Content-Disposition: form-data; name="field.whiteboard"
    ...
    ... would be great to have, but has high risk
    ... -----------------------------26999413214087432371486976730
    ... Content-Disposition: form-data; name="field.actions.continue"
    ...
    ... Continue
    ... -----------------------------26999413214087432371486976730--
    ... """.replace(
    ...             "\n", "\r\n"
    ...         )  # Necessary to ensure it fits the HTTP standard
    ...     )
    ... )  # noqa
    HTTP/1.1 303 See Other
    ...
    Content-Length: 0
    ...
    Location: http://.../firefox/+spec/svg-support
    ...


OK, lets see if it was immediately accepted:

    >>> anon_browser.open("http://launchpad.test/firefox/+spec/svg-support")
    >>> "firefox/trunk" in anon_browser.contents
    True
    >>> "Accepted" in anon_browser.contents
    True

And lets put it back:

    >>> print(
    ...     http(
    ...         r"""
    ... POST /firefox/+spec/svg-support/+setproductseries HTTP/1.1
    ... Authorization: Basic Zm9vLmJhckBjYW5vbmljYWwuY29tOnRlc3Q=
    ... Referer: https://launchpad.test/
    ... Content-Type: multipart/form-data; boundary=---------------------------26999413214087432371486976730
    ...
    ... -----------------------------26999413214087432371486976730
    ... Content-Disposition: form-data; name="field.productseries"
    ...
    ... 2
    ... -----------------------------26999413214087432371486976730
    ... Content-Disposition: form-data; name="field.productseries-empty-marker"
    ...
    ... 1
    ... -----------------------------26999413214087432371486976730
    ... Content-Disposition: form-data; name="field.whiteboard"
    ...
    ... would be great to have, but has high risk
    ... -----------------------------26999413214087432371486976730
    ... Content-Disposition: form-data; name="field.actions.continue"
    ...
    ... Continue
    ... -----------------------------26999413214087432371486976730--
    ... """.replace(
    ...             "\n", "\r\n"
    ...         )  # Necessary to ensure it fits the HTTP standard
    ...     )
    ... )  # noqa
    HTTP/1.1 303 See Other
    ...
    Content-Length: 0
    ...
    Location: http://.../firefox/+spec/svg-support
    ...

And again, it should be accepted automatically.

    >>> anon_browser.open("http://launchpad.test/firefox/+spec/svg-support")
    >>> "firefox/1.0" in anon_browser.contents
    True
    >>> "Accepted" in anon_browser.contents
    True
