==========================
Web Service Project Groups
==========================


Project group collection
------------------------

It is possible to get a batched list of all the project groups.

    >>> group_collection = webservice.get("/projectgroups").jsonBody()
    >>> print(group_collection["resource_type_link"])
    http://.../#project_groups

    >>> group_collection["total_size"]
    7

    >>> from operator import itemgetter
    >>> project_group_entries = sorted(
    ...     group_collection["entries"], key=itemgetter("name")
    ... )
    >>> print(project_group_entries[0]["self_link"])
    http://.../apache

    >>> for project_group in project_group_entries:
    ...     print(project_group["display_name"])
    ...
    Apache
    ...
    GNOME
    ...
    The Mozilla Project

It's possible to search the list and get a subset of the project groups.

    >>> group_collection = webservice.named_get(
    ...     "/projectgroups", "search", text="Apache"
    ... ).jsonBody()
    >>> for project_group in group_collection["entries"]:
    ...     print(project_group["display_name"])
    ...
    Apache

Searching without providing a search string is the same as getting all
the project groups.

    >>> group_collection = webservice.named_get(
    ...     "/projectgroups", "search"
    ... ).jsonBody()
    >>> project_group_entries = sorted(
    ...     group_collection["entries"], key=itemgetter("name")
    ... )
    >>> for project_group in project_group_entries:
    ...     print(project_group["display_name"])
    ...
    Apache
    ...
    GNOME
    ...
    The Mozilla Project


Project group entry
-------------------

Project groups are available at their canonical URL on the API virtual
host.

    >>> from lazr.restful.testing.webservice import (
    ...     pprint_collection,
    ...     pprint_entry,
    ... )

    >>> mozilla = webservice.get("/mozilla").jsonBody()
    >>> pprint_entry(mozilla)
    active: True
    active_milestones_collection_link: 'http://.../mozilla/active_milestones'
    all_milestones_collection_link: 'http://.../mozilla/all_milestones'
    bug_reported_acknowledgement: None
    bug_reporting_guidelines: None
    bug_tracker_link: None
    content_templates: None
    date_created: '...'
    description: 'The Mozilla Project...'
    display_name: 'The Mozilla Project'
    driver_link: None
    freshmeat_project: None
    homepage_content: None
    homepage_url: 'http://www.mozilla.org/'
    icon_link: 'http://.../mozilla/icon'
    logo_link: 'http://.../mozilla/logo'
    mugshot_link: 'http://.../mozilla/mugshot'
    name: 'mozilla'
    official_bug_tags: []
    owner_link: 'http://.../~name12'
    projects_collection_link: 'http://.../mozilla/projects'
    registrant_link: 'http://.../~name12'
    resource_type_link: '...'
    reviewed: False
    self_link: 'http://.../mozilla'
    sourceforge_project: None
    summary: 'The Mozilla Project...'
    title: 'The Mozilla Project'
    web_link: 'http://launchpad.../mozilla'
    wiki_url: None

The milestones can be accessed through the
active_milestones_collection_link and the
all_milestones_collection_link.

    >>> response = webservice.get(
    ...     mozilla["active_milestones_collection_link"]
    ... )
    >>> active_milestones = response.jsonBody()
    >>> print_self_link_of_entries(active_milestones)
    http://.../mozilla/+milestone/1.0

    >>> response = webservice.get(mozilla["all_milestones_collection_link"])
    >>> all_milestones = response.jsonBody()
    >>> print_self_link_of_entries(all_milestones)
    http://.../mozilla/+milestone/0.8
    http://.../mozilla/+milestone/0.9
    http://.../mozilla/+milestone/0.9.1
    http://.../mozilla/+milestone/0.9.2
    http://.../mozilla/+milestone/1.0.0

The milestones can also be accessed anonymously.

    >>> response = anon_webservice.get(
    ...     mozilla["active_milestones_collection_link"]
    ... )
    >>> active_milestones = response.jsonBody()
    >>> print_self_link_of_entries(active_milestones)
    http://.../mozilla/+milestone/1.0

    >>> response = anon_webservice.get(
    ...     mozilla["all_milestones_collection_link"]
    ... )
    >>> all_milestones = response.jsonBody()
    >>> print_self_link_of_entries(all_milestones)
    http://.../mozilla/+milestone/0.8
    http://.../mozilla/+milestone/0.9
    http://.../mozilla/+milestone/0.9.1
    http://.../mozilla/+milestone/0.9.2
    http://.../mozilla/+milestone/1.0.0

"getMilestone" returns a milestone for the given name, or None if there
is no milestone for the given name.

    >>> milestone_1_0 = webservice.named_get(
    ...     mozilla["self_link"], "getMilestone", name="1.0"
    ... ).jsonBody()
    >>> print(milestone_1_0["self_link"])
    http://.../mozilla/+milestone/1.0

    >>> print(
    ...     webservice.named_get(
    ...         mozilla["self_link"], "getMilestone", name="fnord"
    ...     ).jsonBody()
    ... )
    None


Project entry
-------------

Projects are available at their canonical URL on the API virtual host.

    >>> firefox = webservice.get("/firefox").jsonBody()
    >>> pprint_entry(firefox)
    active: True
    active_milestones_collection_link: 'http://.../firefox/active_milestones'
    all_milestones_collection_link: 'http://.../firefox/all_milestones'
    brand_link: 'http://.../firefox/brand'
    bug_reported_acknowledgement: None
    bug_reporting_guidelines: None
    bug_supervisor_link: None
    bug_tracker_link: None
    commercial_subscription_is_due: False
    commercial_subscription_link: None
    content_templates: None
    date_created: '2004-09-24T20:58:02.185708+00:00'
    date_next_suggest_packaging: None
    description: 'The Mozilla Firefox web browser'
    development_focus_link: 'http://.../firefox/trunk'
    display_name: 'Mozilla Firefox'
    download_url: None
    driver_link: None
    freshmeat_project: None
    homepage_url: None
    icon_link: 'http://.../firefox/icon'
    information_type: 'Public'
    is_permitted: True
    license_approved: False
    license_info: None
    licenses: ['MIT / X / Expat Licence']
    logo_link: 'http://.../firefox/logo'
    name: 'firefox'
    official_answers: True
    official_blueprints: False
    official_bug_tags: []
    official_bugs: True
    official_codehosting: False
    owner_link: 'http://.../~name12'
    private: False
    private_bugs: False
    programming_language: None
    project_group_link: 'http://.../mozilla'
    project_reviewed: False
    qualifies_for_free_hosting: True
    recipes_collection_link: 'http://.../firefox/recipes'
    registrant_link: 'http://.../~name12'
    releases_collection_link: 'http://.../firefox/releases'
    remote_product: None
    resource_type_link: 'http://.../#project'
    reviewer_whiteboard: None
    screenshots_url: None
    self_link: 'http://.../firefox'
    series_collection_link: 'http://.../firefox/series'
    sourceforge_project: None
    summary: 'The Mozilla Firefox web browser'
    title: 'Mozilla Firefox'
    translation_focus_link: None
    vcs: None
    web_link: 'http://launchpad.../firefox'
    webhooks_collection_link: 'http://api.launchpad.../firefox/webhooks'
    wiki_url: None

In Launchpad project names may not have uppercase letters in their
name.  As a convenience, requests for projects using the wrong case
are redirected to the correct location.

    >>> print(webservice.get("/FireFox"))
    HTTP/1.1 301 Moved Permanently
    ...
    Location: http://api.launchpad.test/beta/firefox
    ...

Some entries for projects are only available to admins.  Here we see
several that are not available to non-privileged users marked as
'redacted'.

    >>> firefox = user_webservice.get("/firefox").jsonBody()
    >>> pprint_entry(firefox)
    active: True
    ...
    is_permitted:...redacted...
    license_approved:...redacted...
    ...
    project_reviewed:...redacted...
    ...
    reviewer_whiteboard:...redacted...
    ...

The milestones can be accessed through the
active_milestones_collection_link and the
all_milestones_collection_link.

    >>> response = webservice.get(
    ...     firefox["active_milestones_collection_link"]
    ... )
    >>> active_milestones = response.jsonBody()
    >>> print_self_link_of_entries(active_milestones)
    http://.../firefox/+milestone/1.0

    >>> response = webservice.get(firefox["all_milestones_collection_link"])
    >>> all_milestones = response.jsonBody()
    >>> print_self_link_of_entries(all_milestones)
    http://.../firefox/+milestone/0.9
    http://.../firefox/+milestone/0.9.1
    http://.../firefox/+milestone/0.9.2
    http://.../firefox/+milestone/1.0
    http://.../firefox/+milestone/1.0.0

"getMilestone" returns a milestone for the given name, or None if there
is no milestone for the given name.

    >>> milestone_1_0 = webservice.named_get(
    ...     firefox["self_link"], "getMilestone", name="1.0"
    ... ).jsonBody()
    >>> print(milestone_1_0["self_link"])
    http://.../firefox/+milestone/1.0

    >>> print(
    ...     webservice.named_get(
    ...         firefox["self_link"], "getMilestone", name="fnord"
    ...     ).jsonBody()
    ... )
    None

The project group can be accessed through the project_group_link.

    >>> print(
    ...     webservice.get(firefox["project_group_link"]).jsonBody()[
    ...         "self_link"
    ...     ]
    ... )
    http://.../mozilla

A list of series can be accessed through the series_collection_link.

    >>> response = webservice.get(firefox["series_collection_link"])
    >>> series = response.jsonBody()
    >>> print(series["total_size"])
    2

    >>> print_self_link_of_entries(series)
    http://.../firefox/1.0
    http://.../firefox/trunk

"getSeries" returns the series for the given name.

    >>> series_1_0 = webservice.named_get(
    ...     firefox["self_link"], "getSeries", name="1.0"
    ... ).jsonBody()
    >>> print(series_1_0["self_link"])
    http://.../firefox/1.0

Series can also be accessed anonymously.

    >>> response = anon_webservice.get(firefox["series_collection_link"])
    >>> series = response.jsonBody()
    >>> print(series["total_size"])
    2

"newSeries" permits the creation of new series.

    >>> experimental_new_series = webservice.named_post(
    ...     firefox["self_link"],
    ...     "newSeries",
    ...     name="experimental",
    ...     summary="An experimental new series.",
    ... )
    >>> print(experimental_new_series)
    HTTP/1.1 201 Created
    ...
    Location: http://.../firefox/experimental
    ...

A list of releases can be accessed through the releases_collection_link.

    >>> response = webservice.get(firefox["releases_collection_link"])
    >>> releases = response.jsonBody()
    >>> print(releases["total_size"])
    4

    >>> print_self_link_of_entries(releases)
    http://.../firefox/1.0/1.0.0
    http://.../firefox/trunk/0.9
    http://.../firefox/trunk/0.9.1
    http://.../firefox/trunk/0.9.2

"getRelease" returns the release for the given version.

    >>> release_0_9_1 = webservice.named_get(
    ...     firefox["self_link"], "getRelease", version="0.9.1"
    ... ).jsonBody()
    >>> print(release_0_9_1["self_link"])
    http://.../firefox/trunk/0.9.1

Releases can also be accessed anonymously.

    >>> response = anon_webservice.get(firefox["releases_collection_link"])
    >>> releases = response.jsonBody()
    >>> print(releases["total_size"])
    4

The development focus series can be accessed through the
development_focus_link.

    >>> response = webservice.get(firefox["development_focus_link"])
    >>> print(response.jsonBody()["self_link"])
    http://.../firefox/trunk

Attributes can be edited via the webservice.patch() method.

    >>> import json
    >>> patch = {
    ...     "driver_link": webservice.getAbsoluteUrl("/~mark"),
    ...     "homepage_url": "http://sf.net/firefox",
    ...     "licenses": ["Python Licence", "GNU GPL v2"],
    ...     "bug_tracker_link": webservice.getAbsoluteUrl(
    ...         "/bugs/bugtrackers/mozilla.org"
    ...     ),
    ... }
    >>> print(
    ...     webservice.patch(
    ...         "/firefox", "application/json", json.dumps(patch)
    ...     )
    ... )
    HTTP/1.1 209 Content Returned
    ...

    >>> firefox = webservice.get("/firefox").jsonBody()
    >>> print(firefox["driver_link"])
    http://.../~mark

    >>> print(firefox["homepage_url"])
    http://sf.net/firefox

    >>> print(webservice.get(firefox["driver_link"]).jsonBody()["self_link"])
    http://.../~mark

    >>> print(webservice.get(firefox["owner_link"]).jsonBody()["self_link"])
    http://.../~name12

    >>> print(
    ...     webservice.get(firefox["bug_tracker_link"]).jsonBody()[
    ...         "self_link"
    ...     ]
    ... )
    http://.../bugs/bugtrackers/mozilla.org

When the owner_link is changed the ownership of some attributes is
changed as well.

    >>> login("test@canonical.com")
    >>> test_project_owner = factory.makePerson(name="test-project-owner")
    >>> test_project = factory.makeProduct(
    ...     name="test-project", owner=test_project_owner
    ... )
    >>> test_series = factory.makeProductSeries(
    ...     product=test_project, name="test-series", owner=test_project_owner
    ... )
    >>> test_milestone = factory.makeMilestone(
    ...     product=test_project,
    ...     name="test-milestone",
    ...     productseries=test_series,
    ... )
    >>> test_project_release = factory.makeProductRelease(
    ...     product=test_project, milestone=test_milestone
    ... )
    >>> logout()

    >>> test_project = webservice.get("/test-project").jsonBody()
    >>> print(test_project["owner_link"])
    http://.../~test-project-owner

    >>> patch = {
    ...     "owner_link": webservice.getAbsoluteUrl("/~mark"),
    ... }
    >>> print(
    ...     webservice.patch(
    ...         "/test-project", "application/json", json.dumps(patch)
    ...     )
    ... )
    HTTP/1.1 209 Content Returned
    ...

    >>> test_project = webservice.get("/test-project").jsonBody()
    >>> print(test_project["owner_link"])
    http://.../~mark

Read-only attributes, like registrant, cannot be modified via the
webservice.patch() method.

    >>> patch = {
    ...     "registrant_link": webservice.getAbsoluteUrl("/~mark"),
    ... }
    >>> print(
    ...     webservice.patch(
    ...         "/firefox", "application/json", json.dumps(patch)
    ...     )
    ... )
    HTTP/1.1 400 Bad Request
    ...
    registrant_link: You tried to modify a read-only attribute.

    >>> firefox = webservice.get("/firefox").jsonBody()
    >>> print(firefox["registrant_link"])
    http://.../~name12

Similarly the date_created attribute cannot be modified.

    >>> original_date_created = firefox["date_created"]
    >>> patch = {"date_created": "2000-01-01T01:01:01+00:00Z"}
    >>> print(
    ...     webservice.patch(
    ...         "/firefox", "application/json", json.dumps(patch)
    ...     )
    ... )
    HTTP/1.1 400 Bad Request
    ...
    date_created: You tried to modify a read-only attribute.

    >>> firefox = webservice.get("/firefox").jsonBody()
    >>> firefox["date_created"] == original_date_created
    True

"get_timeline" returns a lightweight representation of the project's
hierarchy of series, milestones, and releases.

    >>> patch = {"status": "Obsolete"}
    >>> print(
    ...     webservice.patch(
    ...         "/firefox/trunk", "application/json", json.dumps(patch)
    ...     )
    ... )
    HTTP/1.1 209 Content Returned...
    >>> timeline = webservice.named_get(
    ...     firefox["self_link"], "get_timeline", include_inactive=True
    ... ).jsonBody()
    >>> pprint_collection(timeline)
    start: 0
    total_size: 3
    ---
    is_development_focus: True
    landmarks: [{'code_name': None,
                 'date': '2056-10-16',
                 'name': '1.0',
                 'type': 'milestone',
                 'uri': '/firefox/+milestone/1.0'},
                {'code_name': 'One (secure) Tree Hill',
                 'date': '2004-10-15',
                 'name': '0.9.2',
                 'type': 'release',
                 'uri': '/firefox/trunk/0.9.2'},
                {'code_name': 'One Tree Hill (v2)',
                 'date': '2004-10-15',
                 'name': '0.9.1',
                 'type': 'release',
                 'uri': '/firefox/trunk/0.9.1'},
                {'code_name': 'One Tree Hill',
                 'date': '2004-10-15',
                 'name': '0.9',
                 'type': 'release',
                 'uri': '/firefox/trunk/0.9'}]
    name: 'trunk'
    project_link: 'http://.../firefox'
    resource_type_link: '.../#timeline_project_series'
    self_link: 'http://.../firefox/trunk'
    status: 'Obsolete'
    uri: '/firefox/trunk'
    web_link: 'http://launchpad.../firefox/trunk'
    ---
    is_development_focus: False
    landmarks: [{'code_name': 'First Stable Release',
                 'date': '2004-06-28',
                 'name': '1.0.0',
                 'type': 'release',
                 'uri': '/firefox/1.0/1.0.0'}]
    name: '1.0'
    project_link: 'http://.../firefox'
    resource_type_link: '.../#timeline_project_series'
    self_link: 'http://.../firefox/1.0'
    status: 'Active Development'
    uri: '/firefox/1.0'
    web_link: 'http://launchpad.../firefox/1.0'
    ---
    is_development_focus: False
    landmarks: []
    name: 'experimental'
    project_link: 'http://.../firefox'
    resource_type_link: '.../#timeline_project_series'
    self_link: 'http://.../firefox/experimental'
    status: 'Active Development'
    uri: '/firefox/experimental'
    web_link: 'http://launchpad.../firefox/experimental'
    ---


Project collection
------------------

It is possible to get a batched list of all the projects.

    >>> project_collection = webservice.get("/projects").jsonBody()
    >>> print(project_collection["resource_type_link"])
    http://.../#projects

The entire collection has 24 entries.

    >>> project_collection["total_size"]
    24

It's possible to search the list and get a subset of the project groups.

    >>> project_collection = webservice.named_get(
    ...     "/projects", "search", text="Apache"
    ... ).jsonBody()
    >>> projects = [
    ...     project["display_name"]
    ...     for project in project_collection["entries"]
    ... ]
    >>> for project_name in sorted(projects):
    ...     print(project_name)
    ...
    Derby
    Tomcat

If you don't specify "text" to the search a batched list of all the
projects is returned.

    >>> project_collection = webservice.named_get(
    ...     "/projects", "search"
    ... ).jsonBody()
    >>> len(project_collection["entries"])
    5

It is also possible to search for projects by a text string by adding
the ws.op=search parameter.

    >>> project_collection = webservice.get(
    ...     "/projects?ws.op=search&text=gnome"
    ... ).jsonBody()
    >>> project_collection["total_size"]
    4

The latest projects registered can be retrieved.

    >>> latest = webservice.named_get("/projects", "latest").jsonBody()
    >>> entries = sorted(latest["entries"], key=itemgetter("display_name"))
    >>> for project in entries:
    ...     print(project["display_name"])
    ...
    Derby
    Mega Money Maker
    Obsolete Junk
    Redfish
    Test-project

There is a method for doing a query about attributes related to project
licensing.  We can find all projects with unreviewed licenses.

    >>> unreviewed = webservice.named_get(
    ...     "/projects", "licensing_search", project_reviewed=False
    ... ).jsonBody()

    >>> entries = sorted(
    ...     unreviewed["entries"], key=itemgetter("display_name")
    ... )
    >>> for project in entries:
    ...     print(project["display_name"])
    ...
    Arch mirrors ...

The project collection has a method for creating a new project.

    >>> def create_project(
    ...     name,
    ...     display_name,
    ...     title,
    ...     summary,
    ...     description=None,
    ...     project_group=None,
    ...     homepage_url=None,
    ...     screenshots_url=None,
    ...     wiki_url=None,
    ...     download_url=None,
    ...     freshmeat_project=None,
    ...     sourceforge_project=None,
    ...     programming_lang=None,
    ...     licenses=(),
    ...     license_info=None,
    ...     project_reviewed=False,
    ...     registrant=None,
    ... ):
    ...     return webservice.named_post(
    ...         "/projects",
    ...         "new_project",
    ...         name=name,
    ...         display_name=display_name,
    ...         title=title,
    ...         summary=summary,
    ...         description=description,
    ...         project_group=project_group,
    ...         homepage_url=homepage_url,
    ...         screenshots_url=screenshots_url,
    ...         wiki_url=wiki_url,
    ...         download_url=download_url,
    ...         freshmeat_project=freshmeat_project,
    ...         sourceforge_project=sourceforge_project,
    ...         programming_lang=programming_lang,
    ...         licenses=licenses,
    ...         license_info=license_info,
    ...         project_reviewed=project_reviewed,
    ...         registrant=registrant,
    ...     )

Verify a project does not exist and then create it.

    >>> print(webservice.get("/my-new-project"))
    HTTP/1.1 404 Not Found
    ...

    >>> print(
    ...     create_project(
    ...         "my-new-project",
    ...         "My New Project",
    ...         "My New Project",
    ...         "My Shiny New Project",
    ...         licenses=["Zope Public Licence", "GNU GPL v2"],
    ...         wiki_url="http://example.com/shiny",
    ...     )
    ... )
    HTTP/1.1 201 Created
    ...
    Location: http://.../my-new-project
    ...

    >>> print(webservice.get("/my-new-project"))
    HTTP/1.1 200 Ok
    ...

    >>> new_project = webservice.get("/my-new-project").jsonBody()
    >>> print(new_project["name"])
    my-new-project

    >>> print(new_project["display_name"])
    My New Project

    >>> print(new_project["summary"])
    My Shiny New Project

    >>> for license in sorted(new_project["licenses"]):
    ...     print(license)
    ...
    GNU GPL v2
    Zope Public Licence

    >>> print(new_project["project_reviewed"])
    False

    >>> print(new_project["homepage_url"])
    None

Attempting to create a project with a name that has already been used is
an error.

    >>> print(
    ...     create_project(
    ...         "my-new-project",
    ...         "My New Project",
    ...         "My New Project",
    ...         "My Shiny New Project",
    ...     )
    ... )
    HTTP/1.1 400 Bad Request
    ...
    name: my-new-project is already used by another project

If the fields do not validate a Bad Request error is received.  Here the
URL is not properly formed. Due to bug #1088358 the error is escaped as
if it was HTML.

    >>> print(
    ...     create_project(
    ...         "my-new-project",
    ...         "My New Project",
    ...         "My New Project",
    ...         "My Shiny New Project",
    ...         wiki_url="htp://badurl.example.com",
    ...     )
    ... )
    HTTP/1.1 400 Bad Request
    ...
    wiki_url: The URI scheme &quot;htp&quot; is not allowed.  Only URIs
    with the following schemes may be used: ftp, http, https


The pillar set
--------------

A few features are common to projects, project groups, and
distributions. We call all three "pillars", and publish the common
functionality at an object called the pillar set.

    >>> pillar_set = webservice.get("/pillars").jsonBody()
    >>> pprint_entry(pillar_set)
    featured_pillars_collection_link: 'http://.../pillars/featured_pillars'
    resource_type_link: '...'
    self_link: '...'

The featured pillars are available as a separate collection. Because
they're of different resource types, the best way to compare them is by
comparing the self_link, which every resource has.

    >>> featured_link = pillar_set["featured_pillars_collection_link"]
    >>> featured_pillars = webservice.get(featured_link).jsonBody()
    >>> featured_pillars["total_size"]
    9

    >>> featured_entries = sorted(
    ...     featured_pillars["entries"], key=itemgetter("self_link")
    ... )
    >>> for pillar in featured_entries:
    ...     print(pillar["self_link"])
    ...
    http://.../applets
    http://.../bazaar
    ...
    http://.../gnome

    >>> search_result = webservice.named_get(
    ...     "/pillars", "search", text="bazaar"
    ... ).jsonBody()
    >>> found_entries = sorted(
    ...     search_result["entries"], key=itemgetter("self_link")
    ... )
    >>> for pillar in found_entries:
    ...     print(pillar["self_link"])
    ...
    http://.../bazaar
    http://.../bzr
    http://.../launchpad

    >>> search_result = webservice.named_get(
    ...     "/pillars", "search", text="bazaar", limit="1"
    ... ).jsonBody()
    >>> for pillar in search_result["entries"]:
    ...     print(pillar["self_link"])
    ...
    http://.../bazaar


Project series entry
--------------------

The entry for a project series is available at its canonical URL on the
virtual host.

    >>> from zope.security.proxy import removeSecurityProxy
    >>> login("test@canonical.com")
    >>> babadoo_owner = factory.makePerson(name="babadoo-owner")
    >>> babadoo = factory.makeProduct(name="babadoo", owner=babadoo_owner)
    >>> foobadoo = factory.makeProductSeries(
    ...     product=babadoo, name="foobadoo", owner=babadoo_owner
    ... )
    >>> removeSecurityProxy(foobadoo).summary = "Foobadoo support for Babadoo"
    >>> fooey = factory.makeAnyBranch(
    ...     product=babadoo, name="fooey", owner=babadoo_owner
    ... )
    >>> removeSecurityProxy(foobadoo).branch = fooey
    >>> logout()

    >>> babadoo_foobadoo = webservice.get("/babadoo/foobadoo").jsonBody()
    >>> pprint_entry(babadoo_foobadoo)
    active: True
    active_milestones_collection_link:
            'http://.../babadoo/foobadoo/active_milestones'
    all_milestones_collection_link:
            'http://.../babadoo/foobadoo/all_milestones'
    branch_link: 'http://.../~babadoo-owner/babadoo/fooey'
    bug_reported_acknowledgement: None
    bug_reporting_guidelines: None
    content_templates: None
    date_created: '...'
    display_name: 'foobadoo'
    driver_link: None
    drivers_collection_link: 'http://.../babadoo/foobadoo/drivers'
    name: 'foobadoo'
    official_bug_tags: []
    owner_link: 'http://.../~babadoo-owner'
    project_link: 'http://.../babadoo'
    release_finder_url_pattern: None
    releases_collection_link: 'http://.../babadoo/foobadoo/releases'
    resource_type_link: '...'
    self_link: 'http://.../babadoo/foobadoo'
    status: 'Active Development'
    summary: 'Foobadoo support for Babadoo'
    title: 'Babadoo foobadoo series'
    web_link: 'http://launchpad.../babadoo/foobadoo'

"get_timeline" returns a lightweight representation of the series'
milestones and releases.

    >>> timeline = webservice.named_get(
    ...     babadoo_foobadoo["self_link"], "get_timeline"
    ... ).jsonBody()
    >>> pprint_entry(timeline)
    is_development_focus: False
    landmarks: []
    name: 'foobadoo'
    project_link: 'http://.../babadoo'
    resource_type_link: 'http://.../#timeline_project_series'
    self_link: 'http://.../babadoo/foobadoo'
    status: 'Active Development'
    uri: '/babadoo/foobadoo'
    web_link: 'http://launchpad.../babadoo/foobadoo'


Creating a milestone on the product series
==========================================

The newMilstone method is called by sending "ws.op=newMilestone" as a
request variable along with the parameters. The webservice.named_post()
method simplifies this for us.

    >>> firefox_1_0 = webservice.get("/firefox/1.0").jsonBody()
    >>> response = webservice.named_post(
    ...     firefox_1_0["self_link"],
    ...     "newMilestone",
    ...     {},
    ...     name="alpha1",
    ...     code_name="Elmer",
    ...     date_targeted="2005-06-06",
    ...     summary="Feature complete but buggy.",
    ... )
    >>> print(response)
    HTTP/1.1 201 Created
    ...
    Location: http://.../firefox/+milestone/alpha1
    ...

    >>> milestone = webservice.get(response.getHeader("Location")).jsonBody()
    >>> print(milestone["name"])
    alpha1

    >>> print(milestone["code_name"])
    Elmer

    >>> print(milestone["date_targeted"])
    2005-06-06

    >>> print(milestone["summary"])
    Feature complete but buggy.

The milestone name must be unique on the product series.

    >>> print(
    ...     webservice.named_post(
    ...         firefox_1_0["self_link"],
    ...         "newMilestone",
    ...         {},
    ...         name="alpha1",
    ...         dateexpected="157.0",
    ...         summary="Feature complete but buggy.",
    ...     )
    ... )
    HTTP/1.1 400 Bad Request
    ...
    name: The name alpha1 is already used by a milestone in Mozilla Firefox.

The milestone name can only contain letters, numbers, "-", "+", and ".".

    >>> print(
    ...     webservice.named_post(
    ...         firefox_1_0["self_link"],
    ...         "newMilestone",
    ...         {},
    ...         name="!@#$%^&*()",
    ...         dateexpected="157.0",
    ...         summary="Feature complete but buggy.",
    ...     )
    ... )
    HTTP/1.1 400 Bad Request
    ...
    Invalid name...

Invalid data will return a Bad Request error.

    >>> response = webservice.named_post(
    ...     firefox_1_0["self_link"],
    ...     "newMilestone",
    ...     {},
    ...     name="buggy",
    ...     date_targeted="2005-10-36",
    ...     code_name="Samurai Monkey",
    ...     summary="Very buggy.",
    ... )
    >>> print(response)
    HTTP/1.1 400 Bad Request
    ...
    date_targeted: Value doesn't look like a date.


Project release
===============

Project releases are available at their canonical URL on the API virtual
host.

    >>> firefox_1_0_0 = webservice.get("/firefox/1.0/1.0.0").jsonBody()
    >>> pprint_entry(firefox_1_0_0)
    changelog: ''
    date_created: '2005-06-06T08:59:51.930201+00:00'
    date_released: '2004-06-28T00:00:00+00:00'
    display_name: 'Mozilla Firefox 1.0.0'
    files_collection_link: 'http://.../firefox/1.0/1.0.0/files'
    milestone_link: 'http://.../firefox/+milestone/1.0.0'
    owner_link: 'http://.../~name12'
    project_link: 'http://.../firefox'
    release_notes: '...'
    resource_type_link: '...'
    self_link: 'http://.../firefox/1.0/1.0.0'
    title: 'Mozilla Firefox 1.0.0 "First Stable Release"'
    version: '1.0.0'
    web_link: 'http://launchpad.../firefox/1.0/1.0.0'

The createProductRelease method is called by sending
"ws.op=createProductRelease" as a request variable along with the
parameters.  The webservice.named_post() method simplifies this for us.

    >>> response = webservice.named_post(
    ...     milestone["self_link"],
    ...     "createProductRelease",
    ...     {},
    ...     date_released="2000-01-01T01:01:01+00:00Z",
    ...     release_notes="New stuff",
    ...     changelog="Added 5,000 features.",
    ... )
    >>> print(response)
    HTTP/1.1 201 Created
    ...
    Location: http://.../firefox/1.0/alpha1
    ...

    >>> release = webservice.get(response.getHeader("Location")).jsonBody()
    >>> print(release["version"])
    alpha1

    >>> print(release["release_notes"])
    New stuff

    >>> print(release["changelog"])
    Added 5,000 features.

Only one product release can be created per milestone.

    >>> response = webservice.named_post(
    ...     milestone["self_link"],
    ...     "createProductRelease",
    ...     {},
    ...     date_released="2000-01-01T01:01:01+00:00Z",
    ...     changelog="Added 5,000 features.",
    ... )
    >>> print(response)
    HTTP/1.1 400 Bad Request
    ...
    A milestone can only have one ProductRelease.


Project release entries
-----------------------

    >>> releases = webservice.get("/firefox/1.0/releases").jsonBody()
    >>> print_self_link_of_entries(releases)
    http://.../firefox/1.0/1.0.0
    http://.../firefox/1.0/alpha1


Project release file collection
-------------------------------

    >>> pr_files = webservice.get("/firefox/trunk/0.9.2/files").jsonBody()
    >>> print_self_link_of_entries(pr_files)
    http://.../firefox/trunk/0.9.2/+file/firefox_0.9.2.orig.tar.gz


Milestone entry
---------------

The entry for a milestone is available at its canonical URL on the API
virtual host.

    >>> firefox_milestone_1_0 = webservice.get(
    ...     "/firefox/+milestone/1.0"
    ... ).jsonBody()
    >>> pprint_entry(firefox_milestone_1_0)
    code_name: None
    date_targeted: '2056-10-16'
    is_active: True
    name: '1.0'
    official_bug_tags: []
    release_link: None
    resource_type_link: '...'
    self_link: 'http://.../firefox/+milestone/1.0'
    series_target_link: 'http://.../firefox/trunk'
    summary: None
    target_link: 'http://.../firefox'
    title: 'Mozilla Firefox 1.0'
    web_link: 'http://launchpad.../firefox/+milestone/1.0'

The milestone entry has a link to its release if it has one.

    >>> milestone = webservice.get("/firefox/+milestone/1.0.0").jsonBody()
    >>> print(milestone["release_link"])
    http://.../firefox/1.0/1.0.0


Project release entries
-----------------------

    >>> releases = webservice.get("/firefox/1.0/releases").jsonBody()
    >>> print_self_link_of_entries(releases)
    http://.../firefox/1.0/1.0.0
    http://.../firefox/1.0/alpha1

They can be deleted with the 'delete' operation.

    >>> results = webservice.named_post("/firefox/1.0/alpha1", "delete")
    >>> print(results)
    HTTP/1.1 200 Ok
    ...


Project release file entry
--------------------------

Project release files are available at their canonical URL on the API
virtual host.

    >>> url = "/firefox/trunk/0.9.2/+file/firefox_0.9.2.orig.tar.gz"
    >>> result = webservice.get(url).jsonBody()
    >>> pprint_entry(result)
    date_uploaded: '2005-06-06T08:59:51.926792+00:00'
    description: None
    file_link:
        'http://.../firefox/trunk/0.9.2/+file/firefox_0.9.2.orig.tar.gz/file'
    file_type: 'Code Release Tarball'
    project_release_link: 'http://.../firefox/trunk/0.9.2'
    resource_type_link: 'http://.../#project_release_file'
    self_link:
        'http://.../firefox/trunk/0.9.2/+file/firefox_0.9.2.orig.tar.gz'
    signature_link:
        'http://.../trunk/0.9.2/+file/firefox_0.9.2.orig.tar.gz/signature'

The actual file redirects to the librarian when accessed.

    >>> url = "/firefox/trunk/0.9.2/+file/firefox_0.9.2.orig.tar.gz/file"
    >>> result = webservice.get(url)
    >>> print(result)
    HTTP/1.1 303 See Other
    ...
    Location: http://.../firefox_0.9.2.orig.tar.gz
    ...

The signature file will redirect too, if found.  In this case there is
no signature so we get a 404.

    >>> url = "/firefox/trunk/0.9.2/+file/firefox_0.9.2.orig.tar.gz/signature"
    >>> result = webservice.get(url)
    >>> print(result)
    HTTP/1.1 404 Not Found
    ...

The file and signature on a Project Release File are 'readonly'. Trying
to put new content will result in a ForbiddenAttribute error.

    >>> url = "/firefox/trunk/0.9.2/+file/firefox_0.9.2.orig.tar.gz/file"
    >>> response = webservice.put(url, "application/x-tar-gz", "fakefiledata")
    >>> print(response)
    HTTP/1.1 405 Method Not Allowed...
    Allow: GET
    ...

    >>> url = "/firefox/trunk/0.9.2/+file/firefox_0.9.2.orig.tar.gz/signature"
    >>> response = webservice.put(url, "pgpapplication/data", "signaturedata")
    >>> print(response)
    HTTP/1.1 405 Method Not Allowed...
    Allow: GET
    ...


Project release files
---------------------

Project release files can be added to a project release using the API
'add_file' method.

    >>> import io

    >>> files_url = "/firefox/1.0/1.0.0/files"
    >>> ff_100_files = webservice.get(files_url).jsonBody()
    >>> print_self_link_of_entries(ff_100_files)

    >>> pr_url = "/firefox/1.0/1.0.0"
    >>> ff_100 = webservice.get(pr_url).jsonBody()
    >>> file_content = io.BytesIO(b"first attachment file content \xff")
    >>> sig_file_content = io.BytesIO(b"hash hash hash \xff")
    >>> response = webservice.named_post(
    ...     ff_100["self_link"],
    ...     "add_file",
    ...     filename="filename.txt",
    ...     file_content=file_content,
    ...     content_type="plain/txt",
    ...     signature_filename="filename.txt.md5",
    ...     signature_content=sig_file_content,
    ...     file_type="README File",
    ...     description="test file",
    ... )
    >>> print(response)
    HTTP/1.1 201 Created
    ...
    Location: http://.../firefox/1.0/1.0.0/+file/filename.txt
    ...

Firefox 1.0/1.0.0 now has one file.

    >>> files_url = "/firefox/1.0/1.0.0/files"
    >>> ff_100_files = webservice.get(files_url).jsonBody()
    >>> print_self_link_of_entries(ff_100_files)
    http://.../firefox/1.0/1.0.0/+file/filename.txt

And it has been uploaded correctly.

    >>> from zope.component import getUtility
    >>> from lp.registry.interfaces.product import IProductSet
    >>> from lp.testing import login, logout
    >>> login("bac@canonical.com")
    >>> concrete_one_zero = getUtility(IProductSet)["firefox"].getRelease(
    ...     "1.0.0"
    ... )
    >>> concrete_one_zero.files[0].libraryfile.read() == (
    ...     file_content.getvalue()
    ... )
    True
    >>> concrete_one_zero.files[0].signature.read() == (
    ...     sig_file_content.getvalue()
    ... )
    True
    >>> logout()

The file type and description are optional.  If no signature is
available then it must be explicitly set to None.

    >>> file_content = io.BytesIO(b"second attachment file content")
    >>> response = webservice.named_post(
    ...     ff_100["self_link"],
    ...     "add_file",
    ...     filename="filename2.txt",
    ...     file_content=file_content,
    ...     content_type="plain/txt",
    ... )
    >>> print(response)
    HTTP/1.1 201 Created
    ...
    Location: http://.../firefox/1.0/1.0.0/+file/filename2.txt
    ...

Firefox 1.0/1.0.0 now has two files.

    >>> files_url = "/firefox/1.0/1.0.0/files"
    >>> ff_100_files = webservice.get(files_url).jsonBody()
    >>> print_self_link_of_entries(ff_100_files)
    http://.../firefox/1.0/1.0.0/+file/filename.txt
    http://.../firefox/1.0/1.0.0/+file/filename2.txt

The file redirects to the librarian when accessed.

    >>> url = webservice.getAbsoluteUrl(
    ...     "/firefox/1.0/1.0.0/+file/filename.txt/file"
    ... )
    >>> result = webservice.get(url)
    >>> print(result)
    HTTP/1.1 303 See Other
    ...
    Location: http://.../filename.txt
    ...

Project release files can be deleted using the 'delete' method.  The
project maintainer, project series owners, admins, or registry experts
can delete files.

    >>> url = webservice.getAbsoluteUrl(
    ...     "/firefox/1.0/1.0.0/+file/filename.txt"
    ... )
    >>> results = webservice.named_post(url, "delete")
    >>> print(results)
    HTTP/1.1 200 Ok
    ...

    >>> files_url = "/firefox/1.0/1.0.0/files"
    >>> ff_100_files = webservice.get(files_url).jsonBody()
    >>> print_self_link_of_entries(ff_100_files)
    http://.../firefox/1.0/1.0.0/+file/filename2.txt

Anonymous users can access project release files.

    >>> release_files = anon_webservice.get(
    ...     "/firefox/1.0/1.0.0/files"
    ... ).jsonBody()
    >>> print_self_link_of_entries(release_files)
    http://.../firefox/1.0/1.0.0/+file/filename2.txt


Commercial subscriptions
------------------------

If a project has a commercial-use subscription then it can be retrieved
through the API.

    >>> login("bac@canonical.com")
    >>> mmm = getUtility(IProductSet)["mega-money-maker"]
    >>> print(mmm.commercial_subscription)
    None

    >>> _ = factory.makeCommercialSubscription(mmm)
    >>> print(mmm.commercial_subscription.product.name)
    mega-money-maker

    >>> logout()
    >>> mmm = webservice.get("/mega-money-maker").jsonBody()
    >>> print(mmm["display_name"])
    Mega Money Maker

    >>> print(mmm["commercial_subscription_link"])
    http://.../mega-money-maker/+commercialsubscription/...
