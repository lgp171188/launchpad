==============================
Archive View Classes and Pages
==============================

Let's use Celso's PPA for the tests.

    >>> from lp.registry.interfaces.person import IPersonSet
    >>> cprov = getUtility(IPersonSet).getByName("cprov")


ArchiveView
===========

The ArchiveView includes a few helper methods that make it easier to
display different types of archives (copy archives, ppas).

First let's create a copy archive:

    >>> from lp.registry.interfaces.distribution import IDistributionSet
    >>> from lp.testing.factory import (
    ...     remove_security_proxy_and_shout_at_engineer,
    ... )
    >>> ubuntu = getUtility(IDistributionSet)["ubuntu"]
    >>> copy_location = factory.makeCopyArchiveLocation(
    ...     distribution=ubuntu, name="intrepid-security-rebuild"
    ... )
    >>> copy_archive = remove_security_proxy_and_shout_at_engineer(
    ...     copy_location
    ... ).archive

And let's create two views to compare:

    >>> ppa_archive_view = create_initialized_view(
    ...     cprov.archive, name="+index"
    ... )
    >>> copy_archive_view = create_initialized_view(
    ...     copy_archive, name="+index"
    ... )

The ArchiveView includes an archive_url property that will return the
archive url if it is available (ie. an active archive that is not a copy)
and None otherwise:

    >>> print(ppa_archive_view.archive_url)
    http://ppa.launchpad.test/cprov/ppa/ubuntu
    >>> print(copy_archive_view.archive_url)
    None

The ArchiveView includes an archive_label property that returns either
the string 'PPA' or 'archive' depending on whether the archive is a PPA
(this is mainly for branding purposes):

    >>> print(ppa_archive_view.archive_label)
    PPA
    >>> print(copy_archive_view.archive_label)
    archive

The ArchiveView provides the html for the inline description editing widget.

    >>> print(ppa_archive_view.archive_description_html.title)
    PPA description

For convenience the ArchiveView also includes a build_counters property
that returns a dict of the build count summary for the archive:

    >>> for key, value in sorted(ppa_archive_view.build_counters.items()):
    ...     print("%s: %d" % (key, value))
    ...
    failed: 1
    ...
    superseded: 0
    total: 4

An ArchiveView also includes an easy way to get any
IPackageCopyRequest's associated with an archive:

    >>> len(ppa_archive_view.package_copy_requests)
    0

    # Create a copy-request to Celso's PPA.
    >>> naked_copy_location = remove_security_proxy_and_shout_at_engineer(
    ...     copy_location
    ... )
    >>> package_copy_request = ubuntu.main_archive.requestPackageCopy(
    ...     naked_copy_location, copy_archive.owner
    ... )

    >>> len(copy_archive_view.package_copy_requests)
    1

An ArchiveView inherits the status-filter widget for filtering
packages by status.

    >>> for term in ppa_archive_view.widgets["status_filter"].vocabulary:
    ...     print(term.title)
    ...
    Published
    Superseded

An ArchiveView inherits the series-filter widget for filtering packages
by series.

    >>> for term in ppa_archive_view.widgets["series_filter"].vocabulary:
    ...     print(term.title)
    ...
    Breezy Badger Autotest
    Warty

An ArchiveView provides a helper property which returns repository
usage details in a dictionary containing:

 * Number of sources and binaries published with their appropriate
   labels;
 * Number of bytes used and permitted (quota);
 * Percentage of the used quota (with 2 degrees of precision).

We will use a helper function for printing the returned dictionary
contents.

    >>> import six

    >>> def print_repository_usage(repository_usage):
    ...     for key, value in sorted(six.iteritems(repository_usage)):
    ...         print("%s: %s" % (key, value))
    ...

Celso PPA has some packages, but still below the quota.

    >>> ppa_repository_usage = ppa_archive_view.repository_usage
    >>> print_repository_usage(ppa_repository_usage)
    binaries_size:   3
    binary_label:    3 binary packages
    quota:           1073741824
    source_label:    3 source packages
    sources_size:    9923399
    used:            9929546
    used_css_class:  green
    used_percentage: 0.92

Reducing the quota and making Celso's PPA usage above it. The quota
value is updated, percentage is limited to 100 % and the CSS class has
changed.

    >>> login("foo.bar@canonical.com")
    >>> cprov.archive.authorized_size = 1
    >>> login(ANONYMOUS)

    >>> fresh_view = create_initialized_view(cprov.archive, name="+index")
    >>> print_repository_usage(fresh_view.repository_usage)
    binaries_size:   3
    binary_label:    3 binary packages
    quota:           1048576
    source_label:    3 source packages
    sources_size:    9923399
    used:            9929546
    used_css_class:  red
    used_percentage: 100.00

The COPY archive has no packages.

    >>> copy_repository_usage = copy_archive_view.repository_usage
    >>> print_repository_usage(copy_repository_usage)
    binaries_size:   0
    binary_label:    0 binary packages
    quota:           0
    source_label:    0 source packages
    sources_size:    0
    used:            0
    used_css_class:  green
    used_percentage: 0.00

Mark's PPA has a single source, thus the package labels are adjusted
for their singular form.

    >>> mark = getUtility(IPersonSet).getByName("mark")
    >>> mark_archive_view = create_initialized_view(
    ...     mark.archive, name="+index"
    ... )
    >>> mark_repository_usage = mark_archive_view.repository_usage
    >>> print_repository_usage(mark_repository_usage)
    binaries_size:   0
    binary_label:    1 binary package
    quota:           1073741824
    source_label:    1 source package
    sources_size:    9922683
    used:            9924731
    used_css_class:  green
    used_percentage: 0.92

The authorized_size of a PPA can also be None (IE: no limit.)

    >>> login("foo.bar@canonical.com")
    >>> mark.archive.authorized_size = None
    >>> login(ANONYMOUS)

    >>> mark_archive_view = create_initialized_view(
    ...     mark.archive, name="+index"
    ... )
    >>> mark_repository_usage = mark_archive_view.repository_usage
    >>> print_repository_usage(mark_repository_usage)
    binaries_size:   0
    binary_label:    1 binary package
    quota:           0
    source_label:    1 source package
    sources_size:    9922683
    used:            9924731
    used_css_class:  green
    used_percentage: 0.00

An ArchiveView provides a batched_sources property that can be used
to get the current batch of publishing records for an archive:

    >>> for publishing in ppa_archive_view.batched_sources:
    ...     print(publishing.source_package_name)
    ...
    cdrkit
    iceweasel
    pmount

The batched_sources property will also be filtered by distroseries when
appropriate:

    >>> filtered_view = create_initialized_view(
    ...     cprov.archive,
    ...     name="+index",
    ...     method="GET",
    ...     query_string="field.series_filter=warty",
    ... )
    >>> for publishing in filtered_view.batched_sources:
    ...     print(publishing.source_package_name)
    ...
    iceweasel
    pmount

The context archive dependencies access is also encapsulated in
`ArchiveView` with the following aspects:

 * 'dependencies': cached `list` of `self.context.dependencies`.

 * 'show_dependencies': whether or not the dependencies section in the
   UI should be presented.

 * 'has_disabled_dependencies': whether or not the context archive
   uses disabled archives as dependencies.

    >>> view = create_initialized_view(cprov.archive, name="+index")

    >>> print(view.dependencies)
    []

    >>> print(view.show_dependencies)
    False

    >>> print(view.has_disabled_dependencies)
    False

'show_dependencies' is True for the PPA users, since the link for
adding new dependencies is part of the section controlled by this
flag.

    >>> login("celso.providelo@canonical.com")

    >>> view = create_initialized_view(cprov.archive, name="+index")

    >>> print(view.dependencies)
    []

    >>> print(view.show_dependencies)
    True

    >>> print(view.has_disabled_dependencies)
    False

When there are any dependencies, 'show_dependencies' becomes True also
for anonymous requests, since the dependencies are relevant to any
user.

    # Create a new PPA and add it as dependency of Celso's PPA.
    >>> login("foo.bar@canonical.com")
    >>> testing_person = factory.makePerson(name="zoing")
    >>> testing_ppa = factory.makeArchive(
    ...     distribution=ubuntu, name="ppa", owner=testing_person
    ... )
    >>> from lp.soyuz.interfaces.publishing import PackagePublishingPocket
    >>> unused = cprov.archive.addArchiveDependency(
    ...     testing_ppa, PackagePublishingPocket.RELEASE
    ... )
    >>> login(ANONYMOUS)

    >>> view = create_initialized_view(cprov.archive, name="+index")

    >>> for archive_dependency in view.dependencies:
    ...     print(archive_dependency.dependency.displayname)
    ...
    PPA for Zoing

    >>> print(view.show_dependencies)
    True

    >>> print(view.has_disabled_dependencies)
    False

When a dependency is disabled, the 'has_disabled_dependencies' flag
becomes True, but only if the viewer has permission to edit the PPA.

    # Disable the just created testing PPA.
    >>> login("foo.bar@canonical.com")
    >>> testing_ppa.disable()
    >>> login(ANONYMOUS)

    >>> view = create_initialized_view(cprov.archive, name="+index")

    >>> for archive_dependency in view.dependencies:
    ...     print(archive_dependency.dependency.displayname)
    ...
    PPA for Zoing

    >>> print(view.show_dependencies)
    True

    >>> print(view.has_disabled_dependencies)
    False

    >>> login("celso.providelo@canonical.com")
    >>> view = create_initialized_view(cprov.archive, name="+index")

    >>> for archive_dependency in view.dependencies:
    ...     print(archive_dependency.dependency.displayname)
    ...
    PPA for Zoing

    >>> print(view.show_dependencies)
    True

    >>> print(view.has_disabled_dependencies)
    True

Remove the testing PPA dependency to not influence subsequent tests.

    >>> login("foo.bar@canonical.com")
    >>> cprov.archive.removeArchiveDependency(testing_ppa)
    >>> login(ANONYMOUS)

The ArchiveView also provides the latest updates ordered by the date
they were published. We include any relevant builds for failures.

    >>> def print_latest_updates(latest_updates):
    ...     for update in latest_updates:
    ...         arch_tags = [build.arch_tag for build in update["builds"]]
    ...         print(
    ...             "%s - %s %s"
    ...             % (
    ...                 update["title"],
    ...                 update["status"],
    ...                 " ".join(arch_tags),
    ...             )
    ...         )
    ...
    >>> print_latest_updates(view.latest_updates)
    cdrkit - Failed to build: i386
    pmount - Successfully built
    iceweasel - Successfully built

Let's now update the datepublished for iceweasel to show that the ordering
is from most recent.  The view's latest_updates property is cached so we need
to reload the view.

    >>> login("celso.providelo@canonical.com")
    >>> view = create_initialized_view(cprov.archive, name="+index")
    >>> view.filtered_sources[1].setPublished()
    >>> login(ANONYMOUS)
    >>> print_latest_updates(view.latest_updates)
    cdrkit - Failed to build: i386
    pmount - Successfully built
    iceweasel - Successfully built

The ArchiveView also includes a helper method to return the number of
updates over the past month (by default).

    >>> view.num_updates_over_last_days()
    0

If we update the datecreated for some of the publishing records, those
created within the last 30 days will be included in the count, but
others will not.

    >>> from datetime import datetime, timedelta, timezone
    >>> from zope.security.proxy import removeSecurityProxy
    >>> from lp.services.database.constants import UTC_NOW
    >>> thirtyone_days_ago = datetime.now(tz=timezone.utc) - timedelta(31)
    >>> login("foo.bar@canonical.com")
    >>> removeSecurityProxy(view.filtered_sources[0]).datecreated = UTC_NOW
    >>> removeSecurityProxy(view.filtered_sources[1]).datecreated = UTC_NOW
    >>> removeSecurityProxy(view.filtered_sources[2]).datecreated = (
    ...     thirtyone_days_ago
    ... )
    >>> login(ANONYMOUS)

    >>> view.num_updates_over_last_days()
    2

We can optionally pass the number of days.

    >>> view.num_updates_over_last_days(33)
    3


The ArchiveView includes a helper to return the number of packages that
are building as well as the number of packages waiting to build.

    >>> for key, value in sorted(view.num_pkgs_building.items()):
    ...     print("%s: %d" % (key, value))
    ...
    building: 0
    total: 0
    waiting: 0

Let's set some builds appropriately to see the results.

    >>> from lp.buildmaster.enums import BuildStatus
    >>> from lp.soyuz.interfaces.binarypackagebuild import (
    ...     IBinaryPackageBuildSet,
    ... )
    >>> warty_hppa = getUtility(IDistributionSet)["ubuntu"]["warty"]["hppa"]
    >>> source = view.filtered_sources[0]
    >>> ignore = getUtility(IBinaryPackageBuildSet).new(
    ...     source.sourcepackagerelease,
    ...     view.context,
    ...     warty_hppa,
    ...     source.pocket,
    ... )
    >>> builds = getUtility(IBinaryPackageBuildSet).getBuildsForArchive(
    ...     view.context
    ... )
    >>> for build in builds:
    ...     print(build.title)
    ...
    hppa build of cdrkit 1.0 in ubuntu warty RELEASE
    hppa build of mozilla-firefox 0.9 in ubuntu warty RELEASE
    i386 build of pmount 0.1-1 in ubuntu warty RELEASE
    i386 build of iceweasel 1.0 in ubuntu warty RELEASE
    i386 build of cdrkit 1.0 in ubuntu breezy-autotest RELEASE

    >>> builds[0].updateStatus(BuildStatus.NEEDSBUILD)
    >>> builds[1].updateStatus(
    ...     BuildStatus.BUILDING, force_invalid_transition=True
    ... )
    >>> builds[2].updateStatus(
    ...     BuildStatus.BUILDING, force_invalid_transition=True
    ... )

    >>> for key, value in sorted(view.num_pkgs_building.items()):
    ...     print("%s: %d" % (key, value))
    ...
    building: 2
    total: 3
    waiting: 1

Adding a second waiting build for the cdrkit does not add to the number
of packages that are currently building.

    >>> builds[4].updateStatus(BuildStatus.NEEDSBUILD)
    >>> for key, value in sorted(view.num_pkgs_building.items()):
    ...     print("%s: %d" % (key, value))
    ...
    building: 2
    total: 3
    waiting: 1

But as soon as one of cdrkit's builds start, the package is considered
to be building:

    >>> builds[4].updateStatus(BuildStatus.BUILDING)
    >>> for key, value in sorted(view.num_pkgs_building.items()):
    ...     print("%s: %d" % (key, value))
    ...
    building: 3
    total: 3
    waiting: 0

The archive index view overrides the default series filter to use the
distroseries from the browser's user-agent, when applicable.

    >>> print(view.default_series_filter)
    None

    >>> view_warty = create_view(
    ...     cprov.archive,
    ...     name="+index",
    ...     HTTP_USER_AGENT="Mozilla/5.0 "
    ...     "(X11; U; Linux i686; en-US; rv:1.9.0.10) "
    ...     "Gecko/2009042523 Ubuntu/4.10 (whatever) "
    ...     "Firefox/3.0.10",
    ... )
    >>> view_warty.initialize()
    >>> print(view_warty.default_series_filter.name)
    warty

The archive index view also inherits the getSelectedFilterValue() method
which can be used to find the currently selected value for both filters.

    >>> print(view_warty.getSelectedFilterValue("series_filter").name)
    warty

    >>> for status in view_warty.getSelectedFilterValue("status_filter"):
    ...     print(status.name)
    ...
    PENDING
    PUBLISHED

To enable the inline editing of the archive displayname, ArchiveView
also provides a custom widget, displayname_edit_widget.

    >>> print(view.displayname_edit_widget.title)
    Edit the displayname

The view provides the is_probationary_ppa property. The archive's description
is not linkified when the owner is a probationary user to prevent spammers
from using PPAs.

    >>> login("admin@canonical.com")
    >>> cprov.archive.description = "http://example.dom/"
    >>> login(ANONYMOUS)
    >>> cprov.is_probationary
    True

    >>> print(view.archive_description_html.value)
    <p>http://example.dom/</p>

The description is HTML escaped, and not linkified even when it contains HTML
tags.

    >>> login("admin@canonical.com")
    >>> cprov.archive.description = (
    ...     '<a href="http://example.com/">http://example.com/</a>'
    ... )
    >>> login(ANONYMOUS)
    >>> print(view.archive_description_html.value)  # noqa
    <p>&lt;a href=&quot;http://example.com/&quot;&gt;http://example.com/&lt;/a&gt;</p>

The PPA description is linked when the user has made a contribution.

    >>> from lp.registry.interfaces.person import IPersonSet

    >>> login("admin@canonical.com")
    >>> contributor = getUtility(IPersonSet).getByName("name12")
    >>> contributor_ppa = factory.makeArchive(
    ...     distribution=ubuntu, name="ppa", owner=contributor
    ... )
    >>> contributor_ppa.description = "http://example.dom/"
    >>> login(ANONYMOUS)
    >>> contributor_view = create_initialized_view(
    ...     contributor_ppa, name="+index"
    ... )
    >>> contributor.is_probationary
    False

    >>> print(contributor_view.archive_description_html.value)
    <p><a rel="nofollow" href="http://example.dom/">http://...example...


ArchivePackageView
==================

This view displays detailed information about the archive packages that
is not so relevant for the PPA index page, such as a summary of build
statuses, repository usage, full publishing details and access to
copy/delete packages where appropriate.

And let's create two views to compare:

    >>> ppa_archive_view = create_initialized_view(
    ...     cprov.archive, name="+packages"
    ... )
    >>> copy_archive_view = create_initialized_view(
    ...     copy_archive, name="+packages"
    ... )

    >>> print(ppa_archive_view.page_title)
    Packages in ...PPA for Celso Providelo...

    >>> print(copy_archive_view.page_title)
    Packages in ...Copy archive intrepid-security-rebuild...

This view inherits from ArchiveViewBase and has all the
corresponding properties such as archive_url, build_counters etc.
(see ArchiveView above).

Additionally, ArchivePackageView can display a string representation
of the series supported by this archive.

    >>> print(ppa_archive_view.series_list_string)
    Breezy Badger Autotest and Warty

    >>> copy_archive_view.series_list_string
    ''

The view also has a page_title property and can indicate whether the context
is a copy archive.

    >>> print(copy_archive_view.page_title)
    Packages in ...Copy archive intrepid-security-rebuild...

    >>> copy_archive_view.is_copy
    True


ArchivePackageDeletionView
==========================

We use ArchivePackageDeletionView to provide the mechanisms used to
delete packages from a PPA via the UI.

This view is only accessible by users with 'launchpad.Edit' permission
in the archive, that would be only the PPA owner (or administrators of
the Team owning the PPA) and Launchpad administrators. See further
tests in lib/lp/soyuz/stories/ppa/xx-delete-packages.rst.

We will use the PPA owner, Celso user, to satisfy the references
required for deleting packages.

    >>> login("celso.providelo@canonical.com")

Issuing a empty request we can inspect the internal attributes used to
build the page.

    >>> view = create_initialized_view(cprov.archive, name="+delete-packages")

We query the available PUBLISHED sources and use them to build the
'selected_sources' widget.

    >>> [pub.id for pub in view.batched_sources]
    [27, 28, 29]

    >>> view.has_sources_for_display
    True

    >>> len(view.widgets.get("selected_sources").vocabulary)
    3

This view also provides package filtering by source package name, so
the user can refine the available options presented. By default all
available sources are presented with empty filter.

    >>> for pub in view.batched_sources:
    ...     print(pub.displayname)
    ...
    cdrkit 1.0 in breezy-autotest
    iceweasel 1.0 in warty
    pmount 0.1-1 in warty

Whatever is passed as 'name_filter' results in a corresponding set of
filtered results.

    >>> view = create_initialized_view(
    ...     cprov.archive,
    ...     name="+delete-packages",
    ...     query_string="field.name_filter=pmount",
    ... )

    >>> for pub in view.batched_sources:
    ...     print(pub.displayname)
    ...
    pmount 0.1-1 in warty

The 'name_filter' is decoded as UTF-8 before further processing. If it
did not, the storm query compiler would raise an error, because it can
only deal with unicode variables.

    >>> view = create_initialized_view(
    ...     cprov.archive,
    ...     name="+delete-packages",
    ...     query_string="field.name_filter=%C3%A7",
    ... )

    >>> len(list(view.batched_sources))
    0

Similarly, the sources can be filtered by series:

    >>> view = create_initialized_view(
    ...     cprov.archive,
    ...     name="+delete-packages",
    ...     query_string="field.series_filter=warty",
    ... )

    >>> for pub in view.batched_sources:
    ...     print(pub.displayname)
    ...
    iceweasel 1.0 in warty
    pmount 0.1-1 in warty

The page also uses all the built in batching features:

    >>> view = create_initialized_view(
    ...     cprov.archive,
    ...     name="+delete-packages",
    ...     query_string="field.series_filter=warty",
    ...     form={"batch": "1", "start": "1"},
    ... )

    >>> for pub in view.batched_sources:
    ...     print(pub.displayname)
    ...
    pmount 0.1-1 in warty

When submitted, deletions immediately take effect resulting in a page
which the available options already exclude the deleted items.

    >>> view = create_initialized_view(
    ...     cprov.archive,
    ...     name="+delete-packages",
    ...     form={
    ...         "field.actions.delete": "Delete Packages",
    ...         "field.name_filter": "",
    ...         "field.deletion_comment": "Go away",
    ...         "field.selected_sources": ["27", "28", "29"],
    ...         "field.selected_sources-empty-marker": 1,
    ...     },
    ... )

    >>> import transaction
    >>> transaction.commit()

If by any chance, the form containing already deleted items, is
re-POSTed to the page, the code is able to identify such invalid
situation and ignore it. See bug #185922 for reference.

    >>> view = create_initialized_view(
    ...     cprov.archive,
    ...     name="+delete-packages",
    ...     form={
    ...         "field.actions.delete": "Delete Packages",
    ...         "field.name_filter": "",
    ...         "field.deletion_comment": "Go away",
    ...         "field.selected_sources": ["27", "28", "29"],
    ...         "field.selected_sources-empty-marker": 1,
    ...     },
    ... )

    >>> len(view.errors)
    0


ArchiveEditDependenciesView
===========================

We use ArchiveEditDependenciesView to provide the mechanisms used to
add and/or remove archive dependencies for a PPA via the UI.

This view is only accessible by users with 'launchpad.Edit' permission
in the archive, that would be only the PPA owner (or administrators of
the Team owning the PPA) and Launchpad administrators. See further
tests in lib/lp/soyuz/stories/ppa/xx-edit-dependencies.rst.

We will use the PPA owner, Celso user, to play with edit-dependencies
corner-cases.

    >>> login("celso.providelo@canonical.com")

Issuing a empty request we can inspect the internal attributes used to
build the page.

    >>> view = create_initialized_view(
    ...     cprov.archive, name="+edit-dependencies"
    ... )

The view's h1 heading and leaf breadcrumb are equivalent.

    >>> print(view.label)
    Edit PPA dependencies

    >>> print(view.page_title)
    Edit PPA dependencies

There is a property indicating whether or not the context PPA has
recorded dependencies.

    >>> view.has_dependencies
    False

Also the 'selected_dependencies' form field is present, even if it is empty.

    >>> len(view.widgets.get("selected_dependencies").vocabulary)
    0

When there is no dependencies the form focus is set to the
'dependency_candidate' input field, where the user can directly type
the owner of the PPA they want to mark as dependency.

    >>> print(view.focusedElementScript())
    <!--
    setFocusByName('field.dependency_candidate');
    // -->

Let's emulate a dependency addition. Note that the form contains, a
empty 'selected_dependencies' (as it was rendered in the empty
request) and 'dependency_candidate' contains a valid PPA name.
Validation checks are documented in
lib/lp/soyuz/stories/ppa/xx-edit-dependencies.rst.

    >>> view = create_initialized_view(
    ...     cprov.archive,
    ...     name="+edit-dependencies",
    ...     form={
    ...         "field.selected_dependencies": [],
    ...         "field.dependency_candidate": "~mark/ubuntu/ppa",
    ...         "field.primary_dependencies": "UPDATES",
    ...         "field.primary_components": "ALL_COMPONENTS",
    ...         "field.actions.save": "Save",
    ...     },
    ... )

    >>> transaction.commit()

After processing the POST the view will redirect to itself.

    >>> view.next_url is not None
    True

Let's refresh the view class as it would be done in browsers.

    >>> view = create_initialized_view(
    ...     cprov.archive, name="+edit-dependencies"
    ... )

Now we can see that the view properties correctly indicate the
presence of a PPA dependency.

    >>> view.has_dependencies
    True

The 'selected_dependencies' widget has one element representing a PPA
dependency. Each element has:

 * value: dependency IArchive,
 * token: dependency IArchive.owner,
 * title: link to the dependency IArchive in Launchpad rendered as the
          dependency title.

    >>> [dependency] = view.widgets.get("selected_dependencies").vocabulary

    >>> print(dependency.value.displayname)
    PPA for Mark Shuttleworth

    >>> print(dependency.token)
    ~mark/ubuntu/ppa

    >>> print(dependency.title.escapedtext)
    <a href="http://launchpad.test/~mark/+archive/ubuntu/ppa">PPA for Mark
    Shuttleworth</a>

The form focus, now that we have a recorded dependencies, is set to the
first listed dependency.

    >>> print(view.focusedElementScript())
    <!--
    setFocusByName('field.selected_dependencies');
    // -->

The PPA dependency element 'title' is only linkified if the viewer can
view the target PPA. If Mark's PPA gets disabled, Celso can't view it
anymore, so it's not rendered as a link.

    # Disable Mark's PPA.
    >>> login("foo.bar@canonical.com")
    >>> mark.archive.disable()
    >>> login("celso.providelo@canonical.com")

    >>> view = create_initialized_view(
    ...     cprov.archive, name="+edit-dependencies"
    ... )

    >>> [dependency] = view.widgets.get("selected_dependencies").vocabulary

    >>> print(dependency.value.displayname)
    PPA for Mark Shuttleworth

    >>> print(dependency.token)
    ~mark/ubuntu/ppa

    >>> print(dependency.title)
    PPA for Mark Shuttleworth

If we remove the just-added dependency, the view gets back to its
initial/empty state.

    >>> view = create_initialized_view(
    ...     cprov.archive,
    ...     name="+edit-dependencies",
    ...     form={
    ...         "field.selected_dependencies": ["~mark/ubuntu/ppa"],
    ...         "field.dependency_candidate": "",
    ...         "field.primary_dependencies": "UPDATES",
    ...         "field.primary_components": "ALL_COMPONENTS",
    ...         "field.actions.save": "Save",
    ...     },
    ... )

After processing the POST the view will redirect to itself.

    >>> view.next_url is not None
    True

Again, the view would be refreshed by browsers.

    >>> view = create_initialized_view(
    ...     cprov.archive, name="+edit-dependencies"
    ... )

Now all the updated fields can be inspected.

    >>> view.has_dependencies
    False

    >>> print(view.focusedElementScript())
    <!--
    setFocusByName('field.dependency_candidate');
    // -->

Primary dependencies can be adjusted in the same form according to a
set of pre-defined options. By default all PPAs use the dependencies
for UPDATES pocket (see archive-dependencies.rst for more information).

    >>> primary_dependencies = view.widgets.get(
    ...     "primary_dependencies"
    ... ).vocabulary
    >>> for dependency in primary_dependencies:
    ...     print(dependency.value)
    ...
    Release
    Security
    Updates
    Proposed
    Backports

    >>> view.widgets.get("primary_dependencies")._getCurrentValue()
    <DBItem PackagePublishingPocket.UPDATES, (20) Updates>

A similar widget is used for the primary archive component overrides,
which contains two pre-defined options. By default all PPAs use all
ubuntu components available to satisfy build dependencies, i.e. the
'multiverse' component.

    >>> primary_components = view.widgets.get("primary_components").vocabulary
    >>> for term in primary_components:
    ...     if term.value is not None:
    ...         print(term.value.name)
    ...     else:
    ...         print(term.value)
    ...
    multiverse
    None

    >>> print(view.widgets.get("primary_components")._getCurrentValue().name)
    multiverse

The form validation code identifies attempts to change the primary
dependency to the same value and doesn't change anything. Even when
there is no explicit primary dependency set.

    >>> add_updates_view = create_initialized_view(
    ...     cprov.archive,
    ...     name="+edit-dependencies",
    ...     form={
    ...         "field.selected_dependencies": [],
    ...         "field.dependency_candidate": "",
    ...         "field.primary_dependencies": "UPDATES",
    ...         "field.primary_components": "ALL_COMPONENTS",
    ...         "field.actions.save": "Save",
    ...     },
    ... )

    >>> add_updates_view.widgets.get(
    ...     "primary_dependencies"
    ... )._getCurrentValue()
    <DBItem PackagePublishingPocket.UPDATES, (20) Updates>

Any other pre-defined primary dependency can be selected.

    >>> add_proposed_view = create_initialized_view(
    ...     cprov.archive,
    ...     name="+edit-dependencies",
    ...     form={
    ...         "field.selected_dependencies": [],
    ...         "field.dependency_candidate": "",
    ...         "field.primary_dependencies": "PROPOSED",
    ...         "field.primary_components": "ALL_COMPONENTS",
    ...         "field.actions.save": "Save",
    ...     },
    ... )

    >>> transaction.commit()

Once the page is reloaded, the selected primary dependency is the
current value of 'primary_dependencies' widget.

    >>> view = create_initialized_view(
    ...     cprov.archive, name="+edit-dependencies"
    ... )

    >>> view.widgets.get("primary_dependencies")._getCurrentValue()
    <DBItem PackagePublishingPocket.PROPOSED, (30) Proposed>

Primary dependencies are not listed in the 'selected_dependencies'
widget. They can only be modified via the 'primary_dependencies'
options.

    >>> len(view.widgets.get("selected_dependencies").vocabulary)
    0

As mentioned, attempts to override primary dependencies to the same
value are detected in the form validation and nothing is changed, even
when there is an explicit override.

    >>> add_proposed_view.initialize()

    >>> add_proposed_view.widgets.get(
    ...     "primary_dependencies"
    ... )._getCurrentValue()
    <DBItem PackagePublishingPocket.PROPOSED, (30) Proposed>

Attempts to override only the component dependencies are also detected
and processed correctly.

    >>> add_proposed_primary_view = create_initialized_view(
    ...     cprov.archive,
    ...     name="+edit-dependencies",
    ...     form={
    ...         "field.selected_dependencies": [],
    ...         "field.dependency_candidate": "",
    ...         "field.primary_dependencies": "PROPOSED",
    ...         "field.primary_components": "FOLLOW_PRIMARY",
    ...         "field.actions.save": "Save",
    ...     },
    ... )

    >>> transaction.commit()

    >>> view = create_initialized_view(
    ...     cprov.archive, name="+edit-dependencies"
    ... )

    >>> print(
    ...     view.widgets.get("primary_dependencies")._getCurrentValue().title
    ... )
    Proposed

    >>> print(view.widgets.get("primary_components")._getCurrentValue())
    None

Overriding the primary dependencies back to the 'default' value
(UPDATES pocket) will result in the override removal and the 'default'
option to be selected.

    >>> add_updates_view.initialize()
    >>> transaction.commit()

    >>> view = create_initialized_view(
    ...     cprov.archive, name="+edit-dependencies"
    ... )

    >>> view.widgets.get("primary_dependencies")._getCurrentValue()
    <DBItem PackagePublishingPocket.UPDATES, (20) Updates>

Dependencies on private PPAs can be only set if the user performing
the action also has permission to view the private PPA and if the
context PPA is also private.  This reduces the risk of confidential
information being leaked; it does not eliminate that risk, because it
is still possible for other people to be able to see the context PPA
who cannot see the dependencies directly, but who can see some of
their contents via builds.  We currently assume that owners of private
PPAs are aware of this risk when adding other private PPAs as
dependencies.

Before testing we will create a new team owned by Mark Shutteworth,
with a private PPA attached to it.

    >>> login("foo.bar@canonical.com")
    >>> a_team = factory.makeTeam(mark, name="pirulito-team")
    >>> team_ppa = factory.makeArchive(
    ...     distribution=ubuntu, name="ppa", owner=a_team, private=True
    ... )
    >>> transaction.commit()
    >>> login("celso.providelo@canonical.com")

Now, when Celso tries to make the new private PPA a dependency of his
PPA the form fails because he has no permission to view its contents.

    >>> add_private_form = {
    ...     "field.selected_dependencies": [],
    ...     "field.dependency_candidate": "~pirulito-team/ubuntu/ppa",
    ...     "field.primary_dependencies": "UPDATES",
    ...     "field.primary_components": "FOLLOW_PRIMARY",
    ...     "field.actions.save": "Save",
    ... }

    >>> view = create_initialized_view(
    ...     cprov.archive, name="+edit-dependencies", form=add_private_form
    ... )

    >>> for error in view.errors:
    ...     print(error)
    ...
    You don&#x27;t have permission to use this dependency.

When we grant access to Celso for viewing the private PPA, by making
him a member of the new team, setting the private PPA as dependency is
still denied since Celso's PPA is still public.

    >>> login("foo.bar@canonical.com")
    >>> ignored = a_team.addMember(cprov, mark)
    >>> transaction.commit()
    >>> login("celso.providelo@canonical.com")

    >>> view = create_initialized_view(
    ...     cprov.archive, name="+edit-dependencies", form=add_private_form
    ... )

    >>> for error in view.errors:
    ...     print(error)
    ...
    Public PPAs cannot depend on private ones.

Finally, we try with a private PPA of Celso's. That's enough for
allowing Celso to set PPA for Pirulito Team as dependency of his PPA.

    >>> login("foo.bar@canonical.com")
    >>> cprov_private_ppa = factory.makeArchive(
    ...     owner=cprov, private=True, name="p3a"
    ... )
    >>> login("celso.providelo@canonical.com")

    >>> view = create_initialized_view(
    ...     cprov_private_ppa,
    ...     name="+edit-dependencies",
    ...     form=add_private_form,
    ... )

    >>> len(view.errors)
    0

    >>> view = create_initialized_view(
    ...     cprov_private_ppa, name="+edit-dependencies"
    ... )

    >>> dependencies = view.widgets.get("selected_dependencies").vocabulary
    >>> for dependency in dependencies:
    ...     print(dependency.value.displayname)
    ...
    PPA for Pirulito Team

Remove Celso's membership on the new team and disable his PPA so we don't
affect the following tests.

    >>> cprov.leave(a_team)
    >>> cprov_private_ppa.disable()


ArchivePackageCopyingView
=========================

This class extends ArchiveSourceSelectionFormView, and thus uses the
same mechanisms for presenting and filtering available sources for
copying, the 'selected_sources' widget. Related features don't need to
be re-tested.

    >>> login("celso.providelo@canonical.com")

Issuing a empty request we can inspect the internal attributes used to
build the page.

    >>> view = create_initialized_view(cprov.archive, name="+copy-packages")

The main difference for ArchivePackageDeletionView  is that this uses a
different 'source' provider, which may include deleted sources, and a
different default status filter (only published sources are presented
by default).

    >>> view.has_sources_for_display
    False

In this case, the template can use the has_sources
property to identify that, even though there aren't any sources to
display, it's not because the archive isn't active, but rather just
that the user has filtered the sources:

    >>> view.has_sources
    True

All sources in Celso's PPA were just-deleted, so we have to tweak the
'status_filter' to see them.

    >>> view = create_initialized_view(
    ...     cprov.archive,
    ...     name="+copy-packages",
    ...     query_string="field.status_filter=",
    ... )

    >>> [pub.status.name for pub in view.batched_sources]
    ['DELETED', 'DELETED', 'DELETED']

This view contains three properties. The first is a list of the PPAs
in which the current user has upload/copy rights (see
`IArchiveSet.getPPAsForUser`).

    >>> for ppa in view.ppas_for_user:
    ...     print(ppa.displayname)
    ...
    PPA for Celso Providelo

The second shows whether or not the current user is allowed to perform
copies. They must participate in at least one PPA for this to be True.

    >>> view.can_copy
    True

And finally if the user has the right to upload/copy to the context
PPA.

    >>> view.can_copy_to_context_ppa
    True

Lets exercise the properties. 'No Privileges Person' user has their own
PPA, thus they can copy to it, but not to Celso's PPA.

    >>> login("no-priv@canonical.com")
    >>> view = create_initialized_view(cprov.archive, name="+copy-packages")

    >>> for ppa in view.ppas_for_user:
    ...     print(ppa.displayname)
    ...
    PPA for No Privileges Person

    >>> view.can_copy
    True

    >>> view.can_copy_to_context_ppa
    False

When 'No Privileges Person' gets upload right to Celso's PPA ...

    >>> login("foo.bar@canonical.com")
    >>> no_priv = getUtility(IPersonSet).getByName("no-priv")
    >>> cprov.archive.newComponentUploader(no_priv, "main")
    <ArchivePermission ...>

They become able to copy to the context PPA.

    >>> login("no-priv@canonical.com")
    >>> view = create_initialized_view(cprov.archive, name="+copy-packages")

    >>> for ppa in view.ppas_for_user:
    ...     print(ppa.displayname)
    ...
    PPA for Celso Providelo
    PPA for No Privileges Person

    >>> view.can_copy
    True

    >>> view.can_copy_to_context_ppa
    True

When the No-Priv's PPA is disabled it's not available as a
'Destination Archive' option anymore.

    # Disable No-Priv's PPA.
    >>> login("foo.bar@canonical.com")
    >>> no_priv.archive.disable()

    >>> login("no-priv@canonical.com")
    >>> view = create_initialized_view(cprov.archive, name="+copy-packages")

    >>> for ppa in view.ppas_for_user:
    ...     print(ppa.displayname)
    ...
    PPA for Celso Providelo

    # Re-enable No-Priv's PPA.
    >>> login("foo.bar@canonical.com")
    >>> no_priv.archive.enable()

'Foo Bar' user has no PPA, so they cannot perform copies at all.

    >>> view = create_initialized_view(cprov.archive, name="+copy-packages")

    >>> print(view.ppas_for_user)
    []

    >>> view.can_copy
    False

    >>> view.can_copy_to_context_ppa
    False

When we activate the Ubuntu team PPA, in which Celso participates,
he will be able to copy not only to his PPA but also to the PPA for a
team he is member of.

    >>> ubuntu_team = getUtility(IPersonSet).getByName("ubuntu-team")

    >>> from lp.soyuz.enums import ArchivePurpose
    >>> from lp.soyuz.interfaces.archive import IArchiveSet
    >>> ubuntu_team_ppa = getUtility(IArchiveSet).new(
    ...     owner=ubuntu_team,
    ...     distribution=None,
    ...     purpose=ArchivePurpose.PPA,
    ...     description="Don't we have a distribution ?",
    ... )

    >>> login("celso.providelo@canonical.com")
    >>> view = create_initialized_view(cprov.archive, name="+copy-packages")

    >>> for ppa in view.ppas_for_user:
    ...     print(ppa.displayname)
    ...
    PPA for Celso Providelo
    PPA for Ubuntu Team

    >>> view.can_copy
    True

    >>> view.can_copy_to_context_ppa
    True

The 'Copy' interface is also available for non-ppa archives, so users
can copy packages from them directly to their PPAs, making it useful
for backporting packages, for instance.

    >>> view = create_initialized_view(
    ...     ubuntu.main_archive, name="+copy-packages"
    ... )

    >>> for ppa in view.ppas_for_user:
    ...     print(ppa.displayname)
    ...
    PPA for Celso Providelo
    PPA for Ubuntu Team

    >>> view.can_copy
    True

    >>> view.can_copy_to_context_ppa
    False

Even when Celso is an owner of the non-PPA archive, copies to it will
continue to be denied in the UI.

    >>> login("foo.bar@canonical.com")
    >>> ignored = ubuntu.main_archive.owner.addMember(cprov, cprov)
    >>> login("celso.providelo@canonical.com")

    >>> view = create_initialized_view(
    ...     ubuntu.main_archive, name="+copy-packages"
    ... )

    >>> view.can_copy_to_context_ppa
    False

We will prepare a empty POST and inspect the default form values.

    >>> view = create_initialized_view(
    ...     cprov.archive,
    ...     name="+copy-packages",
    ...     form={
    ...         "field.destination_archive": "",
    ...         "field.destination_series": "",
    ...     },
    ... )

The 'destination_archive' widget contents are directly based on the
'ppas_for_user', but it excludes the context PPA from the list of
options making it the default option, 'This PPA' rendered option.

    >>> archive_widget = view.widgets["destination_archive"]

    >>> archive_widget.required
    False

    >>> print(archive_widget.translate(archive_widget._messageNoValue))
    This PPA

    >>> for item in archive_widget.vocabulary:
    ...     print(item.title)
    ...
    PPA for Ubuntu Team [~ubuntu-team/ubuntu/ppa]

    >>> print(archive_widget.getInputValue() == cprov.archive)
    True

The 'destination_series' widget behaves similarly, it contains all
series available for the PPA distribution and default to 'The same
series', which ends up being None in the browser domain.

    >>> series_widget = view.widgets["destination_series"]

    >>> series_widget.required
    False

    >>> print(archive_widget.translate(series_widget._messageNoValue))
    The same series

    >>> for item in series_widget.vocabulary:
    ...     print(item.title)
    ...
    Breezy Badger Autotest
    Grumpy
    Hoary
    Warty

    >>> print(series_widget.getInputValue())
    None

The 'destination_archive' widget behaves differently depending on
whether or not the user has permission to perform copies to the
context PPA.

No Privileges user can't copy package to the Ubuntu Team PPA, thus
'destination' widget will become required and will fail if an empty
value is submitted.

    >>> login("no-priv@canonical.com")

    >>> view = create_initialized_view(
    ...     ubuntu_team.archive,
    ...     name="+copy-packages",
    ...     form={
    ...         "field.destination_archive": "",
    ...         "field.destination_series": "",
    ...     },
    ... )

    >>> archive_widget = view.widgets["destination_archive"]
    >>> archive_widget.required
    True

    >>> for item in archive_widget.vocabulary:
    ...     print(item.title)
    ...
    PPA for Celso Providelo [~cprov/ubuntu/ppa]
    PPA for No Privileges Person [~no-priv/ubuntu/ppa]

    >>> print(archive_widget.getInputValue())
    Traceback (most recent call last):
    ...
    zope.formlib.interfaces.WidgetInputError:
    ('destination_archive', 'Destination PPA',
     RequiredMissing('destination_archive'))


Copy private files to public archives
-------------------------------------

Users are allowed to copy private sources into public PPAs.
See more information in scripts/packagecopier.py.

First we will enable Celso's private PPA.

    >>> login("foo.bar@canonical.com")
    >>> cprov_private_ppa.enable()

Then we will create a testing publication, that will be restricted.

    >>> from lp.soyuz.tests.test_publishing import SoyuzTestPublisher
    >>> test_publisher = SoyuzTestPublisher()
    >>> hoary = ubuntu.getSeries("hoary")
    >>> test_publisher.addFakeChroots(hoary)
    >>> unused = test_publisher.setUpDefaultDistroSeries(hoary)
    >>> private_source = test_publisher.createSource(
    ...     cprov_private_ppa, "foocomm", "1.0-1", new_version="2.0-1"
    ... )
    >>> transaction.commit()

Now, as Celso we will try to copy the just created 'private' source to
the public Ubuntu-team PPA, which is empty.

    >>> print(private_source.displayname)
    foocomm 2.0-1 in hoary

    >>> ubuntu_team_ppa.getPublishedSources().count()
    0

    >>> login("celso.providelo@canonical.com")
    >>> view = create_initialized_view(
    ...     cprov_private_ppa,
    ...     name="+copy-packages",
    ...     form={
    ...         "field.selected_sources": [str(private_source.id)],
    ...         "field.destination_archive": "~ubuntu-team/ubuntu/ppa",
    ...         "field.destination_series": "",
    ...         "field.include_binaries": "REBUILD_SOURCES",
    ...         "field.actions.copy": "Copy",
    ...     },
    ... )

    >>> len(view.errors)
    0

The action is performed as an asynchronous copy, and the user is informed of
it via a page notification.

    >>> from lp.testing.pages import extract_text
    >>> for notification in view.request.response.notifications:
    ...     print(extract_text(notification.message))
    ...
    Requested sync of 1 package to PPA for Ubuntu Team.
    Please allow some time for this to be processed.

There is one copy job waiting, which we run.

    >>> from lp.services.config import config
    >>> from lp.services.job.runner import JobRunner
    >>> from lp.soyuz.interfaces.packagecopyjob import (
    ...     IPlainPackageCopyJobSource,
    ... )
    >>> from lp.testing.dbuser import dbuser
    >>> [job] = getUtility(IPlainPackageCopyJobSource).getActiveJobs(
    ...     ubuntu_team_ppa
    ... )
    >>> with dbuser(config.IPlainPackageCopyJobSource.dbuser):
    ...     JobRunner([job]).runAll()
    ...
    >>> print(job.status.name)
    COMPLETED

The copy results in a pending source publication.

    >>> [copied_source] = ubuntu_team_ppa.getPublishedSources(
    ...     name="foocomm", exact_match=True
    ... )
    >>> print(copied_source.displayname)
    foocomm 2.0-1 in hoary

If we run the same copy again, it will fail.

    >>> view = create_initialized_view(
    ...     cprov_private_ppa,
    ...     name="+copy-packages",
    ...     form={
    ...         "field.selected_sources": [str(private_source.id)],
    ...         "field.destination_archive": "~ubuntu-team/ubuntu/ppa",
    ...         "field.destination_series": "",
    ...         "field.include_binaries": "REBUILD_SOURCES",
    ...         "field.actions.copy": "Copy",
    ...     },
    ... )
    >>> [job] = getUtility(IPlainPackageCopyJobSource).getActiveJobs(
    ...     ubuntu_team_ppa
    ... )
    >>> with dbuser(config.IPlainPackageCopyJobSource.dbuser):
    ...     JobRunner([job]).runAll()
    ...
    >>> print(job.status.name)
    FAILED

The job failure is shown in the UI.

    >>> from lp.testing import person_logged_in
    >>> with person_logged_in(ubuntu_team_ppa.owner):
    ...     ubuntu_team_ppa_view = create_initialized_view(
    ...         ubuntu_team_ppa,
    ...         name="+packages",
    ...         principal=ubuntu_team_ppa.owner,
    ...     )
    ...
    >>> ubuntu_team_ppa_view.has_pending_copy_jobs is not None
    True
    >>> for job in ubuntu_team_ppa_view.package_copy_jobs:
    ...     print(job.status.title, job.package_name, job.package_version)
    ...     print(job.error_message)
    ...
    Failed foocomm 2.0-1
    foocomm 2.0-1 in hoary (same version already building in the destination
    archive for Hoary)


External dependencies validation
================================

The ArchiveAdminView checks the external_dependencies form data to see if
it's a valid sources.list entry.

    >>> ppa_archive_view = create_initialized_view(
    ...     cprov.archive, name="+admin"
    ... )

    >>> from lp.soyuz.interfaces.archive import validate_external_dependencies

The validate_external_dependencies() function is called when validating and
will return a list of errors if the data dis not validate.  A valid entry is
of the form:
    deb scheme://domain/ suite component[s]

    >>> def print_validate_external_dependencies(ext_deps):
    ...     for error in validate_external_dependencies(ext_deps):
    ...         print(error)
    ...

    >>> print_validate_external_dependencies(
    ...     "deb http://example.com/ karmic main"
    ... )

Multiple entries are valid, separated by newlines:

    >>> print_validate_external_dependencies(
    ...     "deb http://example.com/ karmic main\n"
    ...     "deb http://example.com/ karmic restricted"
    ... )

If the line does not start with the word "deb" it fails:

    >>> print_validate_external_dependencies(
    ...     "deb http://example.com/ karmic universe\n"
    ...     "dab http://example.com/ karmic main"
    ... )
    dab http://example.com/ karmic main: Must start with 'deb'

If the line has too few parts it fails.  Here we're missing a suite:

    >>> print_validate_external_dependencies(
    ...     "deb http://example.com/ karmic universe\n"
    ...     "deb http://example.com/ main"
    ... )
    'deb http://example.com/ main'
        is not a complete and valid sources.list entry

If the URL looks invalid, it fails:

    >>> print_validate_external_dependencies(
    ...     "deb http://example.com/ karmic universe\n"
    ...     "deb example.com/ karmic main"
    ... )
    deb example.com/ karmic main: Invalid URL

Options are permitted:

    >>> print_validate_external_dependencies(
    ...     "deb [trusted=yes] http://example.com/ karmic main"
    ... )
    >>> print_validate_external_dependencies(
    ...     "deb [trusted=yes] example.com/ karmic main"
    ... )
    deb [trusted=yes] example.com/ karmic main: Invalid URL
