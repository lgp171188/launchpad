DistributionSourcePackageView
=============================

The DistributionSourcePackageView is used to present a source
package within a distribution.

    # Setup the breezy autotest distroseries
    >>> login("foo.bar@canonical.com")
    >>> from lp.soyuz.tests.test_publishing import SoyuzTestPublisher
    >>> publisher = SoyuzTestPublisher()
    >>> publisher.prepareBreezyAutotest()
    >>> ubuntutest = publisher.ubuntutest
    >>> from lp.registry.interfaces.series import SeriesStatus
    >>> publisher.distroseries.status = SeriesStatus.DEVELOPMENT

    # Publish the source 'gedit' in the ubuntutest main archive.
    >>> from datetime import datetime, timezone
    >>> from lp.soyuz.enums import PackagePublishingStatus
    >>> gedit_main_src_hist = publisher.getPubSource(
    ...     sourcename="gedit",
    ...     archive=ubuntutest.main_archive,
    ...     date_uploaded=datetime(2010, 12, 30, tzinfo=timezone.utc),
    ...     status=PackagePublishingStatus.PUBLISHED,
    ... )

The view has an active_series property that provides a sorted list of active
series.

    >>> eel_main_src_hist = publisher.getPubSource(
    ...     sourcename="eel",
    ...     archive=ubuntutest.main_archive,
    ...     date_uploaded=datetime(2010, 12, 30, tzinfo=timezone.utc),
    ...     status=PackagePublishingStatus.PUBLISHED,
    ...     distroseries=ubuntutest.getSeries("breezy-autotest"),
    ... )
    >>> earliest_series = factory.makeDistroSeries(
    ...     distribution=ubuntutest, version="1.1", name="earliest"
    ... )
    >>> eel_main_src_hist = publisher.getPubSource(
    ...     sourcename="eel",
    ...     archive=ubuntutest.main_archive,
    ...     date_uploaded=datetime(2010, 12, 30, tzinfo=timezone.utc),
    ...     status=PackagePublishingStatus.PUBLISHED,
    ...     distroseries=earliest_series,
    ... )
    >>> latest_series = factory.makeDistroSeries(
    ...     distribution=ubuntutest, version="10.04", name="latest"
    ... )
    >>> eel_main_src_hist = publisher.getPubSource(
    ...     sourcename="eel",
    ...     archive=ubuntutest.main_archive,
    ...     date_uploaded=datetime(2010, 12, 30, tzinfo=timezone.utc),
    ...     status=PackagePublishingStatus.PUBLISHED,
    ...     distroseries=latest_series,
    ... )
    >>> transaction.commit()
    >>> ubuntu_eel = ubuntutest.getSourcePackage("eel")
    >>> view = create_initialized_view(
    ...     ubuntu_eel, name="+index", principal=factory.makePerson()
    ... )
    >>> for series in view.active_series:
    ...     print(series.name, series.version)
    ...
    latest 10.04
    breezy-autotest 6.6.6
    earliest 1.1

The view has a latest_sourcepackage attribute whose series is the same
as the first series from view.active_series.

    >>> latest_series = view.latest_sourcepackage.distroseries
    >>> print(latest_series.name, latest_series.version)
    latest 10.04

The view has a version_table attribute for populating a table. The "Set
upstream link" action should only be displayed for series with the status
CURRENT or DEVELOPMENT.

    >>> view.active_series[1].status = SeriesStatus.CURRENT
    >>> view.active_series[2].status = SeriesStatus.SUPPORTED
    >>> for row in view.version_table:
    ...     if row.get("distroseries") is not None:
    ...         set_upstream_link = ""
    ...         if row["show_set_upstream_link"] is True:
    ...             set_upstream_link = "  set-upstream-link"
    ...         ds = row["distroseries"]
    ...         print(
    ...             "%-16s %-12s %s"
    ...             % (ds.name, ds.status.name, set_upstream_link)
    ...         )
    ...
    latest           DEVELOPMENT    set-upstream-link
    breezy-autotest  CURRENT        set-upstream-link
    earliest         SUPPORTED

If the latest sourcepackage does not have a link to an upstream project,
this page will display a form to add one.

    >>> from lp.testing.pages import find_tag_by_id
    >>> upstream_portlet = find_tag_by_id(view.render(), "upstream")
    >>> print(upstream_portlet.find(id="field.actions.link")["value"])
    Link to Upstream Project


Related PPA versions
--------------------

The view includes a related_ppa_versions property which returns
a list of dictionaries describing 3 PPAs with versions of the same
package.

    # Create two PPAs to which we can publish sources.
    >>> ppa_nightly = factory.makeArchive(
    ...     name="nightly", distribution=ubuntutest
    ... )
    >>> ppa_beta = factory.makeArchive(name="beta", distribution=ubuntutest)

    # Publish gedit to both PPAs
    >>> gedit_nightly_src_breezy = publisher.getPubSource(
    ...     sourcename="gedit",
    ...     archive=ppa_nightly,
    ...     creator=ppa_nightly.owner,
    ...     status=PackagePublishingStatus.PUBLISHED,
    ...     version="0.8.2n3",
    ... )
    >>> gedit_beta_src_breezy = publisher.getPubSource(
    ...     sourcename="gedit",
    ...     archive=ppa_beta,
    ...     creator=ppa_beta.owner,
    ...     status=PackagePublishingStatus.PUBLISHED,
    ...     version="0.8.1",
    ... )
    >>> gedit_beta_src_hoary = publisher.getPubSource(
    ...     sourcename="gedit",
    ...     archive=ppa_beta,
    ...     creator=ppa_nightly.owner,
    ...     status=PackagePublishingStatus.PUBLISHED,
    ...     version="0.8.0",
    ...     distroseries=ubuntutest.getSeries("hoary-test"),
    ... )

    # Give the creators of the above source packages some soyuz
    # karma for their efforts.
    >>> from lp.registry.model.karma import KarmaCategory
    >>> from lp.registry.model.karma import KarmaTotalCache
    >>> from lp.services.database.interfaces import IStore
    >>> from lp.testing.dbuser import dbuser
    >>> soyuz_category = (
    ...     IStore(KarmaCategory).find(KarmaCategory, name="soyuz").one()
    ... )
    >>> sourcepackagerelease = gedit_nightly_src_breezy.sourcepackagerelease
    >>> gedit_name = sourcepackagerelease.sourcepackagename
    >>> ppa_beta_owner = ppa_beta.owner
    >>> ppa_nightly_owner = ppa_nightly.owner
    >>> with dbuser("karma"):
    ...     cache_entry = KarmaTotalCache(
    ...         person=ppa_beta_owner, karma_total=200
    ...     )
    ...     cache_entry = KarmaTotalCache(
    ...         person=ppa_nightly_owner, karma_total=201
    ...     )
    ...

    # Because our connection has been closed during the reconnect, we
    # need to get the distro and source package again.
    >>> from lp.registry.interfaces.distribution import IDistributionSet
    >>> ubuntutest = getUtility(IDistributionSet)["ubuntutest"]
    >>> ubuntu_gedit = ubuntutest.getSourcePackage("gedit")
    >>> ubuntu_gedit_view = create_initialized_view(
    ...     ubuntu_gedit, name="+index"
    ... )
    >>> for archive_pub in ubuntu_gedit_view.related_ppa_versions:
    ...     print(
    ...         "%s - %s"
    ...         % (
    ...             archive_pub["archive"].displayname,
    ...             archive_pub["versions"],
    ...         )
    ...     )
    ...
    PPA named nightly for Person-name... - Breezy Badger Autotest (0.8.2n3)
    PPA named beta for Person-name... - Breezy Badger Autotest (0.8.1),
        Hoary Mock (0.8.0)

The view also calculates the url for finding further PPA versions.

    >>> print(ubuntu_gedit_view.further_ppa_versions_url)
    http://launchpad.test/ubuntutest/+ppas?name_filter=gedit


Editing a distribution source package
-------------------------------------

The +edit view allows users to edit a DistributionSourcePackage. The
view provides a label, page_title and cancel_url.

    >>> distribution = factory.makeDistribution(
    ...     name="youbuntu", displayname="Youbuntu"
    ... )
    >>> sourcepackagename = factory.makeSourcePackageName(name="bonkers")
    >>> package = factory.makeDistributionSourcePackage(
    ...     sourcepackagename=sourcepackagename, distribution=distribution
    ... )
    >>> view = create_initialized_view(package, "+edit")
    >>> print(view.label)
    Edit ...bonkers... package in Youbuntu

    >>> print(view.page_title)
    Edit ...bonkers... package in Youbuntu

    >>> print(view.cancel_url)
    http://launchpad.test/youbuntu/+source/bonkers

The view allows the user the set the bug_reporting_guidelines field.

    >>> view.field_names
    ['bug_reporting_guidelines', 'content_templates',
    'bug_reported_acknowledgement',
    'enable_bugfiling_duplicate_search']

    >>> print(package.bug_reporting_guidelines)
    None

    >>> form = {
    ...     "field.bug_reporting_guidelines": "guidelines",
    ...     "field.actions.change": "Change",
    ... }
    >>> view = create_initialized_view(package, "+edit", form=form)
    >>> view.errors
    []
    >>> print(view.next_url)
    http://launchpad.test/youbuntu/+source/bonkers

    >>> print(package.bug_reporting_guidelines)
    guidelines
