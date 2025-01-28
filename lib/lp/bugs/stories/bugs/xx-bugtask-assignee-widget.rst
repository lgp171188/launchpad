The bug task edit page now features a new and improved assignee
widget, which makes it easier to "take" a task.

    >>> print(
    ...     http(
    ...         rb"""
    ... GET /ubuntu/+source/mozilla-firefox/+bug/1/+editstatus HTTP/1.1
    ... Authorization: Basic Zm9vLmJhckBjYW5vbmljYWwuY29tOnRlc3Q=
    ... """
    ...     )
    ... )
    HTTP/1.1 200 Ok
    ...
    ...Assigned to...
    ...nobody...
    ...me...

So, taking the task is now as simple as selecting the "me" radio
button:

    >>> print(
    ...     http(
    ...         rb"""
    ... POST /ubuntu/+source/mozilla-firefox/+bug/1/+editstatus HTTP/1.1
    ... Authorization: Basic Zm9vLmJhckBjYW5vbmljYWwuY29tOnRlc3Q=
    ... Referer: https://launchpad.test/
    ... Content-Type: multipart/form-data; boundary=---------------------------19759086281403130373932339922
    ...
    ... -----------------------------19759086281403130373932339922
    ... Content-Disposition: form-data; name="ubuntu_mozilla-firefox.status"
    ...
    ... Confirmed
    ... -----------------------------19759086281403130373932339922
    ... Content-Disposition: form-data; name="ubuntu_mozilla-firefox.status-empty-marker"
    ...
    ... 1
    ... -----------------------------19759086281403130373932339922
    ... Content-Disposition: form-data; name="ubuntu_mozilla-firefox.importance"
    ...
    ... Low
    ... -----------------------------19759086281403130373932339922
    ... Content-Disposition: form-data; name="ubuntu_mozilla-firefox.importance-empty-marker"
    ...
    ... 1
    ... -----------------------------19759086281403130373932339922
    ... Content-Disposition: form-data; name="ubuntu_mozilla-firefox.milestone"
    ...
    ...
    ... -----------------------------19759086281403130373932339922
    ... Content-Disposition: form-data; name="ubuntu_mozilla-firefox.milestone-empty-marker"
    ...
    ... 1
    ... -----------------------------19759086281403130373932339922
    ... Content-Disposition: form-data; name="ubuntu_mozilla-firefox.sourcepackagename"
    ...
    ... mozilla-firefox
    ... -----------------------------19759086281403130373932339922
    ... Content-Disposition: form-data; name="ubuntu_mozilla-firefox.assignee.option"
    ...
    ... ubuntu_mozilla-firefox.assignee.assign_to_me
    ... -----------------------------19759086281403130373932339922
    ... Content-Disposition: form-data; name="ubuntu_mozilla-firefox.assignee"
    ...
    ...
    ... -----------------------------19759086281403130373932339922
    ... Content-Disposition: form-data; name="ubuntu_mozilla-firefox.bugwatch"
    ...
    ...
    ... -----------------------------19759086281403130373932339922
    ... Content-Disposition: form-data; name="ubuntu_mozilla-firefox.bugwatch-empty-marker"
    ...
    ... 1
    ... -----------------------------19759086281403130373932339922
    ... Content-Disposition: form-data; name="ubuntu_mozilla-firefox.actions.save"
    ...
    ... Save Changes
    ... -----------------------------19759086281403130373932339922--
    ... """.replace(
    ...             b"\n", b"\r\n"
    ...         )  # Necessary to ensure it fits the HTTP standard
    ...     )
    ... )  # noqa
    HTTP/1.1 303 See Other
    ...

In this example, we were logged in as Foo Bar, so the task is now
automagically assigned to Foo Bar.

    >>> print(
    ...     http(
    ...         rb"""
    ... GET /ubuntu/+source/mozilla-firefox/+bug/1 HTTP/1.1
    ... Authorization: Basic Zm9vLmJhckBjYW5vbmljYWwuY29tOnRlc3Q=
    ... """
    ...     )
    ... )
    HTTP/1.1 200 Ok
    ...
    ...mozilla-firefox (Ubuntu)...Foo Bar...
    ...

But, you can also assign the task to another person, of course:

    >>> print(
    ...     http(
    ...         rb"""
    ... POST /ubuntu/+source/mozilla-firefox/+bug/1/+editstatus HTTP/1.1
    ... Authorization: Basic Zm9vLmJhckBjYW5vbmljYWwuY29tOnRlc3Q=
    ... Referer: https://launchpad.test/
    ... Content-Length: 1999
    ... Content-Type: multipart/form-data; boundary=---------------------------19759086281403130373932339922
    ...
    ... -----------------------------19759086281403130373932339922
    ... Content-Disposition: form-data; name="ubuntu_mozilla-firefox.status"
    ...
    ... Confirmed
    ... -----------------------------19759086281403130373932339922
    ... Content-Disposition: form-data; name="ubuntu_mozilla-firefox.status-empty-marker"
    ...
    ... 1
    ... -----------------------------19759086281403130373932339922
    ... Content-Disposition: form-data; name="ubuntu_mozilla-firefox.importance"
    ...
    ... Low
    ... -----------------------------19759086281403130373932339922
    ... Content-Disposition: form-data; name="ubuntu_mozilla-firefox.importance-empty-marker"
    ...
    ... 1
    ... -----------------------------19759086281403130373932339922
    ... Content-Disposition: form-data; name="ubuntu_mozilla-firefox.milestone"
    ...
    ...
    ... -----------------------------19759086281403130373932339922
    ... Content-Disposition: form-data; name="ubuntu_mozilla-firefox.milestone-empty-marker"
    ...
    ... 1
    ... -----------------------------19759086281403130373932339922
    ... Content-Disposition: form-data; name="ubuntu_mozilla-firefox.sourcepackagename"
    ...
    ... mozilla-firefox
    ... -----------------------------19759086281403130373932339922
    ... Content-Disposition: form-data; name="ubuntu_mozilla-firefox.assignee.option"
    ...
    ... ubuntu_mozilla-firefox.assignee.assign_to
    ... -----------------------------19759086281403130373932339922
    ... Content-Disposition: form-data; name="ubuntu_mozilla-firefox.assignee"
    ...
    ... name12
    ... -----------------------------19759086281403130373932339922
    ... Content-Disposition: form-data; name="ubuntu_mozilla-firefox.bugwatch"
    ...
    ...
    ... -----------------------------19759086281403130373932339922
    ... Content-Disposition: form-data; name="ubuntu_mozilla-firefox.bugwatch-empty-marker"
    ...
    ... 1
    ... -----------------------------19759086281403130373932339922
    ... Content-Disposition: form-data; name="ubuntu_mozilla-firefox.actions.save"
    ...
    ... Save Changes
    ... -----------------------------19759086281403130373932339922--
    ... """.replace(
    ...             b"\n", b"\r\n"
    ...         )  # Necessary to ensure it fits the HTTP standard
    ...     )
    ... )  # noqa
    HTTP/1.1 303 See Other
    ...

In this case, we assigned the task to Sample Person:

    >>> print(
    ...     http(
    ...         rb"""
    ... GET /ubuntu/+source/mozilla-firefox/+bug/1 HTTP/1.1
    ... Authorization: Basic Zm9vLmJhckBjYW5vbmljYWwuY29tOnRlc3Q=
    ... """
    ...     )
    ... )
    HTTP/1.1 200 Ok
    ...
    ...mozilla-firefox (Ubuntu)...Sample Person...
    ...

Lastly, the widget also allows you to simply assign the task to nobody
(to, "give up" the task, you might say)

    >>> print(
    ...     http(
    ...         rb"""
    ... POST /ubuntu/+source/mozilla-firefox/+bug/1/+editstatus HTTP/1.1
    ... Authorization: Basic Zm9vLmJhckBjYW5vbmljYWwuY29tOnRlc3Q=
    ... Referer: https://launchpad.test/
    ... Content-Length: 1999
    ... Content-Type: multipart/form-data; boundary=---------------------------19759086281403130373932339922
    ...
    ... -----------------------------19759086281403130373932339922
    ... Content-Disposition: form-data; name="ubuntu_mozilla-firefox.status"
    ...
    ... Confirmed
    ... -----------------------------19759086281403130373932339922
    ... Content-Disposition: form-data; name="ubuntu_mozilla-firefox.status-empty-marker"
    ...
    ... 1
    ... -----------------------------19759086281403130373932339922
    ... Content-Disposition: form-data; name="ubuntu_mozilla-firefox.importance"
    ...
    ... Low
    ... -----------------------------19759086281403130373932339922
    ... Content-Disposition: form-data; name="ubuntu_mozilla-firefox.importance-empty-marker"
    ...
    ... 1
    ... -----------------------------19759086281403130373932339922
    ... Content-Disposition: form-data; name="ubuntu_mozilla-firefox.milestone"
    ...
    ...
    ... -----------------------------19759086281403130373932339922
    ... Content-Disposition: form-data; name="ubuntu_mozilla-firefox.milestone-empty-marker"
    ...
    ... 1
    ... -----------------------------19759086281403130373932339922
    ... Content-Disposition: form-data; name="ubuntu_mozilla-firefox.sourcepackagename"
    ...
    ... mozilla-firefox
    ... -----------------------------19759086281403130373932339922
    ... Content-Disposition: form-data; name="ubuntu_mozilla-firefox.assignee.option"
    ...
    ... ubuntu_mozilla-firefox.assignee.assign_to_nobody
    ... -----------------------------19759086281403130373932339922
    ... Content-Disposition: form-data; name="ubuntu_mozilla-firefox.assignee"
    ...
    ...
    ... -----------------------------19759086281403130373932339922
    ... Content-Disposition: form-data; name="ubuntu_mozilla-firefox.bugwatch"
    ...
    ...
    ... -----------------------------19759086281403130373932339922
    ... Content-Disposition: form-data; name="ubuntu_mozilla-firefox.bugwatch-empty-marker"
    ...
    ... 1
    ... -----------------------------19759086281403130373932339922
    ... Content-Disposition: form-data; name="ubuntu_mozilla-firefox.actions.save"
    ...
    ... Save Changes
    ... -----------------------------19759086281403130373932339922--
    ... """.replace(
    ...             b"\n", b"\r\n"
    ...         )  # Necessary to ensure it fits the HTTP standard
    ...     )
    ... )  # noqa
    HTTP/1.1 303 See Other
    ...

And now the bug task is unassigned:

    >>> print(
    ...     http(
    ...         rb"""
    ... GET /ubuntu/+source/mozilla-firefox/+bug/1 HTTP/1.1
    ... Authorization: Basic Zm9vLmJhckBjYW5vbmljYWwuY29tOnRlc3Q=
    ... """
    ...     )
    ... )
    HTTP/1.1 200 Ok
    ...
    ...mozilla-firefox (Ubuntu)...
    ...
