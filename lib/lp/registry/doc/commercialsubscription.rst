========================
Commercial Subscriptions
========================

The CommercialSubscription class is used to track whether a project,
which does not qualify for free hosting, has an unexpired subscription.

    >>> from zope.component import getUtility
    >>> from lp.registry.interfaces.product import IProductSet
    >>> from lp.testing import login, ANONYMOUS
    >>> login("no-priv@canonical.com")

An open source project should not have a commercial subscription,
indicated by 'None'.

    >>> product_set = getUtility(IProductSet)
    >>> bzr = product_set.getByName("bzr")
    >>> print(bzr.commercial_subscription)
    None

Make a commercial subscription.

    >>> _ = factory.makeCommercialSubscription(bzr)

Commercial subscriptions have zope.Public permissions for reading.

    >>> from lp.services.webapp.authorization import check_permission
    >>> login(ANONYMOUS)
    >>> check_permission("zope.Public", bzr.commercial_subscription)
    True
    >>> print(bzr.commercial_subscription.product.name)
    bzr

For modification, launchpad.Commercial is required.  Anonymous users,
regular users, and the project owner all are denied.

    >>> check_permission("launchpad.Commercial", bzr.commercial_subscription)
    False

    >>> login("no-priv@canonical.com")
    >>> check_permission("launchpad.Commercial", bzr.commercial_subscription)
    False

    >>> ignored = login_person(bzr.owner)
    >>> check_permission("launchpad.Commercial", bzr.commercial_subscription)
    False

A member of the commercial admins team does have modification privileges.

    >>> from lp.app.interfaces.launchpad import ILaunchpadCelebrities
    >>> celebs = getUtility(ILaunchpadCelebrities)
    >>> commercial_admin = celebs.commercial_admin
    >>> login("commercial-member@canonical.com")
    >>> commercial_member = getUtility(ILaunchBag).user
    >>> commercial_member.inTeam(commercial_admin)
    True
    >>> check_permission("launchpad.Commercial", bzr.commercial_subscription)
    True

The commercial_subscription_is_due attribute is true if the licence
does not qualify for free hosting and the commercial subscription
is inactive or about to expire.  The is_permitted attribute is
true if the project either has a qualifying licence or has an active
commercial subscription. The qualifies_for_free_hosting attribute is
true, if automatically qualifying licences are the only ones selected,
or if the licence has been reviewed and been manually approved.

The commercial subscription is about to expire here.

    >>> from datetime import date, datetime, timedelta, timezone
    >>> from zope.security.proxy import removeSecurityProxy
    >>> from lp.registry.interfaces.product import License
    >>> login("foo.bar@canonical.com")
    >>> bzr.licenses = [License.OTHER_PROPRIETARY]
    >>> subscription = removeSecurityProxy(bzr.commercial_subscription)
    >>> subscription.date_expires = datetime.now(timezone.utc) + timedelta(29)
    >>> bzr.qualifies_for_free_hosting
    False
    >>> bzr.commercial_subscription_is_due
    True
    >>> bzr.commercial_subscription.is_active
    True
    >>> bzr.is_permitted
    True

The subscription will not expire for more than 30 days so a new
subscription is not due yet.

    >>> subscription.date_expires = datetime.now(timezone.utc) + timedelta(31)
    >>> bzr.commercial_subscription_is_due
    False

Make the subscription no longer active.

    >>> subscription.date_expires = subscription.date_starts
    >>> bzr.commercial_subscription.is_active
    False
    >>> bzr.commercial_subscription_is_due
    True
    >>> bzr.is_permitted
    False

The qualifies_for_free_hosting attribute is False
if the product has License.OTHER_PROPRIETARY.

    >>> bzr.qualifies_for_free_hosting
    False
    >>> bzr.licenses = [License.GNU_GPL_V2]
    >>> bzr.qualifies_for_free_hosting
    True

The license_approved attribute is used to manually approve an
OTHER_OPEN_SOURCE licence or a project with additional licence info
as being "good enough" to use Launchpad. The license_approved property
can only be set on a product that does not have OTHER_PROPRIETARY
included as one of the licences.

    >>> bzr.license_info = "bar"
    >>> bzr.project_reviewed = True
    >>> bzr.license_approved = True

    >>> print(bzr.license_info)
    bar
    >>> bzr.project_reviewed
    True
    >>> bzr.license_approved
    True

Setting license_approved implies that the licence has been reviewed,
so project_reviewed is set automatically.

    >>> bzr.project_reviewed = False
    >>> bzr.license_approved = True
    >>> bzr.project_reviewed
    True

Set the bzr licence to Other/Open Source and Other/Proprietary.  It
may not be approved because Other/Proprietary requires a commercial
subscription.

    >>> bzr.licenses = [License.OTHER_OPEN_SOURCE, License.OTHER_PROPRIETARY]
    >>> bzr.project_reviewed = True
    >>> bzr.license_approved = True
    Traceback (most recent call last):
    ...
    ValueError: Projects without a licence or have 'Other/Proprietary'
    may not be approved.

A project with an Other/Open Source licence or additional licence info that
is reviewed, but not approved requires a commercial subscription.

    >>> bzr.licenses = [License.OTHER_OPEN_SOURCE]
    >>> bzr.project_reviewed = True
    >>> bzr.qualifies_for_free_hosting
    False

When the products licence is OTHER_OPEN_SOURCE or the license_info
attribute contains a description of another licence, the product
requires approval for free hosting. The qualifies_for_free_hosting
attribute is false for products that have licences that required
approval, but were not approved.

However, qualifies_for_free_hosting remains true until
it has been reviewed (project_reviewed is set to true). The
OTHER_PROPRIETARY Licence does not need to be reviewed as do the
OTHER_OPEN_SOURCE licence or an unknown licence in license_info.

    >>> bzr.license_approved
    False
    >>> bzr.license_info = "blah"
    >>> bzr.qualifies_for_free_hosting, bzr.commercial_subscription_is_due
    (True, False)

    >>> bzr.project_reviewed = True
    >>> bzr.qualifies_for_free_hosting, bzr.commercial_subscription_is_due
    (False, True)

    >>> bzr.license_info = ""
    >>> bzr.licenses = [License.OTHER_OPEN_SOURCE]
    >>> bzr.qualifies_for_free_hosting, bzr.commercial_subscription_is_due
    (True, False)

    >>> bzr.project_reviewed = True
    >>> bzr.qualifies_for_free_hosting, bzr.commercial_subscription_is_due
    (False, True)

When the licence is manually approved, a product qualifies for free
hosting; there is no commercial subscription due.

    >>> bzr.license_approved = True
    >>> bzr.qualifies_for_free_hosting, bzr.commercial_subscription_is_due
    (True, False)

=======================
Product Licence Reviews
=======================

The forReview() method allows searching for products whose licence needs to
be reviewed. You can search by text in the Product table's full text index
as well as the license_info field. The results are ordered by date created
then display name.

    >>> from lp.services.database.sqlbase import flush_database_updates
    >>> bzr.licenses = [License.GNU_GPL_V2, License.ECLIPSE]
    >>> flush_database_updates()
    >>> for product in product_set.forReview(
    ...     commercial_member, search_text="gnome"
    ... ):
    ...     print(product.displayname)
    python gnome2 dev
    Evolution
    GNOME Terminal
    Gnome Applets
    gnomebaker

The license_info field is also searched for matching search_text:

    >>> bzr.license_info = "Code in /contrib is under a mit-like licence."
    >>> for product in product_set.forReview(
    ...     commercial_member, search_text="mit"
    ... ):
    ...     print(product.name)
    bzr

The whiteboard field is also searched for matching search_text:

    >>> from lp.testing import celebrity_logged_in
    >>> with celebrity_logged_in("registry_experts"):
    ...     bzr.reviewer_whiteboard = (
    ...         "cc-nc discriminates against commercial uses."
    ...     )
    ...
    >>> for product in product_set.forReview(
    ...     commercial_member, search_text="cc-nc"
    ... ):
    ...     print(product.name)
    bzr

You can search for whether the product is active or not.

    >>> for product in product_set.forReview(commercial_member, active=False):
    ...     print(product.name)
    ...
    python-gnome2-dev
    unassigned

You can search for whether the product is marked reviewed or not.

    >>> for product in product_set.forReview(
    ...     commercial_member, project_reviewed=True
    ... ):
    ...     print(product.name)
    python-gnome2-dev
    unassigned
    alsa-utils
    obsolete-junk

You can search for products by licence. This will match products with
any one of the licences listed.

    >>> for product in product_set.forReview(
    ...     commercial_member, licenses=[License.GNU_GPL_V2, License.BSD]
    ... ):
    ...     print(product.name)
    bzr

It is possible to search for problem project that have been reviewed, but
not approved

    >>> for product in product_set.forReview(
    ...     commercial_member, project_reviewed=True, license_approved=False
    ... ):
    ...     print(product.name)
    python-gnome2-dev
    unassigned
    alsa-utils

You can search for products based on a date range in which the product
was created.

    >>> for product in product_set.forReview(
    ...     commercial_member,
    ...     search_text="bzr",
    ...     created_after=bzr.datecreated,
    ...     created_before=bzr.datecreated,
    ... ):
    ...     print(product.name)
    bzr

You can search for products based on the expiration date of
its commercial subscription.

    >>> date_expires = bzr.commercial_subscription.date_expires
    >>> for product in product_set.forReview(
    ...     commercial_member,
    ...     search_text="bzr",
    ...     subscription_expires_after=date_expires,
    ...     subscription_expires_before=date_expires,
    ... ):
    ...     print(product.name)
    bzr

You can also search using a datetime.date object, since that is what
the web form delivers.

    >>> one_day = timedelta(days=1)
    >>> date_expires = date_expires.date()
    >>> early_date = date(1980, 1, 1)
    >>> late_date = date_expires + timedelta(days=365 * 100)
    >>> for product in product_set.forReview(
    ...     commercial_member,
    ...     search_text="bzr",
    ...     subscription_expires_after=date_expires,
    ...     subscription_expires_before=date_expires + one_day,
    ...     created_after=early_date,
    ...     created_before=late_date,
    ...     subscription_modified_after=early_date,
    ...     subscription_modified_before=late_date,
    ... ):
    ...     print(product.name)
    bzr

A reviewer can search for projects without a commercial subscription.

    >>> for product in product_set.forReview(
    ...     commercial_member,
    ...     has_subscription=False,
    ...     licenses=[License.OTHER_PROPRIETARY],
    ... ):
    ...     print(product.name)
    mega-money-maker

You can search for products based on the date when
their commercial subscription was modified.

    >>> date_last_modified = bzr.commercial_subscription.date_last_modified
    >>> for product in product_set.forReview(
    ...     commercial_member,
    ...     search_text="bzr",
    ...     subscription_modified_after=date_last_modified,
    ...     subscription_modified_before=date_last_modified,
    ... ):
    ...     print(product.name)
    bzr

All the products are returned when no parameters are passed in.

    >>> from lp.registry.model.product import Product
    >>> from lp.services.database.interfaces import IStore
    >>> review_listing = product_set.forReview(commercial_member)
    >>> review_listing.count() == IStore(Product).find(Product).count()
    True

The full text search will not match strings with dots in their name
but a clause is included to search specifically for the name.

    >>> new_product = factory.makeProduct(name="abc.com")
    >>> for product in product_set.forReview(
    ...     commercial_member, search_text="abc.com"
    ... ):
    ...     print(product.name)
    abc.com

The use of 'forReview' is limited to users with launchpad.Moderate.
No Privileges Person cannot access 'forReview'.

    >>> login("no-priv@canonical.com")
    >>> check_permission("launchpad.Moderate", product_set)
    False
    >>> gnome = product_set.forReview(commercial_member, search_text="gnome")
    Traceback (most recent call last):
    ...
    zope.security.interfaces.Unauthorized: ... 'forReview',
    'launchpad.Moderate'...

Members of the registry experts celebrity have permission to review
IProduct and IProjectGroup objects and access an IProjectGroupSet.

    >>> from lp.registry.interfaces.projectgroup import IProjectGroupSet

    >>> project_set = getUtility(IProjectGroupSet)
    >>> product = factory.makeProduct(name="dog")
    >>> project = factory.makeProject(name="cat")

    >>> registry_member = factory.makePerson()
    >>> registry = celebs.registry_experts
    >>> login("foo.bar@canonical.com")
    >>> ignored = registry.addMember(registry_member, registry.teamowner)
    >>> ignored = login_person(registry_member)
    >>> check_permission("launchpad.Moderate", project_set)
    True
    >>> check_permission("launchpad.Moderate", project)
    True
    >>> check_permission("launchpad.Moderate", product)
    True
