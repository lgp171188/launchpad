Answer Tracker Introduction Page
================================

First, we need to set some values for the later tests.

    >>> import transaction
    >>> from lp.app.enums import ServiceUsage
    >>> from lp.registry.interfaces.distribution import IDistributionSet
    >>> from lp.registry.interfaces.product import IProductSet
    >>> from zope.component import getUtility
    >>> login("admin@canonical.com")
    >>> firefox = getUtility(IProductSet).getByName("firefox")
    >>> ubuntu = getUtility(IDistributionSet).getByName("ubuntu")
    >>> firefox.answers_usage = ServiceUsage.LAUNCHPAD
    >>> ubuntu.answers_usage = ServiceUsage.LAUNCHPAD
    >>> logout()
    >>> transaction.commit()

    >>> anon_browser.open("http://answers.launchpad.test/")
    >>> print(anon_browser.title)
    Launchpad Answers

It shows the 5 latest questions asked:

    >>> latest_questions_asked = find_tag_by_id(
    ...     anon_browser.contents, "latest-questions-asked"
    ... )
    >>> print(latest_questions_asked.find("h2").decode_contents())
    Latest questions asked
    >>> for row in latest_questions_asked.find_all("li"):
    ...     print(row.find("a").decode_contents())
    ...
    13: Problemas de Impressão no Firefox
    12: Problema al recompilar kernel con soporte smp (doble-núcleo)
    11: Continue playing after shutdown
    5: Installation failed
    4: Firefox loses focus and gets stuck

As well as the 5 latest questions solved:

    >>> latest_questions_solved = find_tag_by_id(
    ...     anon_browser.contents, "latest-questions-solved"
    ... )
    >>> print(latest_questions_solved.find("h2").decode_contents())
    Latest questions solved
    >>> for row in latest_questions_solved.find_all("li"):
    ...     print(row.find("a").decode_contents())
    ...
    9: mailto: problem in webpage

The application footer also contains a sample of stats for the application:

    # Replace numbers with X in output.
    >>> import re
    >>> print(
    ...     re.sub(
    ...         r"\d+",
    ...         "X",
    ...         extract_text(
    ...             find_tag_by_id(
    ...                 anon_browser.contents, "application-footer"
    ...             )
    ...         ),
    ...     )
    ... )
    X questions answered and X questions solved out of
    X questions asked across X projects

The page also contains the projects actively using the Answer tracker.
(Since sample data contains no projects with a question asked in the
last 60 days, this list is empty):

    >>> print(
    ...     extract_text(
    ...         find_tag_by_id(anon_browser.contents, "most-active-projects")
    ...     )
    ... )
    Most active projects

Add some recent questions so that this listing contains something.

    >>> from lp.answers.testing import QuestionFactory
    >>> from lp.testing import login, logout
    >>> login("no-priv@canonical.com")
    >>> QuestionFactory.createManyByProject([("ubuntu", 2), ("firefox", 1)])
    >>> logout()

    >>> anon_browser.open("http://answers.launchpad.test/")
    >>> print(
    ...     extract_text(
    ...         find_tag_by_id(anon_browser.contents, "most-active-projects")
    ...     )
    ... )
    Most active projects
    Ubuntu
    Mozilla Firefox

Clicking on these project links will bring the user to the project
Answers front page:

    >>> anon_browser.getLink("Ubuntu").click()
    >>> print(anon_browser.url)
    http://answers.launchpad.test/ubuntu
    >>> print(anon_browser.title)
    Questions : Ubuntu
