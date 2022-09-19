Packaging
=========

Create test data.

    >>> from lp.soyuz.tests.test_publishing import SoyuzTestPublisher
    >>> test_publisher = SoyuzTestPublisher()
    >>> login("admin@canonical.com")
    >>> test_data = test_publisher.makeSourcePackageSummaryData()
    >>> test_publisher.updatePackageCache(test_data["distroseries"])
    >>> logout()

A person with permissions to edit packaging visits the distroseries upstream
links page for Hoary and sees that pmount is not linked.

    >>> browser = setupBrowser(auth="Basic limi@plone.org:test")
    >>> browser.open("http://launchpad.test/ubuntu/hoary/+needs-packaging")
    >>> print(extract_text(find_tag_by_id(browser.contents, "packages")))
    Source Package      Bugs    Translations
    pmount          No bugs     64 strings ...

They look at the pmount source package page in Hoary and read that the
upstream project is not set.

    >>> browser.getLink("pmount").click()
    >>> print(extract_text(find_tag_by_id(browser.contents, "no-upstreams")))
    Launchpad...
    There are no projects registered in Launchpad that are a potential
    match for this source package. Can you help us find one?
    Registered upstream project:
    Choose another upstream project
    Register the upstream project

The person knows that the pmount package comes from the thunderbird
project. They set the upstream packaging link and see that it is set.

    >>> browser.getControl("Choose another upstream project").selected = True
    >>> browser.getControl("Link to Upstream Project").click()
    >>> browser.getControl(name="field.product").value = "thunderbird"
    >>> browser.getControl("Continue").click()
    >>> browser.getControl(name="field.productseries").value = ["trunk"]
    >>> browser.getControl("Change").click()
    >>> print(extract_text(find_tag_by_id(browser.contents, "upstreams")))
    The Mozilla Project...Mozilla Thunderbird...trunk...

They see the "Show upstream links" link and take a look at the project's
packaging in distributions.

    >>> browser.getLink("Show upstream links").click()
    >>> print(
    ...     extract_text(
    ...         find_tag_by_id(browser.contents, "distribution-series")
    ...     )
    ... )
    Distribution series  Source package  Version  Project series
    Hoary (5.04)         pmount          0.1-2    Mozilla Thunderbird trunk...

The person returns to the pmount source package page, sees the
link to all versions and follows it to the distro source package page.

    >>> browser.getLink("pmount").click()
    >>> browser.getLink("All versions of pmount source in Ubuntu").click()
    >>> print(extract_text(find_tag_by_id(browser.contents, "packages_list")))
    The Hoary Hedgehog Release (active development) ...
      0.1-2  release (main) 2005-08-24


Register a project from a source package
----------------------------------------

The person can register a project for a package, and Launchpad
will use the data from the source package to prefill the first
step of the multistep form.

    >>> browser = setupBrowser(auth="Basic owner@youbuntu.com:test")

    >>> browser.open("http://launchpad.test/youbuntu/busy/+source/bonkers")
    >>> browser.getControl("Register the upstream project").selected = True
    >>> browser.getControl("Link to Upstream Project").click()
    >>> print(browser.getControl(name="field.name").value)
    bonkers
    >>> print(browser.getControl(name="field.display_name").value)
    Bonkers
    >>> print(browser.getControl(name="field.summary").value)
    summary for flubber-bin
    summary for flubber-lib
    >>> print(extract_text(find_tag_by_id(browser.contents, "step-title")))
    Step 2 (of 2): Check for duplicate projects

When the person selects "Choose another upstream project" and
then finds out that the project doesn't exist, they use the
"Link to Upstream Project" button to register the project.

    >>> browser.open("http://launchpad.test/youbuntu/busy/+source/bonkers/")
    >>> browser.getControl("Choose another upstream project").selected = True
    >>> browser.getControl("Link to Upstream Project").click()
    >>> print(browser.url)
    http://launchpad.test/youbuntu/busy/+source/bonkers/+edit-packaging

    >>> browser.getLink("Register the upstream project").click()
    >>> print(browser.getControl(name="field.name").value)
    bonkers
    >>> print(browser.getControl(name="field.display_name").value)
    Bonkers
    >>> print(browser.getControl(name="field.summary").value)
    summary for flubber-bin
    summary for flubber-lib
    >>> print(extract_text(find_tag_by_id(browser.contents, "step-title")))
    Step 2 (of 2): Check for duplicate projects

After the person selects the licences, the user is redirected back
to the source package page and an informational message will be displayed.

    >>> browser.getControl(name="field.licenses").value = ["BSD"]
    >>> browser.getControl(
    ...     "Complete registration and link to bonkers package"
    ... ).click()
    >>> print(browser.url)
    http://launchpad.test/youbuntu/busy/+source/bonkers
    >>> for tag in find_tags_by_class(
    ...     browser.contents, "informational message"
    ... ):
    ...     print(extract_text(tag))
    Linked Bonkers project to bonkers source package.
    >>> print(extract_text(find_tag_by_id(browser.contents, "upstreams")))
    Bonkers ⇒ trunk
    Change upstream link
    Remove upstream link...
