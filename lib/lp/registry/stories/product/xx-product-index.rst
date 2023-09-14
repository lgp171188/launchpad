Product index
=============

Translation Pages
-----------------

    >>> user_browser.open("http://launchpad.test/evolution")

The product page has a link to help translate it.

    >>> link = user_browser.getLink(
    ...     url="http://translations.launchpad.test/evolution"
    ... )
    >>> link.click()
    >>> print(user_browser.title)
    Translations : Evolution


Links and Programming languages
-------------------------------

Evolution has no external links.

    >>> print(find_tag_by_id(user_browser.contents, "external-links-heading"))
    None

Now update Tomcat to actually have this data:

    >>> import transaction
    >>> from lp.registry.enums import VCSType
    >>> from lp.registry.model.product import Product
    >>> from lp.services.database.interfaces import IStore
    >>> from lp.services.database.sqlbase import flush_database_updates
    >>> from lp.testing import ANONYMOUS, login, logout
    >>> login(ANONYMOUS)

    >>> tomcat = IStore(Product).find(Product, name="tomcat").one()
    >>> tomcat.vcs = VCSType.GIT
    >>> tomcat.homepageurl = "http://home.page/"
    >>> tomcat.sourceforgeproject = "sf-tomcat"
    >>> tomcat.wikiurl = "http://wiki.url/"
    >>> tomcat.screenshotsurl = "http://screenshots.url/"
    >>> tomcat.downloadurl = "http://download.url/"
    >>> tomcat.programminglang = "C++,Xenon and Purple"

    >>> logout()
    >>> flush_database_updates()
    >>> transaction.commit()

Let's check it out:

    >>> browser.open("http://launchpad.test/tomcat")
    >>> content = find_main_content(browser.contents)
    >>> external_links = find_tag_by_id(content, "external-links")
    >>> for link in external_links.find_all("a"):
    ...     print(extract_text(link), link["href"])
    ...
    Home page http://home.page/
    Sourceforge project http://sourceforge.net/projects/sf-tomcat
    Wiki http://wiki.url/
    Screenshots http://screenshots.url/
    External downloads http://download.url/

    >>> print(extract_text(find_tag_by_id(content, "product-languages")))
    Programming languages: C++,Xenon and Purple

When the sourceforge URL is identical to the homepage, we omit the homepage:

    >>> login(ANONYMOUS)

    >>> tomcat = IStore(Product).find(Product, name="tomcat").one()
    >>> tomcat.homepageurl = "http://sourceforge.net/projects/sf-tomcat"

    >>> logout()
    >>> flush_database_updates()
    >>> transaction.commit()

    >>> browser.open("http://launchpad.test/tomcat")
    >>> content = find_main_content(browser.contents)
    >>> external_links = find_tag_by_id(content, "external-links")
    >>> for link in external_links.find_all("a"):
    ...     print(extract_text(link), link["href"])
    ...
    Sourceforge project http://sourceforge.net/projects/sf-tomcat
    Wiki http://wiki.url/
    Screenshots http://screenshots.url/
    External downloads http://download.url/


Licensing alerts
================

A project that includes a licence of "Other/Open Source" that has not
been reviewed by a Launchpad administrator will be displayed as
'Unreviewed.'

    >>> from lp.registry.interfaces.product import License
    >>> owner_browser = setupBrowser(auth="Basic test@canonical.com:test")
    >>> owner_browser.open("http://launchpad.test/thunderbird/+edit")
    >>> owner_browser.getControl(name="field.licenses").value = [
    ...     "OTHER_OPEN_SOURCE"
    ... ]
    >>> owner_browser.getControl(name="field.license_info").value = "foo"
    >>> owner_browser.getControl("Change").click()

Any user can see that the project's licence has not been reviewed.

    >>> user_browser.open("http://launchpad.test/thunderbird")
    >>> print(
    ...     extract_text(
    ...         find_tag_by_id(user_browser.contents, "license-status")
    ...     )
    ... )
    This project’s licence has not been reviewed.

Changing the state to reviewed but not approved results in the project
being shown as proprietary.

    >>> admin_browser.open(
    ...     "http://launchpad.test/thunderbird/+review-license"
    ... )
    >>> admin_browser.getControl(name="field.project_reviewed").value = True
    >>> admin_browser.getControl(name="field.license_approved").value = False
    >>> admin_browser.getControl("Change").click()

    >>> user_browser.open("http://launchpad.test/thunderbird")
    >>> user_browser.contents
    '<...This project&rsquo;s licence is proprietary...

If the project doesn't qualify for free hosting, or if it doesn't have
much time left on its commercial subscription, a portlet is displayed to
direct the owner to purchase a subscription.

    >>> firefox = IStore(Product).find(Product, name="firefox").one()
    >>> ignored = login_person(firefox.owner)
    >>> firefox.licenses = [License.OTHER_PROPRIETARY]
    >>> firefox.license_info = "Internal project."
    >>> flush_database_updates()
    >>> transaction.commit()
    >>> logout()
    >>> owner_browser.open("http://launchpad.test/firefox")
    >>> print(find_tag_by_id(owner_browser.contents, "license-status"))
    <...This project’s licence is proprietary...

    >>> print(
    ...     find_tag_by_id(
    ...         owner_browser.contents, "portlet-requires-subscription"
    ...     )
    ... )
    <div...Purchasing a commercial subscription is required...</div>

Any user can see that the project's licence is proprietary.

    >>> user_browser.open("http://launchpad.test/firefox")
    >>> user_browser.contents
    '<...This project&rsquo;s licence is proprietary...
    >>> print(extract_text(find_tag_by_id(user_browser.contents, "licences")))
    Licence:
    Other/Proprietary (Internal project.)
    Commercial subscription expires ...


A non-owner does not see that a commercial subscription is due.

    >>> print(
    ...     find_tag_by_id(
    ...         user_browser.contents, "portlet-requires-subscription"
    ...     )
    ... )
    None

If the project qualifies for free hosting, the portlet is not displayed.

    >>> firefox.licenses = [License.GNU_GPL_V2]
    >>> flush_database_updates()
    >>> transaction.commit()
    >>> owner_browser.open("http://launchpad.test/firefox")
    >>> print(
    ...     find_tag_by_id(
    ...         owner_browser.contents, "portlet-requires-subscription"
    ...     )
    ... )
    None

If the project's licence is open source, the licence status is not
displayed on the index page, since most projects fall into this
category.

    >>> user_browser.open("http://launchpad.test/firefox")
    >>> print(find_tag_by_id(owner_browser.contents, "license-status"))
    None
    >>> print(extract_text(find_tag_by_id(user_browser.contents, "licences")))
    Licence:
    GNU GPL v2
    Commercial subscription expires ...


Commercial Subscription Expiration
----------------------------------

If the project has been granted a commercial subscription then the
expiration date is shown to the project maintainers, Launchpad admins,
and members of the Launchpad commercial team.

Enable the subscription.

    >>> from zope.component import getUtility
    >>> from lp.registry.interfaces.product import IProductSet
    >>> login(ANONYMOUS)
    >>> mmm = getUtility(IProductSet).getByName("mega-money-maker")
    >>> _ = login_person(mmm.owner)
    >>> _ = factory.makeCommercialSubscription(mmm)
    >>> logout()

 The owner will now see the expiration information on the project
 overview page.

    >>> owner_browser = setupBrowser(auth="Basic bac@canonical.com:test")
    >>> owner_browser.open("http://launchpad.test/mega-money-maker")
    >>> print(
    ...     extract_text(
    ...         find_tag_by_id(
    ...             owner_browser.contents, "commercial_subscription"
    ...         )
    ...     )
    ... )
    Commercial subscription expires ...

Commercial team members will see the expiration information.

    >>> comm_browser = setupBrowser(
    ...     auth="Basic commercial-member@canonical.com:test"
    ... )
    >>> comm_browser.open("http://launchpad.test/mega-money-maker")
    >>> print(
    ...     extract_text(
    ...         find_tag_by_id(
    ...             comm_browser.contents, "commercial_subscription"
    ...         )
    ...     )
    ... )
    Commercial subscription expires ...

Launchpad administrators will see the expiration information.

    >>> admin_browser.open("http://launchpad.test/mega-money-maker")
    >>> print(
    ...     extract_text(
    ...         find_tag_by_id(
    ...             admin_browser.contents, "commercial_subscription"
    ...         )
    ...     )
    ... )
    Commercial subscription expires ...


Development
-----------

The project page shows the series that is the focus of development.

    >>> anon_browser.open("http://launchpad.test/firefox")
    >>> print(
    ...     extract_text(
    ...         find_tag_by_id(anon_browser.contents, "development-focus")
    ...     )
    ... )
    trunk series is the current focus of development.

The page has a link to view the project's milestones.

    >>> anon_browser.getLink("View milestones")
    <Link ... url='http://launchpad.test/firefox/+milestones'>

Project owners and driver can see a link to register series.

    >>> owner_browser = setupBrowser(auth="Basic test@canonical.com:test")
    >>> owner_browser.open("http://launchpad.test/firefox")
    >>> owner_browser.getLink("Register a series")
    <Link ... url='http://launchpad.test/firefox/+addseries'>


Aliases
-------

When a project has one or more aliases, they're shown on the project's
home page.

    >>> IStore(Product).find(Product, name="firefox").one().setAliases(
    ...     ["iceweasel", "snowchicken"]
    ... )
    >>> anon_browser.open("http://launchpad.test/firefox")
    >>> print(extract_text(find_tag_by_id(anon_browser.contents, "aliases")))
    Also known as: iceweasel, snowchicken


Ubuntu packaging
----------------

If a product is packaged in Ubuntu the links are shown.

    >>> user_browser.open("http://launchpad.test/firefox")
    >>> print(
    ...     extract_text(
    ...         find_tag_by_id(user_browser.contents, "portlet-packages")
    ...     )
    ... )
    All packages
    Packages in Distributions
    mozilla-firefox source package in Warty Version 0.9 uploaded on...
