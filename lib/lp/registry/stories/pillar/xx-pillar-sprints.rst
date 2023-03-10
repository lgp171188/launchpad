Sprints relevant for pillars
============================

For Products, ProjectGroups and Distributions, we have a +sprints page which
lists all events relevant to that pillar.

    >>> from datetime import datetime, timedelta, timezone
    >>> import re
    >>> from zope.component import getUtility
    >>> from lp.registry.interfaces.distribution import IDistributionSet
    >>> from lp.registry.interfaces.product import IProductSet

    >>> def print_sprints(contents):
    ...     maincontent = find_tag_by_id(contents, "maincontent")
    ...     for link in maincontent.find_all("a"):
    ...         if re.search("/sprints/[a-z0-9]", link["href"]) is not None:
    ...             print(link.decode_contents())
    ...

    >>> login("test@canonical.com")
    >>> futurista = factory.makeSprint(
    ...     name="futurista",
    ...     title="Future Mega Meeting",
    ...     time_starts=datetime.now(timezone.utc) + timedelta(days=1),
    ... )
    >>> firefox = getUtility(IProductSet).getByName("firefox")
    >>> firefox_spec = firefox.specifications(futurista.owner)[0]
    >>> _ = firefox_spec.linkSprint(futurista, futurista.owner)
    >>> ubuntu = getUtility(IDistributionSet).getByName("ubuntu")
    >>> ubuntu_spec = ubuntu.specifications(futurista.owner)[0]
    >>> _ = ubuntu_spec.linkSprint(futurista, futurista.owner)
    >>> logout()

    >>> anon_browser.open("http://launchpad.test/firefox/+sprints")
    >>> print_sprints(anon_browser.contents)
    Future Mega Meeting
    Ubuntu Below Zero

    >>> anon_browser.open("http://launchpad.test/mozilla/+sprints")
    >>> print_sprints(anon_browser.contents)
    Future Mega Meeting
    Ubuntu Below Zero

    >>> anon_browser.open("http://launchpad.test/ubuntu/+sprints")
    >>> print_sprints(anon_browser.contents)
    Future Mega Meeting
