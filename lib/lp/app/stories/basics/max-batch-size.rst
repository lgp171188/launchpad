Invalid batch size
==================

To prevent users from exhausting server resources, pages that use
batching have a maximum on the batch size. For example, requesting 1000
products will display a page telling the users that the batch is too
large and what is the current maximum.

    >>> anon_browser.handleErrors = True
    >>> anon_browser.open(
    ...     "http://launchpad.test/projects/+all?start=0&batch=1000"
    ... )
    Traceback (most recent call last):
    ...
    urllib.error.HTTPError: HTTP Error 400: Bad Request

    >>> print(extract_text(find_main_content(anon_browser.contents)))
    Invalid Batch Size
    Your requested batch size exceeded the maximum batch size allowed.
    ...
