
/+soft-timeout provides a way of testing if hard timeouts work in addition
to how it works in the xx-soft-timeout.rst test.

If we set soft_request_timeout to some value, the page will take
slightly longer then the soft_request_timeout value to generate, thus
causing a soft timeout to be logged.

    >>> from lp.services.config import config
    >>> from textwrap import dedent
    >>> test_data = dedent("""
    ...     [database]
    ...     db_statement_timeout: 1
    ...     soft_request_timeout: 2
    ...     """)
    >>> config.push('base_test_data', test_data)
    >>> print(http(r"""
    ... GET /+soft-timeout HTTP/1.1
    ... Authorization: Basic Zm9vLmJhckBjYW5vbmljYWwuY29tOnRlc3Q=
    ... """))
    HTTP/1.1 503 Service Unavailable
    ...
    Retry-After: 900
    ...
    <title>Error: Timeout</title>
    ...

    >>> oops_capture.oopses[-1]['type']
    'RequestExpired'

Let's reset the config value we changed:

    >>> base_test_data = config.pop('base_test_data')

