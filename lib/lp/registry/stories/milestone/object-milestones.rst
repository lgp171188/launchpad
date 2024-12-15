Milestones
==========


Utility function(s)
-------------------

We have a page which lists all the milestones for an object. This
function will print them out:

    >>> def all_milestones(browser):
    ...     table = find_main_content(browser.contents).find("tbody")
    ...     if table is None:
    ...         return None
    ...     result = []
    ...     for tr in table.find_all("tr"):
    ...         milestone_date = tr.find("span")
    ...         if len(milestone_date.contents) > 0:
    ...             # Just make sure we don't print an actual date.
    ...             milestone_date.contents[0].replace_with("A date")
    ...         result.append(extract_text(tr))
    ...     return "\n".join(result)
    ...

    >>> def milestones_in_portlet(browser):
    ...     portlet = find_portlet(browser.contents, "Active milestones")
    ...     if portlet is None:
    ...         return None
    ...     result = []
    ...     for tr in portlet.find("table").find_all("tr"):
    ...         result.append(
    ...             " ".join(text.strip() for text in tr.find_all(text=True))
    ...         )
    ...     return "\n".join(result)
    ...


Milestone listings
------------------

Products, distributions, product series, distribution series and
projects have a page in which all of their milestones are listed.


Distributions
.............

    >>> anon_browser.open("http://launchpad.test/debian/+milestones")
    >>> anon_browser.url
    'http://launchpad.test/debian/+milestones'

    >>> print(all_milestones(anon_browser))
    Debian 3.1      Woody ...
    Debian 3.1-rc1  Woody ...


Distribution Series
...................

    >>> anon_browser.open("http://launchpad.test/debian/woody/+milestones")
    >>> print(all_milestones(anon_browser))
    Debian 3.1      ...
    Debian 3.1-rc1  ...

    >>> anon_browser.open("http://launchpad.test/debian/sarge/+milestones")
    >>> print(all_milestones(anon_browser))
    None


Products
........

The Product "All milestones" page lists the milestones for all series,
including the inactive ones. They do not include the bug and blueprint
counts (because they are costly to retrieve).

    >>> anon_browser.open("http://launchpad.test/firefox/+milestones")
    >>> anon_browser.url
    'http://launchpad.test/firefox/+milestones'

    >>> print(all_milestones(anon_browser))
    Mozilla Firefox 1.0.0 "First Stable Release"    1.0    None        ...
    Mozilla Firefox 0.9.2 "One (secure) Tree Hill"  trunk  None        ...
    Mozilla Firefox 0.9.1 "One Tree Hill (v2)"      trunk  None        ...
    Mozilla Firefox 0.9   "One Tree Hill"           trunk  None        ...
    Mozilla Firefox 1.0                             trunk  A date
                                                              not yet released

When the project is a member of a project group, the user can see a
link to the project groups's milestone's page.

    >>> anon_browser.getLink(
    ...     "View milestones for The Mozilla Project"
    ... ).click()
    >>> print(anon_browser.title)
    Milestones : The Mozilla Project


Product Series
..............

    >>> anon_browser.open("http://launchpad.test/firefox/trunk/+milestones")
    >>> print(all_milestones(anon_browser))
    Mozilla Firefox 0.9.2  ...
    Mozilla Firefox 0.9.1  ...
    Mozilla Firefox 0.9    ...
    Mozilla Firefox 1.0    ...

    >>> anon_browser.open("http://launchpad.test/firefox/1.0/+milestones")
    >>> print(all_milestones(anon_browser))
    Mozilla Firefox 1.0.0 ...


Project groups
..............

The project group "All milestones" page lists all milestones for all
products and series, including the inactive ones. They do not include
the bug and blueprint counts (because they are costly to retrieve).

    >>> from lp.testing import login, logout
    >>> from lp.registry.tests.test_project_milestone import (
    ...     ProjectMilestoneTest,
    ... )
    >>> login("foo.bar@canonical.com")
    >>> test_helper = ProjectMilestoneTest(helper_only=True)
    >>> test_helper.setUpProjectMilestoneTests()
    >>> logout()
    >>> anon_browser.open("http://launchpad.test/gnome")
    >>> anon_browser.getLink("See all milestones").click()
    >>> print(all_milestones(anon_browser))
    GNOME 2.1.6  None        This is an inactive milestone
    GNOME 1.0    None        This is an inactive milestone
    GNOME 1.3    A date      This is an inactive milestone
    GNOME 1.2    A date      not yet released
    GNOME 1.1.   A date      not yet released
    GNOME 1.1    A date      not yet released


Individual milestones
---------------------

Pages for the individual milestones show all specifications and bugtasks
associated with that milestone for products of this project:

    >>> anon_browser.getLink("1.1", index=1).click()
    >>> print(anon_browser.title)
    1.1 : GNOME

    >>> specs = find_tag_by_id(anon_browser.contents, "milestone_specs")
    >>> print(extract_text(specs))
    Blueprint Project Priority Assignee Delivery
    Title evolution specification   Evolution  High  Unknown
    Title gnomebaker specification  gnomebaker High  Unknown

    >>> bugtasks = find_tag_by_id(anon_browser.contents, "milestone_bugtasks")
    >>> print(extract_text(bugtasks))
    Bug report Project Importance Assignee Status ...
    Milestone test bug for evolution  Evolution  Undecided Confirmed ...
    Milestone test bug for gnomebaker gnomebaker Undecided Confirmed ...
    Milestone test bug for evolution series trunk Undecided Confirmed

A project milestone page has the same navigation as the project:

    >>> anon_browser.open("http://launchpad.test/firefox/+milestone/1.0")
    >>> print(anon_browser.title)
    1.0 : Mozilla Firefox

    >>> print_location(anon_browser.contents)
    Hierarchy: Mozilla Firefox
    Tabs:
    * Overview (selected) - http://launchpad.test/firefox
    * Code - http://code.launchpad.test/firefox
    * Bugs - http://bugs.launchpad.test/firefox
    * Blueprints - http://blueprints.launchpad.test/firefox
    * Translations - http://translations.launchpad.test/firefox
    * Answers - http://answers.launchpad.test/firefox
    Main heading: Mozilla Firefox 1.0

Similarly, a distribution milestone page has the same navigation as the
distribution:

    >>> anon_browser.open("http://launchpad.test/debian/+milestone/3.1")
    >>> print(anon_browser.title)
    3.1 : Debian

    >>> print_location(anon_browser.contents)
    Hierarchy: Debian
    Tabs:
    * Overview (selected) - http://launchpad.test/debian
    * Code - http://code.launchpad.test/debian
    * Bugs - http://bugs.launchpad.test/debian
    * Blueprints - http://blueprints.launchpad.test/debian
    * Translations - http://translations.launchpad.test/debian
    * Answers - http://answers.launchpad.test/debian
    Main heading: Debian 3.1



Bugs targeted to multiple series
................................

Setup this embarrassing story.

    >>> browser = setupBrowser(auth="Basic test@canonical.com:test")
    >>> browser.open("http://bugs.launchpad.test/firefox/")
    >>> browser.getLink("Report a bug").click()
    >>> browser.getControl("Summary", index=0).value = "Test Bug 1"
    >>> browser.getControl("Continue").click()

    >>> report_bug_url = browser.url

    >>> browser.getControl("Bug Description").value = "Test Bug 1"
    >>> browser.getControl("Submit").click()
    >>> print_feedback_messages(browser.contents)
    Thank you for your bug report...

    >>> bug_1_url = browser.url
    >>> bug_1_id = bug_1_url.split("/")[-1]

    >>> browser.open(report_bug_url)
    >>> browser.getControl("Summary", index=0).value = "Test Bug 2"
    >>> browser.getControl("Continue").click()

    >>> browser.getControl("Bug Description").value = "Test Bug 2"
    >>> browser.getControl("Submit").click()
    >>> print_feedback_messages(browser.contents)
    Thank you for your bug report...

    >>> bug_2_url = browser.url
    >>> bug_2_id = bug_2_url.split("/")[-1]

Next, we'll target each bug to the 1.0 milestone:

    >>> browser.open(bug_1_url)
    >>> browser.getLink(url=bug_1_url + "/+editstatus").click()
    >>> control = browser.getControl("Milestone")
    >>> milestone_name = "1.0"
    >>> [milestone_id] = [
    ...     option.optionValue
    ...     for option in control.controls
    ...     if option.labels[0].endswith(milestone_name)
    ... ]
    >>> control.value = [milestone_id]
    >>> browser.getControl("Save Changes").click()

    >>> browser.open(bug_2_url)
    >>> browser.getLink(url=bug_2_url + "/+editstatus").click()
    >>> browser.getControl("Milestone").value = [milestone_id]
    >>> browser.getControl("Save Changes").click()

Bugs targeted to the same milestone across more than one series will
result in duplicate entries in the milestone listing (one for each
series target).

To demonstrate this, we'll begin by creating a new series "2.0" for the
Mozilla Firefox product, to complement the existing series "1.0":

    >>> browser.open("http://launchpad.test/firefox")
    >>> browser.getLink("Register a series").click()
    >>> print(browser.title)
    Register a new Mozilla Firefox release series...

    >>> browser.getControl("Name").value = "2.0"
    >>> browser.getControl("Summary").value = "The Firefox 2.0 Series"
    >>> browser.getControl("Register Series").click()
    >>> print(browser.title)
    Series 2.0 : Mozilla Firefox

We'll also create a new test milestone within the "trunk" series:

    >>> browser.open("http://launchpad.test/firefox/trunk")
    >>> print(browser.title)
    Series trunk : Mozilla Firefox

    >>> browser.getLink("Create milestone").click()
    >>> print(browser.title)
    Register a new milestone...

    >>> milestone = "test-milestone"
    >>> browser.getControl("Name").value = milestone
    >>> browser.getControl("Date Targeted").value = "2100-08-08"
    >>> browser.getControl("Register Milestone").click()
    >>> print(browser.title)
    Series trunk : Mozilla Firefox

    >>> browser.open("http://launchpad.test/firefox/trunk")

    >>> print(extract_text(find_tag_by_id(browser.contents, "series-trunk")))
    Version                         Expected    Released              Summary
    Mozilla Firefox 0.9.2...        Set date    Change details 2004-10-16  ...
    Mozilla Firefox...              Set date    Change details 2004-10-16  ...
    Mozilla Firefox test-milestone  2100-08-08  Release now ...

    >>> browser.getLink("test-milestone").click()
    >>> print(browser.title)
    test-milestone : Mozilla Firefox

    >>> milestone_url = browser.url

Let's target an existing bug to both series "1.0" and series "2.0":

    >>> from lp.services.helpers import backslashreplace
    >>> browser.open(bug_1_url)
    >>> print(backslashreplace(browser.title))
    Bug #...Test Bug 1... : Bugs : Mozilla Firefox

    >>> browser.getLink("Target to series").click()
    >>> print(browser.title)
    Target bug #... to series...

    >>> browser.getControl("1.0").selected = True
    >>> browser.getControl("2.0").selected = True
    >>> browser.getControl("Target").click()

The bug page now lists a bug task for each series:

    >>> print(extract_text(first_tag_by_class(browser.contents, "listing")))
    Affects Status Importance ...
    1.0 ... New    Undecided  ...
    2.0 ... New    Undecided  ...

Now we'll add each bug task to the same test milestone. Each bug task
has a link to an "edit status" form that can be used to choose the
milestone we're interested in. However, we need to be careful when
matching these links, as they may contain the same text as other links.
We'll use a specific URL pattern to avoid matching unrelated links.

Let's start with the first bug task:

    >>> import re
    >>> edit_status_url = re.compile(r".*/1.0/\+bug/[0-9]+/\+editstatus")
    >>> browser.getLink(url=edit_status_url).click()

Completing the "edit status" form allows us to add the bug task to the
milestone:

    >>> browser.getControl("Milestone").displayValue = [milestone]
    >>> browser.getControl("Importance").value = ["Critical"]
    >>> browser.getControl("Save Changes").click()

    >>> print(extract_text(first_tag_by_class(browser.contents, "listing")))
    Affects Status Importance ...
    1.0 ... New    Critical   ...

Now we'll add the second bug task to the test milestone, using the same
method. However this time we'll use a different importance:

    >>> edit_status_url = re.compile(r".*/2.0/\+bug/[0-9]+/\+editstatus")
    >>> browser.getLink(url=edit_status_url).click()
    >>> browser.getControl("Milestone").displayValue = [milestone]
    >>> browser.getControl("Importance").value = ["High"]
    >>> browser.getControl("Save Changes").click()

    >>> print(extract_text(first_tag_by_class(browser.contents, "listing")))
    Affects Status Importance ...
    2.0 ... New    High       ...

Observe that both bug tasks are now listed in the test milestone
listing:

    >>> browser.open(milestone_url)
    >>> bug_table = find_tag_by_id(browser.contents, "milestone_bugtasks")
    >>> print(extract_text(bug_table))
    Bug report       Importance  Assignee  Status
    #... Test Bug 1  Critical              New
    #... Test Bug 1  High                  New

Each bugtask has one or more badges.

    >>> print(bug_table.find_all("tr")[1])
    <tr>...Test Bug 1...<a...alt="milestone test-milestone"...
      class="sprite milestone"...>...


Bugs targeted to development focus series
.........................................

When a bug is raised for a product or distribution, it is implicitly
targeted to the development focus series for that product or
distribution ("trunk" by default).

Ordinarily, targeting a bug to a milestone causes the bug to appear in
that milestone's bug listing:

    >>> browser.open(bug_2_url)
    >>> browser.getLink(url=bug_2_url + "/+editstatus").click()
    >>> browser.getControl("Milestone").displayValue = [milestone]
    >>> browser.getControl("Save Changes").click()

    >>> browser.open(milestone_url)
    >>> print(
    ...     extract_text(
    ...         find_tag_by_id(browser.contents, "milestone_bugtasks")
    ...     )
    ... )
    Bug report...
    Test Bug 2...

When we explicitly target the bug to the development focus series, the
bug still appears in the milestone's bug listing:

    >>> browser.open(bug_2_url)
    >>> browser.getLink("Target to series").click()
    >>> print(browser.url)
    http://bugs.launchpad.test/firefox/+bug/.../+nominate

    >>> browser.getControl("Trunk").selected = True
    >>> browser.getControl("Target").click()
    >>> print(extract_text(first_tag_by_class(browser.contents, "listing")))
    Affects             Status                  ...
    Mozilla Firefox ... Status tracked in Trunk ...

    >>> browser.open(milestone_url)
    >>> bugtasks = extract_text(
    ...     find_tag_by_id(browser.contents, "milestone_bugtasks")
    ... )
    >>> print(bugtasks)
    Bug report...
    Test Bug 2...

Moreover, the bug appears only once in the listing:

    >>> print(bugtasks.count("Test Bug 2"))
    1


