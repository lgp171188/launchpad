Distribution Source Packages
----------------------------

Source packages can be obtained from the context of a distribution.

    >>> from lazr.restful.testing.webservice import pprint_entry

    >>> debian = webservice.get("/debian").jsonBody()

    >>> mozilla_firefox = webservice.named_get(
    ...     debian["self_link"], "getSourcePackage", name="mozilla-firefox"
    ... ).jsonBody()

    >>> pprint_entry(mozilla_firefox)
    bug_reported_acknowledgement: None
    bug_reporting_guidelines: None
    display_name: 'mozilla-firefox in Debian'
    distribution_link: 'http://.../debian'
    content_templates: None
    name: 'mozilla-firefox'
    official_bug_tags: []
    resource_type_link: 'http://.../#distribution_source_package'
    self_link: 'http://.../debian/+source/mozilla-firefox'
    title: 'mozilla-firefox package in Debian'
    upstream_product_link: None
    web_link: 'http://launchpad.../debian/+source/mozilla-firefox'
    webhooks_collection_link: 'http.../debian/+source/mozilla-firefox/webhooks'

It's also possible to search for tasks with the "searchTasks" method:

    >>> bug_task_collection = webservice.named_get(
    ...     mozilla_firefox["self_link"], "searchTasks", status="New"
    ... ).jsonBody()

    >>> for bug_task in bug_task_collection["entries"]:
    ...     print(bug_task["title"])
    ...     print(
    ...         "%s, %s, <%s>"
    ...         % (
    ...             bug_task["status"],
    ...             bug_task["importance"],
    ...             bug_task["bug_link"],
    ...         )
    ...     )
    ...     print("<%s>" % bug_task["self_link"])
    ...
    Bug #3 in mozilla-firefox (Debian): "Bug Title Test"
    New, Unknown, <http://api.launchpad.test/beta/bugs/3>
    <http://api.launchpad.test/beta/debian/+source/mozilla-firefox/+bug/3>

If the package is linked to an upstream product in Launchpad you can
retrieve that product using the upstream_product_link of the source
package.

    >>> ubuntu = webservice.get("/ubuntu").jsonBody()
    >>> ubuntu_firefox = webservice.named_get(
    ...     ubuntu["self_link"], "getSourcePackage", name="mozilla-firefox"
    ... ).jsonBody()

    >>> upstream_product = webservice.get(
    ...     ubuntu_firefox["upstream_product_link"]
    ... ).jsonBody()

    >>> pprint_entry(upstream_product)
    active: True
    ...
    display_name: 'Mozilla Firefox'
    ...
    self_link: 'http://.../firefox'
    ...

If the package isn't linked to an upstream product its
upstream_product_link will be None.

    >>> print(mozilla_firefox["upstream_product_link"])
    None
