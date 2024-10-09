Bug tags
========

In order to arbitrary group bugs together a bug can be associated with
one or more tags. A tag is a simple text string, not contain a space
character. The tags are available as a list of strings on the bug:

    >>> from lp.bugs.interfaces.bug import IBugSet
    >>> bug_one = getUtility(IBugSet).get(1)

There are no tags currently, so let's add some. It doesn't matter which
order the tags are in, the result will be ordered alphabetically:

    >>> bug_one.tags
    []

    >>> login("test@canonical.com")
    >>> bug_one.tags = ["svg", "sco"]
    >>> for tag in bug_one.tags:
    ...     print(tag)
    ...
    sco
    svg

Under the hood the tags are stored in a different table. If we take a
look at it we can see that the added tags are there.

    >>> from lp.bugs.model.bug import BugTag
    >>> from lp.services.database.interfaces import IStore
    >>> bugtags = (
    ...     IStore(BugTag)
    ...     .find(BugTag, bug_id=bug_one.id)
    ...     .order_by(BugTag.tag)
    ... )
    >>> for bugtag in bugtags:
    ...     print(bugtag.tag)
    ...
    sco
    svg

So if we add another tag by setting the 'tags' attribute to a new list.
The tag will be added in the table.

    >>> bug_one.tags = ["svg", "sco", "install"]
    >>> for tag in bug_one.tags:
    ...     print(tag)
    ...
    install
    sco
    svg
    >>> from lp.services.database.interfaces import IStore
    >>> bugtags = (
    ...     IStore(BugTag)
    ...     .find(BugTag, bug_id=bug_one.id)
    ...     .order_by(BugTag.tag)
    ... )
    >>> bugtags = (
    ...     IStore(BugTag)
    ...     .find(BugTag, bug_id=bug_one.id)
    ...     .order_by(BugTag.tag)
    ... )
    >>> for bugtag in bugtags:
    ...     print(bugtag.tag)
    ...
    install
    sco
    svg

We allow adding the same tag twice, but it won't be stored twice in the
db:

    >>> bug_one.tags = ["svg", "svg", "sco", "install"]
    >>> for tag in bug_one.tags:
    ...     print(tag)
    ...
    install
    sco
    svg

Let's correct the spelling mistake we did and delete one of the tags:

    >>> bug_one.tags = ["sco", "install"]
    >>> for tag in bug_one.tags:
    ...     print(tag)
    ...
    install
    sco

    >>> from lp.services.database.interfaces import IStore
    >>> bugtags = (
    ...     IStore(BugTag)
    ...     .find(BugTag, bug_id=bug_one.id)
    ...     .order_by(BugTag.tag)
    ... )
    >>> for bugtag in bugtags:
    ...     print(bugtag.tag)
    ...
    install
    sco


Widgets
-------

To make it easy editing the tags as a space separated text string, we
use BugTagsWidget.

    >>> from lp.services.webapp.servers import LaunchpadTestRequest
    >>> from lp.bugs.browser.widgets.bug import BugTagsWidget
    >>> from lp.bugs.interfaces.bug import IBug
    >>> bug_tags_field = IBug["tags"].bind(bug_one)
    >>> tag_field = bug_tags_field.value_type
    >>> request = LaunchpadTestRequest()
    >>> tags_widget = BugTagsWidget(bug_tags_field, tag_field, request)

Since we didn't provided a value in the request, the form value will be
empty:

    >>> print(tags_widget._getFormValue())
    <BLANKLINE>

If we set the value to bug one's tags, it will be a space separated
string:

    >>> tags_widget.setRenderedValue(bug_one.tags)
    >>> print(tags_widget._getFormValue())
    install sco

If we pass in a value via the request, we'll be able to get the tags as
a sorted list from getInputValue():

    >>> request = LaunchpadTestRequest(form={"field.tags": "svg sco"})
    >>> tags_widget = BugTagsWidget(bug_tags_field, tag_field, request)
    >>> print(tags_widget._getFormValue())
    sco svg
    >>> for tag in tags_widget.getInputValue():
    ...     print(tag)
    ...
    sco
    svg

When we have an input value, the widget can edit the bug tags.

    >>> for tag in bug_one.tags:
    ...     print(tag)
    ...
    install
    sco
    >>> tags_widget.applyChanges(bug_one)
    True
    >>> for tag in bug_one.tags:
    ...     print(tag)
    ...
    sco
    svg

If a user enters an invalid tag, we get an error explaining what's
wrong.

    >>> request = LaunchpadTestRequest(form={"field.tags": "!!!! foo $$$$"})
    >>> tags_widget = BugTagsWidget(bug_tags_field, tag_field, request)
    >>> tags_widget.getInputValue()
    Traceback (most recent call last):
    ...
    zope.formlib.interfaces.WidgetInputError: ...

    >>> print(tags_widget._error.doc())
    &#x27;!!!!&#x27; isn&#x27;t a valid tag name. Tags must start with a
    letter or number and be lowercase. The characters &quot;+&quot;,
    &quot;-&quot; and &quot;.&quot; are also allowed after the first
    character.

Let's take a closer look at _toFormValue() to ensure that it works
properly:

    >>> print(tags_widget._toFormValue([]))
    <BLANKLINE>
    >>> print(tags_widget._toFormValue(["foo"]))
    foo
    >>> print(tags_widget._toFormValue(["foo", "bar"]))
    foo bar

And _toFieldValue():

    >>> tags_widget._toFieldValue("")
    []
    >>> for tag in tags_widget._toFieldValue("foo"):
    ...     print(tag)
    ...
    foo
    >>> for tag in tags_widget._toFieldValue("FOO bar"):
    ...     print(tag)
    ...
    bar
    foo
    >>> for tag in tags_widget._toFieldValue("foo   \t          bar"):
    ...     print(tag)
    ...
    bar
    foo

A comma isn't valid in a tag name and sometimes users use commas to
separate the tags, so we accept that as well.

    >>> for tag in tags_widget._toFieldValue("foo, bar"):
    ...     print(tag)
    ...
    bar
    foo

    >>> for tag in tags_widget._toFieldValue("foo,bar"):
    ...     print(tag)
    ...
    bar
    foo

Duplicate tags are converted to a single instance.

    >>> for tag in tags_widget._toFieldValue(
    ...     "FOO, , , , bar bar, bar, bar foo"
    ... ):
    ...     print(tag)
    bar
    foo


Bug Tags Widget for Frozen Sets
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A variant of `BugTagsWidget` exists for when tags are stored in a
`FrozenSet` field.

    >>> from lp.bugs.browser.widgets.bug import BugTagsFrozenSetWidget

Field-manipulation is not going to be examined here, and the widget
does not care what type the field is otherwise, so the field from
earlier can be used again.

    >>> tags_frozen_set_widget = BugTagsFrozenSetWidget(
    ...     bug_tags_field, tag_field, request
    ... )

_tagsFromFieldValue() converts tags from the field value to tags for
display. The absence of tags causes it to return None:

    >>> print(tags_frozen_set_widget._tagsFromFieldValue(None))
    None
    >>> print(tags_frozen_set_widget._tagsFromFieldValue(frozenset()))
    None

Tags are ordered before returning:

    >>> tags_frozen_set_widget._tagsFromFieldValue(frozenset([5, 4, 1, 12]))
    [1, 4, 5, 12]

_tagsToFieldValue() converts the tags entered in the form into a value
suitable for the field. In the absence of tags it returns an empty
frozenset():

    >>> for item in tags_frozen_set_widget._tagsToFieldValue(None):
    ...     print(item)
    ...
    >>> for item in tags_frozen_set_widget._tagsToFieldValue([]):
    ...     print(item)
    ...

Otherwise it returns a `frozenset` of the tags given:

    >>> for item in sorted(
    ...     tags_frozen_set_widget._tagsToFieldValue(["foo", "bar"])
    ... ):
    ...     print(item)
    bar
    foo


Large and Small Bug Tags Widget
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A regular BugTagsWidget is rendered as an <input> tag,

    >>> print(tags_widget())
    <input...type="text"...

A LargeBugTagsWidget is rendered as a <textarea>,

    >>> from lp.bugs.browser.widgets.bug import LargeBugTagsWidget
    >>> large_text_widget = LargeBugTagsWidget(
    ...     bug_tags_field, tag_field, request
    ... )
    >>> print(large_text_widget())
    <textarea...


Searching
---------

We can search for bugs with some specific tag.

    >>> from lp.services.searchbuilder import all
    >>> from lp.bugs.interfaces.bugtasksearch import BugTaskSearchParams
    >>> from lp.registry.interfaces.distribution import IDistributionSet
    >>> ubuntu = getUtility(IDistributionSet).getByName("ubuntu")
    >>> svg_tasks = ubuntu.searchTasks(
    ...     BugTaskSearchParams(tag=all("svg"), user=None)
    ... )
    >>> for bugtask in svg_tasks:
    ...     print(
    ...         bugtask.bug.id,
    ...         " ".join("'%s'" % tag for tag in bugtask.bug.tags),
    ...     )
    ...
    1 'sco' 'svg'

We can also search for bugs with any of the tags in a supplied list.

    >>> from lp.services.searchbuilder import any
    >>> crash_dataloss_tasks = ubuntu.searchTasks(
    ...     BugTaskSearchParams(
    ...         tag=any("crash", "dataloss"), orderby="id", user=None
    ...     )
    ... )
    >>> for bugtask in crash_dataloss_tasks:
    ...     print(
    ...         bugtask.bug.id,
    ...         " ".join("'%s'" % tag for tag in bugtask.bug.tags),
    ...     )
    ...
    2 'dataloss' 'pebcak'
    9 'crash'
    10 'crash'

And for bugs with all of the tags in a supplied list.

    >>> from lp.services.searchbuilder import all
    >>> getUtility(IBugSet).get(10).tags = ["crash", "burn"]
    >>> crash_burn_tasks = ubuntu.searchTasks(
    ...     BugTaskSearchParams(
    ...         tag=all("crash", "burn"), orderby="id", user=None
    ...     )
    ... )
    >>> for bugtask in crash_burn_tasks:
    ...     print(
    ...         bugtask.bug.id,
    ...         " ".join("'%s'" % tag for tag in bugtask.bug.tags),
    ...     )
    ...
    10 'burn' 'crash'
    >>> getUtility(IBugSet).get(10).tags = ["crash"]

Tags are also searched when searching for some text in general. For
example, if we search for 'some-tag', we find nothing at the moment:

    >>> some_tag_tasks = ubuntu.searchTasks(
    ...     BugTaskSearchParams(searchtext="some-tag", user=None)
    ... )
    >>> some_tag_tasks.count()
    0

# XXX: Bjorn Tillenius 2006-07-14
#      The tests below don't pass yet. It's desirable functionality, but
#      it's better to get this branch landed and spend time on it later.

If we now set bug one's tag to 'some-tag', it will be found.

    XXX from lp.services.database.sqlbase import flush_database_updates
    XXX bug_one.tags = [u'some-tag']
    XXX flush_database_updates()

    XXX some_tag_tasks = ubuntu.searchTasks(
    ...     BugTaskSearchParams(searchtext=u'some-tag', user=None))
    XXX for bugtask in some_tag_tasks:
    ...     print(bugtask.bug.id,
    ...           ' '.join("'%s'" % tag for tag in bugtask.bug.tags))
    1 'some-tag'


Tags for a context
------------------

    >>> from lp.registry.interfaces.product import IProductSet
    >>> firefox = getUtility(IProductSet).getByName("firefox")
    >>> from lp.registry.interfaces.projectgroup import IProjectGroupSet
    >>> mozilla = getUtility(IProjectGroupSet).getByName("mozilla")
    >>> ubuntu_thunderbird = ubuntu.getSourcePackage("thunderbird")
    >>> debian = getUtility(IDistributionSet).getByName("debian")
    >>> debian_woody = debian.getSeries("woody")
    >>> debian_woody_firefox = debian_woody.getSourcePackage(
    ...     "mozilla-firefox"
    ... )

When viewing a bug listing for a context we want to display all the tags
that are used in that context. We can also get all the used tags, together
with the number of open bugs each tag has. Only tags having open bugs are
returned.

    >>> def print_tag_counts(target, user, **kwargs):
    ...     for tag, sum_count in sorted(
    ...         target.getUsedBugTagsWithOpenCounts(user, **kwargs).items()
    ...     ):
    ...         print(tag, sum_count)
    ...

    >>> print_tag_counts(firefox, None)
    doc 1
    layout-test 1
    sco 1
    svg 1

    >>> print_tag_counts(mozilla, None)
    doc 1
    layout-test 1
    sco 1
    svg 1

    >>> print_tag_counts(ubuntu, None)
    crash 2
    dataloss 1
    pebcak 1
    sco 1
    svg 1

We can require that some tags be included in the output even when limiting the
results.

    >>> print_tag_counts(
    ...     ubuntu, None, tag_limit=1, include_tags=["pebcak", "svg", "fake"]
    ... )
    crash 2
    fake 0
    pebcak 1
    svg 1

Source packages are a bit special, they return all the tags that are
used in the whole distribution, while the bug count includes only bugs
in the specific package.

    >>> print_tag_counts(ubuntu_thunderbird, None)
    crash 1

    >>> print_tag_counts(debian_woody, None)
    dataloss 1
    layout-test 1
    pebcak 1

    >>> print_tag_counts(debian_woody_firefox, None)
    dataloss 1
    layout-test 1
    pebcak 1

Only bugs that the supplied user has access to will be counted:

    >>> bug_nine = getUtility(IBugSet).get(9)
    >>> bug_nine.setPrivate(True, getUtility(ILaunchBag).user)
    True
    >>> flush_database_updates()

    >>> print_tag_counts(ubuntu_thunderbird, None)

    >>> sample_person = getUtility(ILaunchBag).user
    >>> bug_nine.isSubscribed(sample_person)
    True
    >>> print_tag_counts(ubuntu_thunderbird, sample_person)
    crash 1
