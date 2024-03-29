ProductSeries
=============

A Launchpad Product models a single piece of software. However for
release management purposes, a Product often has to be split in several
discrete entities which must be considered separately for packaging,
translations, version control, etc. We call these entities
ProductSeries.

    >>> from zope.component import getUtility
    >>> from lp.testing import verifyObject
    >>> from lp.registry.interfaces.person import IPersonSet
    >>> from lp.registry.interfaces.product import IProductSet
    >>> from lp.registry.interfaces.productseries import IProductSeries
    >>> from lp.translations.interfaces.hastranslationimports import (
    ...     IHasTranslationImports,
    ... )
    >>> from lp.services.database.sqlbase import flush_database_updates

First, get a product that has some ProductSeries in the sample data.

    >>> productset = getUtility(IProductSet)
    >>> firefox = productset["firefox"]

A ProductSeries can be retrieved using the associated product and the
series name.

    >>> trunk = firefox.getSeries("trunk")

Verify that the resulting object correctly implements the IProductSeries
interface.

    >>> verifyObject(IProductSeries, trunk)
    True
    >>> IProductSeries.providedBy(trunk)
    True

and IHasTranslationImports.

    >>> verifyObject(IHasTranslationImports, trunk)
    True
    >>> IHasTranslationImports.providedBy(trunk)
    True

And verify that it looks like the series we think it should be.

    >>> trunk.product == firefox
    True
    >>> print(trunk.name)
    trunk

It's also possible to ask a product for all its associated series.

    >>> onedotzero = firefox.getSeries("1.0")
    >>> list(firefox.series) == [onedotzero, trunk]
    True

A ProductSeries can also be fetched with the IProductSeriesSet utility.

    >>> from lp.registry.interfaces.productseries import IProductSeriesSet

    >>> firefox_1_0 = getUtility(IProductSeriesSet).get(2)
    >>> print(firefox_1_0.product.name)
    firefox
    >>> print(firefox_1_0.name)
    1.0

New ProductSeries are created using Product.newSeries(). Only the product
owner or driver can call Product.newSeries().

    >>> series_driver = factory.makePerson(name="driver")
    >>> summary = "Port of Firefox to the Emacs operating system."
    >>> emacs = firefox.newSeries(series_driver, "emacs", summary)
    Traceback (most recent call last):
    ...
    zope.security.interfaces.Unauthorized:
    (..., 'newSeries', 'launchpad.Driver')

    >>> ignored = login_person(firefox.owner)
    >>> emacs_series = firefox.newSeries(
    ...     firefox.owner,
    ...     "emacs",
    ...     summary,
    ...     releasefileglob="ftp://gnu.org/emacs*.gz",
    ... )
    >>> print(emacs_series.name)
    emacs

    >>> print(emacs_series.summary)
    Port of Firefox to the Emacs operating system.

    >>> print(emacs_series.releasefileglob)
    ftp://gnu.org/emacs*.gz

When a driver creates a series, they are also the driver of the new series
to make them the release manager.

    >>> firefox.driver = series_driver
    >>> ignored = login_person(series_driver)
    >>> emacs2 = firefox.newSeries(series_driver, "emacs2", summary)
    >>> print(emacs2.driver.name)
    driver

A newly created series is assumed to be in the development state.

    >>> login(ANONYMOUS)
    >>> print(emacs_series.status.title)
    Active Development

Let's check that the new series is properly associated to its product.

    >>> flush_database_updates()
    >>> firefox.getSeries("emacs") == emacs_series
    True


Drivers and release managers
============================

A person appointed to the project or series driver role is a release
manager and can edit a product series.

    >>> from lp.services.webapp.authorization import check_permission

    >>> firefox_driver = factory.makePerson()
    >>> ignored = login_person(firefox_driver)
    >>> check_permission("launchpad.Edit", emacs_series)
    False
    >>> ignored = login_person(firefox.owner)
    >>> firefox.driver = firefox_driver
    >>> ignored = login_person(firefox_driver)
    >>> check_permission("launchpad.Edit", emacs_series)
    True

    >>> ignored = login_person(firefox.owner)
    >>> emacs_series.driver = series_driver
    >>> ignored = login_person(series_driver)
    >>> check_permission("launchpad.Edit", emacs_series)
    True

    >>> login(ANONYMOUS)


ProductSeries releassefileglob
------------------------------

Each ProductSeries may have a releassefileglob that describes the location
of where release files are uploaded to. The product release finder process
uses the releassefileglob to locate and retrieve files. The files are stored
in the librarian. Each fill is associated with a release. If the series
does not have a release for version in the file name, the finder will create
it. The finder will also create the series milestone too if it does not
exist. The success of product release finder to retrieve files, and create
milestone and releases, is largely predicated on the quality of the
releassefileglob.

The field is constrained by the validate_release_glob() function. It verifies
that the url uses one of the supported schemes (ftp, http, http).

    >>> from lp.registry.interfaces.productseries import validate_release_glob

    >>> validate_release_glob("ftp://ftp.gnu.org/gnu/emacs/emacs-21.*.gz")
    True
    >>> validate_release_glob("http://ftp.gnu.org/gnu/emacs/emacs-21.*.gz")
    True
    >>> validate_release_glob("https://ftp.gnu.org/gnu/emacs/emacs-21.*.gz")
    True

Invalid URLs and unsupported schemes raise a LaunchpadValidationError.

    >>> validate_release_glob("ftp.gnu.org/gnu/emacs/emacs-21.*.gz")
    Traceback (most recent call last):
     ...
    lp.app.validators.LaunchpadValidationError: ...

    >>> validate_release_glob("wais://ftp.gnu.org/gnu/emacs/emacs-21.*.gz")
    Traceback (most recent call last):
     ...
    lp.app.validators.LaunchpadValidationError: ...

The URL must contain a glob (*) or , and may contain more than one.

    >>> validate_release_glob("http://ftp.gnu.org/gnu/emacs/emacs-21.10.1.gz")
    Traceback (most recent call last):
     ...
    lp.app.validators.LaunchpadValidationError: ...

    >>> validate_release_glob("http://ftp.gnu.org/gnu/*/emacs-21.*.gz")
    True


Specification Listings
----------------------

We should be able to get lists of specifications in different states
related to a productseries.

Basically, we can filter by completeness, and by whether or not the spec
is informational.

    >>> onezero = firefox.getSeries("1.0")
    >>> from lp.blueprints.enums import SpecificationFilter

We will create two specs for onezero and use them to demonstrate the
filtering.

    >>> from lp.blueprints.enums import SpecificationDefinitionStatus
    >>> from lp.blueprints.interfaces.specification import ISpecificationSet
    >>> carlos = getUtility(IPersonSet).getByName("carlos")
    >>> _ = login_person(carlos)
    >>> a = getUtility(ISpecificationSet).new(
    ...     name="a",
    ...     title="A",
    ...     specurl="http://wbc.com/two",
    ...     summary="AA",
    ...     definition_status=SpecificationDefinitionStatus.NEW,
    ...     owner=carlos,
    ...     target=firefox,
    ... )
    >>> a.proposeGoal(onezero, carlos)
    >>> b = getUtility(ISpecificationSet).new(
    ...     name="b",
    ...     title="b",
    ...     specurl="http://fds.com/adsf",
    ...     summary="bb",
    ...     definition_status=SpecificationDefinitionStatus.NEW,
    ...     owner=carlos,
    ...     target=firefox,
    ... )
    >>> b.proposeGoal(onezero, carlos)

Now, we will make one of them accepted, the other declined, and both of
them informational.

    >>> from lp.blueprints.enums import SpecificationImplementationStatus
    >>> a.definition_status = b.definition_status = (
    ...     SpecificationDefinitionStatus.APPROVED
    ... )
    >>> a.implementation_status = (
    ...     SpecificationImplementationStatus.INFORMATIONAL
    ... )
    >>> b.implementation_status = (
    ...     SpecificationImplementationStatus.INFORMATIONAL
    ... )
    >>> a.acceptBy(a.owner)
    >>> shim = a.updateLifecycleStatus(a.owner)
    >>> b.declineBy(b.owner)
    >>> shim = b.updateLifecycleStatus(b.owner)

    >>> from lp.services.database.sqlbase import flush_database_updates
    >>> flush_database_updates()

If we ask for ALL specs we should see them both.

    >>> filter = [SpecificationFilter.ALL]
    >>> for s in onezero.specifications(None, filter=filter):
    ...     print(s.name)
    ...
    a
    b

With a productseries, we can ask for ACCEPTED, PROPOSED and DECLINED
specs:

    >>> filter = [SpecificationFilter.ACCEPTED]
    >>> for spec in onezero.specifications(None, filter=filter):
    ...     print(spec.name, spec.goalstatus.title)
    ...
    a Accepted

    >>> filter = [SpecificationFilter.PROPOSED]
    >>> onezero.specifications(None, filter=filter).count()
    0

    >>> filter = [SpecificationFilter.DECLINED]
    >>> onezero.specifications(None, filter=filter).count()
    1

We should see one informational spec if we ask just for that, the
accepted one.

    >>> filter = [SpecificationFilter.INFORMATIONAL]
    >>> for s in onezero.specifications(None, filter=filter):
    ...     print(s.name)
    ...
    a

If we specifically ask for declined informational, we will get that:

    >>> filter = [
    ...     SpecificationFilter.INFORMATIONAL,
    ...     SpecificationFilter.DECLINED,
    ... ]
    >>> for s in onezero.specifications(None, filter=filter):
    ...     print(s.name)
    ...
    b

There are is one completed, accepted spec for 1.0:

    >>> filter = [SpecificationFilter.COMPLETE]
    >>> for spec in onezero.specifications(None, filter=filter):
    ...     print(spec.name, spec.is_complete, spec.goalstatus.title)
    ...
    a True Accepted

There is one completed, declined spec:

    >>> filter = [SpecificationFilter.COMPLETE, SpecificationFilter.DECLINED]
    >>> for spec in onezero.specifications(None, filter=filter):
    ...     print(spec.name, spec.is_complete, spec.goalstatus.title)
    ...
    b True Declined

Now lets make b incomplete, but accepted.

    >>> b.implementation_status = SpecificationImplementationStatus.BETA
    >>> b.definition_status = SpecificationDefinitionStatus.NEW
    >>> shim = b.acceptBy(b.owner)
    >>> shim = b.updateLifecycleStatus(b.owner)
    >>> flush_database_updates()

And if we ask just for specs, we get BOTH the incomplete and the
complete ones that have been accepted.

    >>> for spec in onezero.specifications(None):
    ...     print(spec.name, spec.is_complete, spec.goalstatus.title)
    ...
    a True Accepted
    b False Accepted

We can search for text in specifications (in this case there are no
matches):

    >>> print(len(list(onezero.specifications(None, filter=["new"]))))
    0


Lifecycle Management
--------------------

In the example above, we use the acceptBy and updateLifecycleStatus methods on
a specification. These help us keep the full record of who moved the spec
through each relevant stage of its existence.

    >>> b.goal_decider is None
    False
    >>> print(b.goal_decider.name)
    carlos
    >>> b.date_completed is None
    True

There's a method which will tell us if status changes we have just made will
change the overall state of the spec to "completed".

    >>> jdub = getUtility(IPersonSet).getByName("jdub")
    >>> b.definition_status = SpecificationDefinitionStatus.APPROVED
    >>> b.implementation_status = (
    ...     SpecificationImplementationStatus.INFORMATIONAL
    ... )
    >>> print(b.updateLifecycleStatus(jdub).title)
    Complete
    >>> print(b.completer.name)
    jdub
    >>> b.date_completed is None
    False


Drivers
-------

Products, project groups and product series have drivers, who are people
that have permission to approve bugs and features for specific releases. The
rules are that:

 1. a "driver" can be set on either ProjectGroup, Product or ProductSeries

 2. drivers are only actually relevant on a ProductSeries, because that's
    the granularity at which we track spec/bug targeting

 3. the important attribute is ".drivers" on a productseries, it is
    calculated based on the combination of owners and drivers in the
    series, product and project group. It is a LIST of drivers, which might
    be empty, or have one, two or three people/teams in it.

 4. the list includes the explicitly set drivers from series, product
    and project group

 5. if there are no explicitly set drivers, then:
      - if there is a project group, then the list is the projectgroup.owner
      - if there is no project group, then the list is the product.owner in
    other words, we use the "highest" owner as the fallback, which is
    either the product owner or the project group owner if there is a
    project group.

We test these rules below. We will create the project group, product and
series directly so that we don't have to deal with security permissions
checks when setting and resetting the driver attributes.

    >>> from lp.services.database.sqlbase import flush_database_updates
    >>> login("foo.bar@canonical.com")
    >>> carlos = getUtility(IPersonSet).getByName("carlos")
    >>> mark = getUtility(IPersonSet).getByName("mark")
    >>> jblack = getUtility(IPersonSet).getByName("jblack")

    >>> projectgroup = factory.makeProject(
    ...     name="testproj",
    ...     displayname="Test Project",
    ...     title="Test Project Title",
    ...     homepageurl="http://foo.com/url",
    ...     summary="summary",
    ...     description="description",
    ...     owner=carlos,
    ... )
    >>> product = factory.makeProduct(
    ...     owner=mark,
    ...     name="testprod",
    ...     displayname="Test Product",
    ...     title="Test product title",
    ...     summary="summary",
    ...     projectgroup=projectgroup,
    ... )
    >>> series = factory.makeProductSeries(
    ...     owner=jblack,
    ...     name="1.0",
    ...     product=product,
    ...     summary="Series summary",
    ... )


First, lets see what we get for the series drivers before we have
anything actually set.

If there is a project group on the product, we would expect the project
group owner:

    >>> print(series.product.projectgroup.name)
    testproj
    >>> for d in series.drivers:
    ...     print(d.name)
    ...
    carlos

If there is NO project group on the product, then we expect the product
owner:

    >>> product.projectgroup = None
    >>> for d in series.drivers:
    ...     print(d.name)
    ...
    mark

Now let's put the project group back:

    >>> product.projectgroup = projectgroup.id
    >>> flush_database_updates()

Edgar and cprov will be the drivers.

    >>> cprov = getUtility(IPersonSet).getByName("cprov")
    >>> edgar = getUtility(IPersonSet).getByName("edgar")

Edgar becomes the driver of the project group and thus also drives the
series.

    >>> projectgroup.driver = edgar
    >>> for d in series.drivers:
    ...     print(d.name)
    ...
    edgar

In addition cprov is made driver of the series. Both are drivers now.

    >>> series.driver = cprov
    >>> for d in series.drivers:
    ...     print(d.name)
    ...
    cprov
    edgar

With just a driver on the series, the owner of the project group is reported
as driver, too.

    >>> projectgroup.driver = None
    >>> for d in series.drivers:
    ...     print(d.name)
    ...
    carlos
    cprov

Without a project group, the driver role falls back to the product owner.

    >>> product.projectgroup = None
    >>> for d in series.drivers:
    ...     print(d.name)
    ...
    cprov
    mark
