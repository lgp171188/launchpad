Official Bug Tags
=================

Distributions and products can define official bug tags.

    >>> from zope.component import getUtility
    >>> from lp.registry.interfaces.distribution import IDistributionSet
    >>> from lp.registry.interfaces.product import IProductSet
    >>> from lp.services.database.interfaces import IStore
    >>> from lp.bugs.model.bugtarget import OfficialBugTag
    >>> store = IStore(OfficialBugTag)

    >>> ubuntu = getUtility(IDistributionSet).getByName("ubuntu")
    >>> distro_tag = OfficialBugTag()
    >>> distro_tag.tag = "PCI"
    >>> distro_tag.target = ubuntu
    >>> store.add(distro_tag)
    <OfficialBugTag object>

    >>> firefox = getUtility(IProductSet).getByName("firefox")
    >>> product_tag = OfficialBugTag()
    >>> product_tag.tag = "bar"
    >>> product_tag.target = firefox
    >>> store.add(product_tag)
    <OfficialBugTag object>

We can add the same bug tag for different products and distributions.

    >>> distro_tag2 = OfficialBugTag()
    >>> distro_tag2.tag = "foo"
    >>> distro_tag2.distribution = ubuntu
    >>> store.add(distro_tag2)
    <OfficialBugTag object>
    >>> store.flush()

But bug tags must be unique for each product and distribution.

    >>> distro_tag3 = OfficialBugTag()
    >>> distro_tag3.tag = "PCI"
    >>> distro_tag3.distribution = ubuntu
    >>> store.add(distro_tag3)
    <OfficialBugTag object>
    >>> store.flush()
    Traceback (most recent call last):
    storm.database.UniqueViolation: ...

    >>> import transaction
    >>> transaction.abort()


Targets of official bug tags
----------------------------

Distribution owners and other persons with the permission launchpad.Edit
can add and remove official bug tags by calling addOfficialBugTag()
or removeOfficialBugTag(), respectively.

    >>> login("colin.watson@ubuntulinux.com")
    >>> ubuntu.addOfficialBugTag("foo")
    >>> ubuntu.addOfficialBugTag("bar")
    >>> result_set = store.find(
    ...     OfficialBugTag, OfficialBugTag.distribution == ubuntu
    ... )
    >>> result_set = result_set.order_by(OfficialBugTag.tag)
    >>> for tag in result_set:
    ...     print(tag.tag)
    ...
    bar
    foo

    >>> ubuntu.removeOfficialBugTag("foo")
    >>> result_set = store.find(
    ...     OfficialBugTag, OfficialBugTag.distribution == ubuntu
    ... )
    >>> for tag in result_set:
    ...     print(tag.tag)
    ...
    bar

    >>> login("test@canonical.com")
    >>> firefox.addOfficialBugTag("foo")
    >>> result_set = store.find(
    ...     OfficialBugTag, OfficialBugTag.product == firefox
    ... )
    >>> for tag in result_set:
    ...     print(tag.tag)
    ...
    foo

    >>> firefox.removeOfficialBugTag("foo")
    >>> result_set = store.find(
    ...     OfficialBugTag, OfficialBugTag.product == firefox
    ... )
    >>> print(result_set.count())
    0

    >>> transaction.commit()

The attempt to add an existing tag a second time succeeds but does not
change the data.

    >>> login("colin.watson@ubuntulinux.com")
    >>> ubuntu.addOfficialBugTag("bar")
    >>> result_set = store.find(
    ...     OfficialBugTag, OfficialBugTag.distribution == ubuntu
    ... )
    >>> result_set = result_set.order_by(OfficialBugTag.tag)
    >>> for tag in result_set:
    ...     print(tag.tag)
    ...
    bar

Similarly, deleting an not-existent tag does not lead to an error, but
does not change the data either.

    >>> ubuntu.removeOfficialBugTag("foo")
    >>> result_set = store.find(
    ...     OfficialBugTag, OfficialBugTag.distribution == ubuntu
    ... )
    >>> for tag in result_set:
    ...     print(tag.tag)
    ...
    bar

Ordinary users cannot add and remove official bug tags.

    >>> login("no-priv@canonical.com")
    >>> ubuntu.addOfficialBugTag("foo")
    Traceback (most recent call last):
    ...
    zope.security.interfaces.Unauthorized:
    (<Distribution 'Ubuntu' (ubuntu)>, 'addOfficialBugTag', 'launchpad.Edit')

    >>> ubuntu.removeOfficialBugTag("foo")
    Traceback (most recent call last):
    ...
    zope.security.interfaces.Unauthorized:
    (<Distribution 'Ubuntu' (ubuntu)>, 'removeOfficialBugTag',
     'launchpad.Edit')

    >>> firefox.addOfficialBugTag("foo")
    Traceback (most recent call last):
    ...
    zope.security.interfaces.Unauthorized:
    (<Product object>, 'addOfficialBugTag', 'launchpad.Edit')

    >>> firefox.removeOfficialBugTag("foo")
    Traceback (most recent call last):
    ...
    zope.security.interfaces.Unauthorized:
    (<Product object>, 'removeOfficialBugTag', 'launchpad.Edit')

Official tags are accessible as a list property of official tag targets.

    >>> for tag in ubuntu.official_bug_tags:
    ...     print(tag)
    ...
    bar

To set the list, the user must have edit permissions for the target.

    >>> login("colin.watson@ubuntulinux.com")

Setting the list creates any new tags appearing in the list.

    >>> ubuntu.official_bug_tags = ["foo", "bar"]
    >>> for tag in ubuntu.official_bug_tags:
    ...     print(tag)
    ...
    bar
    foo

Any existing tags missing from the list are removed.

    >>> ubuntu.official_bug_tags = ["foo"]
    >>> for tag in ubuntu.official_bug_tags:
    ...     print(tag)
    ...
    foo

The list is publicly readable.

    >>> login(ANONYMOUS)
    >>> for tag in ubuntu.official_bug_tags:
    ...     print(tag)
    ...
    foo

But only writable for users with edit permissions.

    >>> login("no-priv@canonical.com")
    >>> ubuntu.official_bug_tags = ["foo", "bar"]
    Traceback (most recent call last):
    ...
    zope.security.interfaces.Unauthorized:
    (<Distribution 'Ubuntu' (ubuntu)>, 'official_bug_tags',
     'launchpad.BugSupervisor')

The same is available for products.

    >>> login("test@canonical.com")
    >>> firefox.official_bug_tags = ["foo", "bar"]
    >>> login(ANONYMOUS)
    >>> for tag in firefox.official_bug_tags:
    ...     print(tag)
    ...
    bar
    foo


Official tags for additional bug targets
----------------------------------------

All IHasBugs implementations provide an official_bug_tags property. They are
taken from the relevant distribution or product.

Distribution series and distribution source package get the official tags of
their parent distribution.

    >>> for tag in ubuntu.getSeries("hoary").official_bug_tags:
    ...     print(tag)
    ...
    foo

    >>> login("test@canonical.com")
    >>> for tag in (
    ...     ubuntu.getSeries("hoary")
    ...     .getSourcePackage("alsa-utils")
    ...     .official_bug_tags
    ... ):
    ...     print(tag)
    foo
    >>> login(ANONYMOUS)

    >>> for tag in ubuntu.getSourcePackage("alsa-utils").official_bug_tags:
    ...     print(tag)
    ...
    foo

Product series gets the tags of the parent product.

    >>> for tag in firefox.getSeries("1.0").official_bug_tags:
    ...     print(tag)
    ...
    bar
    foo

Project group gets the union of all the tags available for its products.

    >>> login("test@canonical.com")
    >>> from lp.registry.interfaces.projectgroup import IProjectGroupSet
    >>> thunderbird = getUtility(IProductSet).getByName("thunderbird")
    >>> thunderbird.official_bug_tags = ["baz"]
    >>> login("no-priv@canonical.com")
    >>> mozilla = getUtility(IProjectGroupSet).getByName("mozilla")
    >>> for tag in mozilla.official_bug_tags:
    ...     print(tag)
    ...
    bar
    baz
    foo
    >>> login(ANONYMOUS)

Milestone gets the tags of the relevant product.

    >>> for tag in firefox.getMilestone("1.0").official_bug_tags:
    ...     print(tag)
    ...
    bar
    foo
