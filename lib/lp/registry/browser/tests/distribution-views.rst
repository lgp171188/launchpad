Distribution Views
==================

Lists of distribution mirrors
-----------------------------

There are several pages listing the mirrors of a distribution, and they all
share a common base class which is responsible for ordering the mirrors by
country.

    >>> from lp.registry.interfaces.distribution import IDistributionSet

    >>> distributionset = getUtility(IDistributionSet)
    >>> ubuntu = distributionset.getByName("ubuntu")
    >>> ubuntu_cdmirrors = create_view(ubuntu, name="+cdmirrors")

    >>> country_and_mirrors = ubuntu_cdmirrors.getMirrorsGroupedByCountry()
    >>> for country_and_mirror in country_and_mirrors:
    ...     country = country_and_mirror["country"]
    ...     mirrors = country_and_mirror["mirrors"]
    ...     for mirror in mirrors:
    ...         assert mirror.country.name == country
    ...     print("%s: %d mirror(s)" % (country, len(mirrors)))
    ...
    France: 2 mirror(s)
    Germany: 1 mirror(s)
    United Kingdom: 1 mirror(s)

Lists of archive mirrors
------------------------

    >>> ubuntu_archivemirrors = create_view(ubuntu, name="+archivemirrors")
    >>> country_and_mirrors = (
    ...     ubuntu_archivemirrors.getMirrorsGroupedByCountry()
    ... )
    >>> for country_and_mirror in country_and_mirrors:
    ...     country = country_and_mirror["country"]
    ...     mirrors = country_and_mirror["mirrors"]
    ...     for mirror in mirrors:
    ...         assert mirror.country.name == country
    ...     print("%s: %d mirror(s)" % (country, len(mirrors)))
    ...
    Antarctica: 2 mirror(s)
    France: 2 mirror(s)
    United Kingdom: 1 mirror(s)


Distribution modification views
===============================


Registering a distribution
--------------------------

The +add view of the DistributionSet allows admins to register distributions.

    >>> view = create_view(distributionset, "+add")
    >>> print(view.label)
    Register a new distribution

    >>> print(view.page_title)
    Register a new distribution

The view provides a cancel link.

    >>> print(view.cancel_url)
    http://launchpad.test/distros

The view accepts the basic fields to register a distribution.

    >>> view.field_names
    ['name', 'display_name', 'summary', 'description', 'domainname',
     'members', 'official_malone', 'blueprints_usage', 'translations_usage',
     'answers_usage']

    >>> login("admin@canonical.com")
    >>> form = {
    ...     "field.name": "youbuntu",
    ...     "field.display_name": "YoUbuntu",
    ...     "field.summary": "summary",
    ...     "field.description": "description",
    ...     "field.domainname": "youbuntu.me",
    ...     "field.members": "landscape-developers",
    ...     "field.require_virtualized": "on",
    ...     "field.processors": [],
    ...     "field.actions.save": "Save",
    ... }
    >>> view = create_initialized_view(distributionset, "+add", form=form)
    >>> view.errors
    []
    >>> print(view.next_url)
    http://launchpad.test/youbuntu

    >>> distribution = distributionset.getByName("youbuntu")
    >>> print(distribution.name)
    youbuntu

Only admins and owners can access the view.

    >>> from lp.services.webapp.authorization import check_permission

    >>> check_permission("launchpad.Admin", view)
    True

    >>> login("no-priv@canonical.com")
    >>> check_permission("launchpad.Admin", view)
    False


Editing a distribution
----------------------

The +edit view allows an owner or admin to change a distribution. It provides
a label, page_title, and cancel_url.

    >>> login("admin@canonical.com")
    >>> view = create_view(distribution, "+edit")
    >>> print(view.label)
    Change YoUbuntu details

    >>> print(view.page_title)
    Change YoUbuntu details

    >>> print(view.cancel_url)
    http://launchpad.test/youbuntu

The view accepts most of the distribution fields.

    >>> distribution.bug_tracking_usage
    <DBItem ServiceUsage.UNKNOWN, (10) Unknown>

    >>> view.field_names
    ['display_name', 'summary', 'description',
     'bug_reporting_guidelines', 'content_templates',
     'bug_reported_acknowledgement',
     'package_derivatives_email', 'icon',
     'logo', 'mugshot', 'official_malone', 'enable_bug_expiration',
     'blueprints_usage', 'translations_usage', 'answers_usage',
     'translation_focus',
     'default_traversal_policy', 'redirect_default_traversal',
     'oci_registry_credentials']

    >>> del form["field.name"]
    >>> del form["field.actions.save"]
    >>> form["field.bug_reporting_guidelines"] = "guidelines"
    >>> form["field.official_malone"] = "on"
    >>> form["field.actions.change"] = "Change"
    >>> view = create_initialized_view(distribution, "+edit", form=form)
    >>> view.errors
    []
    >>> print(view.next_url)
    http://launchpad.test/youbuntu

    >>> print(distribution.bug_reporting_guidelines)
    guidelines

    >>> distribution.bug_tracking_usage
    <DBItem ServiceUsage.LAUNCHPAD, (20) Launchpad>

Only admins and owners can access the view.

    >>> check_permission("launchpad.Edit", view)
    True

    >>> login("no-priv@canonical.com")
    >>> check_permission("launchpad.Edit", view)
    False


Changing a distribution mirror administrator
--------------------------------------------

the +selectmirroradmins allows the owner or admin to change the mirror
administrator.

    >>> login("admin@canonical.com")
    >>> view = create_view(distribution, "+selectmirroradmins")
    >>> print(view.label)
    Change the YoUbuntu mirror administrator

    >>> print(view.page_title)
    Change the YoUbuntu mirror administrator

    >>> print(view.cancel_url)
    http://launchpad.test/youbuntu

The view accepts the mirror_admin field.

    >>> print(distribution.mirror_admin.name)
    name16

    >>> view.field_names
    ['mirror_admin']

    >>> form = {
    ...     "field.mirror_admin": "no-priv",
    ...     "field.actions.change": "Change",
    ... }
    >>> view = create_initialized_view(
    ...     distribution, "+selectmirroradmins", form=form
    ... )
    >>> view.errors
    []
    >>> print(view.next_url)
    http://launchpad.test/youbuntu

    >>> print(distribution.mirror_admin.name)
    no-priv

Only admins and owners can access the view.

    >>> check_permission("launchpad.Edit", view)
    True

    >>> login("no-priv@canonical.com")
    >>> check_permission("launchpad.Edit", view)
    False


Changing a distribution OCI project administrator
-------------------------------------------------

The +select-oci-project-admins view allows the owner or admin to change the
OCI project administrator.

    >>> login("admin@canonical.com")
    >>> view = create_view(distribution, "+select-oci-project-admins")
    >>> print(view.label)
    Change the YoUbuntu OCI project administrator

    >>> print(view.page_title)
    Change the YoUbuntu OCI project administrator

    >>> print(view.cancel_url)
    http://launchpad.test/youbuntu

The view accepts the oci_project_admin field.

    >>> print(distribution.oci_project_admin)
    None

    >>> view.field_names
    ['oci_project_admin']

    >>> form = {
    ...     "field.oci_project_admin": "no-priv",
    ...     "field.actions.change": "Change",
    ... }
    >>> view = create_initialized_view(
    ...     distribution, "+select-oci-project-admins", form=form
    ... )
    >>> view.errors
    []
    >>> print(view.next_url)
    http://launchpad.test/youbuntu

    >>> print(distribution.oci_project_admin.name)
    no-priv

Only admins and owners can access the view.

    >>> check_permission("launchpad.Edit", view)
    True

    >>> login("no-priv@canonical.com")
    >>> check_permission("launchpad.Edit", view)
    False


Changing a distribution security administrator
----------------------------------------------

The +select-security-admins view allows the owner or admin to change the
security administrator.

    >>> login("admin@canonical.com")
    >>> view = create_view(distribution, "+select-security-admins")
    >>> print(view.label)
    Change the YoUbuntu security administrator

    >>> print(view.page_title)
    Change the YoUbuntu security administrator

    >>> print(view.cancel_url)
    http://launchpad.test/youbuntu

The view accepts the security_admin field.

    >>> print(distribution.security_admin)
    None

    >>> view.field_names
    ['security_admin']

    >>> form = {
    ...     "field.security_admin": "no-priv",
    ...     "field.actions.change": "Change",
    ... }
    >>> view = create_initialized_view(
    ...     distribution, "+select-security-admins", form=form
    ... )
    >>> view.errors
    []
    >>> print(view.next_url)
    http://launchpad.test/youbuntu

    >>> print(distribution.security_admin.name)
    no-priv

Only admins and owners can access the view.

    >>> check_permission("launchpad.Edit", view)
    True

    >>> login("no-priv@canonical.com")
    >>> check_permission("launchpad.Edit", view)
    False


Changing a distribution code administrator
------------------------------------------

The +select-code-admins view allows the owner or admin to change the
code administrator.

    >>> login("admin@canonical.com")
    >>> view = create_view(distribution, "+select-code-admins")
    >>> print(view.label)
    Change the YoUbuntu code administrator

    >>> print(view.page_title)
    Change the YoUbuntu code administrator

    >>> print(view.cancel_url)
    http://launchpad.test/youbuntu

The view accepts the code_admin field.

    >>> print(distribution.code_admin)
    None

    >>> view.field_names
    ['code_admin']

    >>> form = {
    ...     "field.code_admin": "no-priv",
    ...     "field.actions.change": "Change",
    ... }
    >>> view = create_initialized_view(
    ...     distribution, "+select-code-admins", form=form
    ... )
    >>> view.errors
    []
    >>> print(view.next_url)
    http://launchpad.test/youbuntu

    >>> print(distribution.code_admin.name)
    no-priv

Only admins and owners can access the view.

    >>> check_permission("launchpad.Edit", view)
    True

    >>> login("no-priv@canonical.com")
    >>> check_permission("launchpad.Edit", view)
    False


Changing a distribution members team
------------------------------------

the +selectmirroradmins allows the owner or admin to change the members team.

    >>> login("admin@canonical.com")
    >>> view = create_view(distribution, "+selectmemberteam")
    >>> print(view.label)
    Change the YoUbuntu members team

    >>> print(view.page_title)
    Change the YoUbuntu members team

    >>> print(view.cancel_url)
    http://launchpad.test/youbuntu

The view accepts the members field.

    >>> print(distribution.members.name)
    landscape-developers

    >>> view.field_names
    ['members']

    >>> form = {
    ...     "field.members": "ubuntu-team",
    ...     "field.actions.change": "Change",
    ... }
    >>> view = create_initialized_view(
    ...     distribution, "+selectmemberteam", form=form
    ... )
    >>> view.errors
    []
    >>> print(view.next_url)
    http://launchpad.test/youbuntu

    >>> print(distribution.members.name)
    ubuntu-team

Only admins and owners can access the view.

    >>> check_permission("launchpad.Edit", view)
    True

    >>> login("no-priv@canonical.com")
    >>> check_permission("launchpad.Edit", view)
    False


Distribution +index
===================

+index portlets
---------------

The distribution index page may contain portlets for Launchpad applications.
If the distribution does not officially use the apps, its portlet does
not appear.

    >>> from lp.testing.pages import find_tag_by_id

    >>> owner = distribution.owner
    >>> ignored = login_person(owner)
    >>> distribution.official_malone = False
    >>> question = factory.makeQuestion(target=distribution)
    >>> faq = factory.makeFAQ(target=distribution)
    >>> bugtask = factory.makeBugTask(target=distribution)
    >>> blueprint = factory.makeSpecification(distribution=distribution)

    >>> view = create_view(distribution, name="+index", principal=owner)
    >>> content = find_tag_by_id(view.render(), "maincontent")
    >>> print(find_tag_by_id(content, "portlet-latest-faqs"))
    None
    >>> print(find_tag_by_id(content, "portlet-latest-questions"))
    None
    >>> print(find_tag_by_id(content, "portlet-latest-bugs"))
    None
    >>> print(find_tag_by_id(content, "portlet-blueprints"))
    None

If the distribution officially uses the application, its portlet does appear.

    >>> from lp.app.enums import ServiceUsage

    >>> distribution.answers_usage = ServiceUsage.LAUNCHPAD
    >>> distribution.blueprints_usage = ServiceUsage.LAUNCHPAD
    >>> distribution.official_malone = True

    >>> view = create_view(distribution, name="+index", principal=owner)
    >>> content = find_tag_by_id(view.render(), "maincontent")
    >>> print(find_tag_by_id(content, "portlet-latest-faqs")["id"])
    portlet-latest-faqs
    >>> print(find_tag_by_id(content, "portlet-latest-questions")["id"])
    portlet-latest-questions
    >>> print(find_tag_by_id(content, "portlet-latest-bugs")["id"])
    portlet-latest-bugs
    >>> print(find_tag_by_id(content, "portlet-blueprints")["id"])
    portlet-blueprints


Displaying commercial subscription information
----------------------------------------------

Only distribution owners, Launchpad administrators, and Launchpad
Commercial members are to see commercial subscription information on
the product overview page.

For distribution owners the property is true.

    >>> from zope.security.proxy import removeSecurityProxy

    >>> commercial_distro = factory.makeDistribution()
    >>> _ = login_person(removeSecurityProxy(commercial_distro).owner)
    >>> view = create_initialized_view(commercial_distro, name="+index")
    >>> print(view.show_commercial_subscription_info)
    True

For Launchpad admins the property is true.

    >>> login("foo.bar@canonical.com")
    >>> view = create_initialized_view(commercial_distro, name="+index")
    >>> print(view.show_commercial_subscription_info)
    True

For Launchpad commercial members the property is true.

    >>> login("commercial-member@canonical.com")
    >>> view = create_initialized_view(commercial_distro, name="+index")
    >>> print(view.show_commercial_subscription_info)
    True

But for a no-privileges user the property is false.

    >>> login("no-priv@canonical.com")
    >>> view = create_initialized_view(commercial_distro, name="+index")
    >>> print(view.show_commercial_subscription_info)
    False

And for an anonymous user it is false.

    >>> login(ANONYMOUS)
    >>> view = create_initialized_view(commercial_distro, name="+index")
    >>> print(view.show_commercial_subscription_info)
    False


Distribution +series
--------------------

The +series view provides a page title and list of dicts that represent
the series and the CSS class to present them with.

    >>> view = create_view(ubuntu, name="+series")
    >>> print(view.label)
    Timeline

    >>> for styled_series in view.styled_series:
    ...     print(styled_series["series"].name, styled_series["css_class"])
    ...
    breezy-autotest
    grumpy
    hoary highlight
    warty


Distribution +derivatives
-------------------------

The +derivatives view provides a page title and list of dicts that represent
the derivatives and the CSS class to present them with.

    >>> view = create_view(ubuntu, name="+derivatives")
    >>> print(view.label)
    Derivatives

    >>> for styled_series in view.styled_series:
    ...     print(styled_series["series"].name, styled_series["css_class"])
    ...
    hoary-test
    krunch
    breezy-autotest
    2k5 highlight


Distribution +ppas
------------------

The +ppas view provides a page title and label, some statistics helpers
and search results.

    >>> view = create_view(ubuntu, name="+ppas")
    >>> print(view.label)
    Personal Package Archives for Ubuntu

    # The leaf of the breadcrumbs, also used in the page-title.
    >>> print(view.page_title)
    Personal Package Archives
