Check that we can get a potlist for a source package that has potemplates:

    >>> print(
    ...     http(
    ...         rb"""
    ... GET /ubuntu/hoary/+source/evolution/+potlist HTTP/1.1
    ... Host: translations.launchpad.test
    ... """
    ...     )
    ... )
    HTTP/1.1 200 Ok
    Content-Length: ...
    Content-Type: text/html;charset=utf-8
    <BLANKLINE>
    ...
    ...Listing of FEW templates...
    ...
