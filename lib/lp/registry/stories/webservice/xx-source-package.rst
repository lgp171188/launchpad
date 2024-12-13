Source Package API
==================


Prelude
-------

    >>> login(ANONYMOUS)
    >>> a_distro = factory.makeDistribution(name="my-distro")
    >>> a_distro_owner = a_distro.owner
    >>> a_series = factory.makeDistroSeries(
    ...     name="my-series", distribution=a_distro
    ... )
    >>> evolution_package = factory.makeSourcePackage(
    ...     sourcepackagename="evolution", distroseries=a_series
    ... )
    >>> logout()


Getting source packages
-----------------------

We can get source packages that are bound to a distribution series from the
distribution series.

    >>> my_series = webservice.get("/my-distro/my-series").jsonBody()
    >>> evolution = webservice.named_get(
    ...     my_series["self_link"], "getSourcePackage", name="evolution"
    ... ).jsonBody()

    >>> from lazr.restful.testing.webservice import pprint_entry
    >>> pprint_entry(evolution)
    bug_reported_acknowledgement: None
    bug_reporting_guidelines: None
    content_templates: None
    displayname: 'evolution in My-distro My-series'
    distribution_link: 'http://.../my-distro'
    distroseries_link: 'http://.../my-distro/my-series'
    latest_published_component_name: None
    name: 'evolution'
    official_bug_tags: []
    productseries_link: None
    resource_type_link: ...
    self_link: 'http://api.../my-distro/my-series/+source/evolution'
    web_link: 'http://.../+source/evolution'


Getting official branches
-------------------------

Then we can get the branches that are bound to various pockets of this
distribution series. By default, there are none bound to evolution.

    >>> branch = webservice.named_get(
    ...     evolution["self_link"], "getBranch", pocket="Release"
    ... ).jsonBody()
    >>> print(branch)
    None


Setting official branches
-------------------------

We can even set a branch for the series. First we need to *make* a branch
though.

    >>> login(ANONYMOUS)
    >>> owner = factory.makePerson(name="devo")
    >>> branch = factory.makePackageBranch(
    ...     sourcepackage=evolution_package, owner=owner, name="branch"
    ... )
    >>> print(branch.unique_name)
    ~devo/my-distro/my-series/evolution/branch
    >>> branch_url = "/" + branch.unique_name
    >>> logout()

Then we set the branch on the evolution package:

    >>> from lp.testing.pages import webservice_for_person
    >>> from lp.services.webapp.interfaces import OAuthPermission
    >>> webservice = webservice_for_person(
    ...     a_distro_owner, permission=OAuthPermission.WRITE_PRIVATE
    ... )
    >>> branch = webservice.get(branch_url).jsonBody()
    >>> response = webservice.named_post(
    ...     evolution["self_link"],
    ...     "setBranch",
    ...     pocket="Release",
    ...     branch=branch["self_link"],
    ... )
    >>> print(response.jsonBody())
    None

I guess this means that if we get the branch for the RELEASE pocket again,
we'll get the new branch.

    >>> branch = webservice.named_get(
    ...     evolution["self_link"], "getBranch", pocket="Release"
    ... ).jsonBody()
    >>> print(branch["unique_name"])
    ~devo/my-distro/my-series/evolution/branch

    >>> linked_branches = webservice.named_get(
    ...     evolution["self_link"], "linkedBranches"
    ... ).jsonBody()
    >>> for pocket in linked_branches:
    ...     print(pocket)
    ...
    RELEASE
    >>> branch = linked_branches["RELEASE"]
    >>> print(branch["unique_name"])
    ~devo/my-distro/.../branch

Of course, we're also allowed to change our minds. If we set the branch for
the RELEASE pocket to 'null' (i.e. the JSON for Python' None), then there is
no longer an official branch for that pocket.

    >>> response = webservice.named_post(
    ...     evolution["self_link"],
    ...     "setBranch",
    ...     pocket="Release",
    ...     branch="null",
    ... )
    >>> print(response.jsonBody())
    None
    >>> branch = webservice.named_get(
    ...     evolution["self_link"], "getBranch", pocket="Release"
    ... ).jsonBody()
    >>> print(branch)
    None
