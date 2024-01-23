===============
Matrix Accounts
===============


In their Launchpad profile, users can register their Matrix accounts.

Adding a new account
--------------------

To register a Matrix account with their account, the user visits their
profile page and uses the 'Edit Matrix accounts' link.

    >>> def go_to_edit_matrix_accounts_page(browser):
    ...     browser.open("http://launchpad.test/~no-priv")
    ...     browser.getLink("Edit Matrix accounts").click()
    ...

    >>> go_to_edit_matrix_accounts_page(user_browser)
    >>> print(user_browser.title)
    No Privileges Person's Matrix...

An anonymous user, isn't able to see the "Edit Matrix accounts" button, nor go
to the page directly:

    >>> anon_browser.open("http://launchpad.test/~no-priv")
    >>> browser.getLink("Edit Matrix accounts")
    Traceback (most recent call last):
      ...
    AttributeError: 'NoneType' object ...

    >>> anon_browser.open(
    ...     "http://launchpad.test/~no-priv/+editmatrixaccounts"
    ... )
    Traceback (most recent call last):
      ...
    zope.security.interfaces.Unauthorized: ...

The user enters the username and homeserver combination in the text inputs
and clicks on the 'Save Changes' button.

    >>> def add_matrix_account(browser, username, homeserver):
    ...     browser.getControl(name="new_homeserver").value = homeserver
    ...     browser.getControl(name="new_username").value = username
    ...     browser.getControl("Save Changes").click()
    ...
    >>> def show_notifications(browser, type):
    ...     for notification in find_tags_by_class(browser.contents, type):
    ...         print(extract_text(notification))
    ...

    >>> def show_matrix_accounts(browser):
    ...     for item in find_tags_by_class(
    ...         browser.contents, "matrix-account"
    ...     ):
    ...         print(extract_text(item.find("span")))
    ...

    >>> add_matrix_account(user_browser, "mark", "ubuntu.com")
    >>> show_notifications(user_browser, "informational")
    Matrix accounts saved successfully.

    >>> show_matrix_accounts(user_browser)
    @mark:ubuntu.com

In this case, the user tried registering a Matrix account with invalid
usernames or homeservers, an error is displayed and the user can enter
another one:

    >>> go_to_edit_matrix_accounts_page(user_browser)
    >>> go_to_edit_matrix_accounts_page(user_browser)
    >>> add_matrix_account(user_browser, "<b>mark</b>", "ubuntu.com")
    >>> show_notifications(user_browser, "error")
    Username must be valid.

User remains on the edit Matrix accounts page, and can reenter the username and
homeserver, but none should be empty:
    >>> print(user_browser.title)
    No Privileges Person's Matrix...

    >>> add_matrix_account(user_browser, "", "ubuntu.com")
    >>> show_notifications(user_browser, "error")
    You must provide the following fields: username, homeserver.


Editing an account
-------------------

To edit an existing Matrix account, the user can update the corresponding
input fields:

    >>> def edit_existing_matrix_account(
    ...     browser, index, username, homeserver
    ... ):
    ...     main_content = find_tag_by_id(browser.contents, "maincontent")
    ...     table_row = main_content.find_all("tr")[index + 1]
    ...
    ...     homeserver_input = table_row.find(
    ...         "input", {"class": "field_homeserver"}
    ...     ).attrs["name"]
    ...     username_input = table_row.find(
    ...         "input", {"class": "field_username"}
    ...     ).attrs["name"]
    ...
    ...     browser.getControl(name=homeserver_input).value = homeserver
    ...     browser.getControl(name=username_input).value = username
    ...     browser.getControl("Save Changes").click()

    >>> go_to_edit_matrix_accounts_page(user_browser)
    >>> edit_existing_matrix_account(user_browser, 0, "fred", "test.com")
    >>> show_notifications(user_browser, "informational")
    Matrix accounts saved successfully.

    >>> show_matrix_accounts(user_browser)
    @fred:test.com

Edited fields will also show an error if not valid:

    >>> go_to_edit_matrix_accounts_page(user_browser)
    >>> edit_existing_matrix_account(user_browser, 0, "fred", "<server>")
    >>> show_notifications(user_browser, "error")
    Homeserver must be a valid domain.

    >>> edit_existing_matrix_account(user_browser, 0, "&fred", "test.com")
    >>> show_notifications(user_browser, "error")
    Username must be valid.


Removing an account
-------------------

To remove an existing Matrix account, the user simply checks the 'Remove'
checkbox besides the ID, and if there are no accounts left, UI informs the
user:

    >>> go_to_edit_matrix_accounts_page(user_browser)
    >>> user_browser.getControl("Remove", index=0).click()
    >>> user_browser.getControl("Save Changes").click()

    >>> show_notifications(user_browser, "informational")
    Matrix accounts saved successfully.

    >>> matrix_section = find_tag_by_id(user_browser.contents, "empty-matrix")
    >>> print(extract_text(matrix_section.find_all("span")[0]))
    No matrix accounts registered.

    >>> print(matrix_section.find("a").attrs["href"])
    http://.../~no-priv/+editmatrixaccounts
