Foo Bar changes the productseries named 'failedbranch' from the product a52dec
to bazaar. Also changes the name of the productseries to 'newname'.
    >>> print(
    ...     http(
    ...         r"""
    ... POST /a52dec/failedbranch/+review HTTP/1.1
    ... Authorization: Basic Zm9vLmJhckBjYW5vbmljYWwuY29tOnRlc3Q=
    ... Referer: https://launchpad.test/
    ... Content-Type: multipart/form-data; boundary=---------------------------10572808480422220968425074
    ...
    ... -----------------------------10572808480422220968425074
    ... Content-Disposition: form-data; name="field.product"
    ...
    ... bazaar
    ... -----------------------------10572808480422220968425074
    ... Content-Disposition: form-data; name="field.name"
    ...
    ... newname
    ... -----------------------------10572808480422220968425074
    ... Content-Disposition: form-data; name="field.actions.change"
    ...
    ... Change
    ... -----------------------------10572808480422220968425074--
    ... """.replace(
    ...             "\n", "\r\n"
    ...         )  # Necessary to ensure it fits the HTTP standard
    ...     )
    ... )  # noqa
    HTTP/1.1 303 See Other
    ...
    Location: http://localhost/bazaar/newname...

    >>> print(
    ...     http(
    ...         r"""
    ... GET /bazaar/newname HTTP/1.1
    ... Authorization: Basic Zm9vLmJhckBjYW5vbmljYWwuY29tOnRlc3Q=
    ... """
    ...     )
    ... )
    HTTP/1.1 200 Ok
    ...
