NameBlocklist pages
===================

    >>> import transaction
    >>> from zope.component import getUtility
    >>> from lp.testing.sampledata import ADMIN_EMAIL
    >>> from lp.app.interfaces.launchpad import ILaunchpadCelebrities
    >>> from lp.registry.interfaces.nameblocklist import INameBlocklistSet
    >>> name_blocklist_set = getUtility(INameBlocklistSet)
    >>> from lp.testing.pages import extract_text, find_tag_by_id
    >>> registry_experts = getUtility(ILaunchpadCelebrities).registry_experts
    >>> registry_expert = factory.makePerson()
    >>> login(ADMIN_EMAIL)
    >>> ignore = registry_experts.addMember(registry_expert, registry_expert)
    >>> transaction.commit()


View all
--------

All the blocklisted regular expressions that filter pillar names and
person names can be seen on the /+nameblocklist page.

    >>> ignored = login_person(registry_expert)
    >>> view = create_initialized_view(
    ...     name_blocklist_set, "+index", principal=registry_expert
    ... )
    >>> print(
    ...     extract_text(
    ...         find_tag_by_id(view.render(), "blocklist"), formatter="html"
    ...     )
    ... )
    Regular Expression                   Admin    Comment
    ^admin Edit blocklist expression     &mdash;
    blocklist Edit blocklist expression  &mdash;  For testing purposes


Add expression to blocklist
---------------------------

An invalid regular expression cannot be added.

    >>> form = {
    ...     "field.regexp": "(",
    ...     "field.admin": registry_experts.name,
    ...     "field.comment": "old-comment",
    ...     "field.actions.add": "Add to blocklist",
    ... }
    >>> view = create_initialized_view(name_blocklist_set, "+add", form=form)
    >>> for error in view.errors:
    ...     print(error)
    ...
    Invalid regular expression: ...

A duplicate regular expression cannot be added.

    >>> form["field.regexp"] = "blocklist"
    >>> view = create_initialized_view(name_blocklist_set, "+add", form=form)
    >>> for error in view.errors:
    ...     print(error)
    ...
    This regular expression already exists.

After adding a regular expression, a notification will be displayed.

    >>> form["field.regexp"] = "foo"
    >>> view = create_initialized_view(name_blocklist_set, "+add", form=form)
    >>> for notification in view.request.response.notifications:
    ...     print(notification.message)
    ...
    Regular expression &quot;foo&quot; has been added to the name blocklist.

    >>> transaction.commit()
    >>> foo_exp = name_blocklist_set.getByRegExp("foo")
    >>> print(foo_exp.regexp)
    foo
    >>> print(foo_exp.admin.name)
    registry


Edit expression in blocklist
----------------------------

When a regular expression is edited, it still must be valid.

    >>> form = {
    ...     "field.regexp": "(",
    ...     "field.admin": registry_experts.name,
    ...     "field.comment": "new-comment",
    ...     "field.actions.change": "Change",
    ... }
    >>> view = create_initialized_view(foo_exp, "+edit", form=form)
    >>> for error in view.errors:
    ...     print(error)
    ...
    Invalid regular expression: ...

It cannot changed to conflict with another regular expression.

    >>> form["field.regexp"] = "blocklist"
    >>> view = create_initialized_view(foo_exp, "+edit", form=form)
    >>> for error in view.errors:
    ...     print(error)
    ...
    This regular expression already exists.

Otherwise, the change will be successful.

    >>> form["field.regexp"] = "bar"
    >>> view = create_initialized_view(foo_exp, "+edit", form=form)
    >>> print(foo_exp.regexp, foo_exp.comment)
    bar new-comment
