Librarian File Upload Protocol Unit Tests
=========================================

This file tests the Librarian server's upload protocol, and how it responds to
various possible upload requests.  (Note that this isn't testing the storage
backend at all, just the protocol logic).

Database check
--------------

The Database-Name header is now mandatory.  If it isn't present, an otherwise
well-formed request will be rejected:

    >>> upload_request(b"""STORE 14 hello.txt
    ... Content-Type: text/plain
    ... File-Content-ID: 123
    ... File-Alias-ID: 456
    ...
    ... Cats and dogs.""")
    reply: '400 Database-Name header is required'
    connection closed

If Database-Name is specified by the client, and doesn't match the database
name of the server, the upload is rejected.

    >>> upload_request(b"""STORE 14 hello.txt
    ... Content-Type: text/plain
    ... File-Content-ID: 123
    ... File-Alias-ID: 456
    ... Database-Name: wrong_database
    ...
    ... Cats and dogs.""")
    reply: "400 Wrong database 'wrong_database', should be 'right_database'"
    connection closed

If the database name matches, it's accepted as usual.

    >>> upload_request(b"""STORE 14 hello.txt
    ... Content-Type: text/plain
    ... File-Content-ID: 123
    ... File-Alias-ID: 456
    ... Database-Name: right_database
    ...
    ... Cats and dogs.""")
    reply: '200'
    file 'hello.txt' stored as text/plain, contents: 'Cats and dogs.'


Error conditions
----------------

Errors receive a 400 status code in the reply, and the connection will be
closed.

Invalid UTF-8 lines are rejected.

    >>> upload_request(b"STORE 10000 \xff\n")
    reply: '400 Non-data lines must be in UTF-8'
    connection closed

Unknown commands are rejected.

    >>> upload_request(b"FROB the chicken\n")
    reply: '400 Unknown command: FROB the chicken'
    connection closed

Incomplete STORE commands are rejected.

    >>> upload_request(b"STORE bad-arg!\n")
    reply: '400 STORE command expects a size and file name'
    connection closed

Invalid headers are rejected.

    >>> upload_request(b"""STORE 10000 foo.txt
    ... Some garbage.
    ... """)
    reply: '400 Invalid header: Some garbage.'
    connection closed


Uploading corner cases
----------------------

Empty files work, rather than hang the connection.

    >>> upload_request(b"""STORE 0 foo.txt
    ... Content-Type: text/plain
    ... File-Content-ID: 123
    ... File-Alias-ID: 456
    ... Database-Name: right_database
    ...
    ... """)
    reply: '200'
    file 'foo.txt' stored as text/plain, contents: ''

Filename with spaces work.

    >>> upload_request(b"""STORE 14 cats and dogs.txt
    ... Content-Type: text/plain
    ... File-Content-ID: 123
    ... File-Alias-ID: 456
    ... Database-Name: right_database
    ...
    ... Cats and dogs.""")
    reply: '200'
    file 'cats and dogs.txt' stored as text/plain, contents: 'Cats and dogs.'

Unicode filenames work, but must be encoded as UTF-8 on the socket.

    >>> filename = 'Yow\N{INTERROBANG}'
    >>> upload_request(("""STORE 14 %s
    ... Content-Type: text/plain
    ... File-Content-ID: 123
    ... File-Alias-ID: 456
    ... Database-Name: right_database
    ...
    ... Cats and dogs.""" % filename).encode('UTF-8'))
    reply: '200'
    file 'Yow‽' stored as text/plain, contents: 'Cats and dogs.'
