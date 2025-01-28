Text Searching
==============

Introduction
------------
We are currently using PostgreSQL's built-in full text search capabilities.

Although in a lot of cases simple substring searches using LIKE would be
fine or even preferred, the disadvantage of using LIKE is that PostgreSQL
cannot use any indexes to do the substring search. This does not scale
when we need to search tens of thousands of entries (packages) or hundreds
of thousands of entries (people) or millions of entries (translations).

Querying
--------

The examples use the following helper function to execute SQL commands
against the database and display the results:

    >>> from lp.services.database.interfaces import (
    ...     DEFAULT_FLAVOR,
    ...     IStoreSelector,
    ...     MAIN_STORE,
    ... )

    >>> store = getUtility(IStoreSelector).get(MAIN_STORE, DEFAULT_FLAVOR)

    >>> def runsql(query, *args):
    ...     '''Run an SQL query and return the results as text'''
    ...     colsize = 25
    ...     for row in store.execute(query, args):
    ...         line = ""
    ...         for col in row:
    ...             if isinstance(col, (float, int)):
    ...                 col = "%1.2f" % col
    ...             if len(col) > colsize:
    ...                 line += "%s... " % col[: colsize - 3]
    ...             else:
    ...                 fmt = "%%-%ds " % colsize
    ...                 line += fmt % col
    ...         line = line.rstrip()
    ...         print(line)
    ...


All queries against the full text indexes use the following basic syntax:

    >>> runsql("SELECT displayname FROM Person WHERE fti @@ ftq('Mark')")
    Mark Shuttleworth

Queries are all case insensitive:

    >>> runsql(
    ...     """SELECT displayname FROM Person WHERE fti @@ ftq('cArlos')
    ...               ORDER BY displayname"""
    ... )
    Carlos Perelló Marín
    Carlos Valdivia Yagüe

If a query contains multiple words, an AND query is performed:

    >>> runsql(
    ...     """SELECT displayname FROM Person
    ...               WHERE fti @@ ftq('Carlos Valdivia')"""
    ... )
    Carlos Valdivia Yagüe

This can also be explicitly performed by joining the words with 'and':

    >>> runsql(
    ...     """
    ...     SELECT displayname FROM Person
    ...         WHERE fti @@ ftq('carlos AND valdivia') ORDER BY displayname
    ...     """
    ... )
    Carlos Valdivia Yagüe

We also support 'OR' as a boolean operation:

    >>> runsql(
    ...     """
    ...     SELECT displayname FROM Person
    ...         WHERE fti @@ ftq('valdivia OR mark') ORDER BY displayname
    ...     """
    ... )
    Carlos Valdivia Yagüe
    Mark Shuttleworth

NULL searches will return nothing:

    >>> runsql(
    ...     """
    ...     SELECT displayname FROM Person
    ...         WHERE fti @@ ftq(NULL) ORDER BY displayname
    ...     """
    ... )


ftq(text) & _ftq(text)
----------------------

To help debug the `ftq(text)` helper, a similar function exists sharing
the same code that returns a string rather than the compiled version. This
allows us to check the 'query munging' algorithms we are using and debug
any syntax error exceptions being generated.

The following examples show the text version of the query using
`_ftq(text)`, and the compiled version returned by `ftq(text)`

    >>> def ftq(query):
    ...     try:
    ...         result = store.execute(
    ...             "SELECT _ftq(%s), ftq(%s)", (query, query)
    ...         )
    ...         uncompiled, compiled = result.get_one()
    ...     except Exception:
    ...         store.rollback()
    ...         raise
    ...     if uncompiled is not None:
    ...         uncompiled = backslashreplace(uncompiled)
    ...         uncompiled = uncompiled.replace(" ", "")
    ...     if compiled is not None:
    ...         compiled = backslashreplace(compiled)
    ...     print("%s <=> %s" % (uncompiled, compiled))
    ...
    >>>
    >>> def search(text_to_search, search_phrase):
    ...     result = store.execute(
    ...         "SELECT to_tsvector(%s)", (text_to_search,)
    ...     )
    ...     ts_vector = result.get_all()[0][0]
    ...     result = store.execute("SELECT ftq(%s)", (search_phrase,))
    ...     ts_query = result.get_all()[0][0]
    ...     result = store.execute(
    ...         "SELECT to_tsvector(%s) @@ ftq(%s)",
    ...         (text_to_search, search_phrase),
    ...     )
    ...     match = result.get_all()[0][0]
    ...     return "FTI data: %s query: %s match: %s" % (
    ...         ts_vector,
    ...         ts_query,
    ...         str(match),
    ...     )
    ...
    >>>
    >>> def search_same(text):
    ...     return search(text, text)
    ...

Queries are lowercased

    >>> ftq("Hello")
    hello <=> 'hello'


Whitespace is normalized

    >>> ftq("Hello\r\n\tMom\t")
    hello&mom <=> 'hello' & 'mom'


Boolean operations are allowed

    >>> ftq("hi AND mom")
    hi&mom <=> 'hi' & 'mom'

    >>> ftq("hi OR mom")
    hi|mom <=> 'hi' | 'mom'

    >>> ftq("hi AND NOT dad")
    hi&!dad <=> 'hi' & !'dad'


Brackets are allowed to specify precedence

    >>> ftq("(HI OR HELLO) AND mom")
    (hi|hello)&mom <=> ( 'hi' | 'hello' ) & 'mom'

    >>> ftq("Hi(Mom)")
    hi&mom <=> 'hi' & 'mom'

    >>> ftq("(Hi)Mom")
    hi&mom <=> 'hi' & 'mom'

    >>> ftq("Hi(Big)Momma")
    hi&big&momma <=> 'hi' & 'big' & 'momma'

    >>> ftq("foo(bar OR baz)")  # Bug #32071
    foo&(bar|baz) <=> 'foo' & ( 'bar' | 'baz' )


We also support negation

    >>> ftq("NOT Hi")
    !hi <=> !'hi'

    >>> ftq("NOT(Hi AND Mom)")
    !(hi&mom) <=> !( 'hi' & 'mom' )

    >>> ftq("Foo AND NOT Bar")
    foo&!bar <=> 'foo' & !'bar'


The implicit boolean operation is AND

    >>> ftq("Hi Mom")
    hi&mom <=> 'hi' & 'mom'

    >>> ftq("Hi NOT mom")
    hi&!mom <=> 'hi' & !'mom'

    >>> ftq("hi (mom OR mum)")
    hi&(mom|mum) <=> 'hi' & ( 'mom' | 'mum' )

    >>> ftq("(hi OR hello) mom")
    (hi|hello)&mom <=> ( 'hi' | 'hello' ) & 'mom'

    >>> ftq("(hi OR hello) NOT mom")
    (hi|hello)&!mom <=> ( 'hi' | 'hello' ) & !'mom'

    >>> ftq("(hi ho OR hoe) work go")
    (hi&ho|hoe)&work&go <=> ( 'hi' & 'ho' | 'hoe' ) & 'work' & 'go'


'-' symbols are treated by the Postgres FTI parser context sensitive.
If they precede a word, they are removed.

    >>> print(search_same("foo -bar"))
    FTI data: 'bar':2 'foo':1
    query: 'foo' & 'bar'
    match: True

If a '-' precedes a number, it is retained.

    >>> print(search_same("123 -456"))
    FTI data: '-456':2 '123':1
    query: '123' & '-456'
    match: True

Trailing '-' are always ignored.

    >>> print(search_same("bar- 123-"))
    FTI data: '123':2 'bar':1
    query: 'bar' & '123'
    match: True

Repeated '-' are simply ignored by to_tsquery().

    >>> ftq("---foo--- ---bar---")
    ---foo---&---bar--- <=> 'foo' & 'bar'


XXX 2025-01-23 lgp171188: The following doctests have a lot of placeholders
ignoring key values like '&', '<->', and '<2>' since it is not straightforward
to test different values in a doctest based on different PostgreSQL versions.
So these ignored values have been checked in the unit tests in the
lp.services.database.tests.test_text_searching module.

Hyphens surrounded by two words are retained. This reflects the way
how to_tsquery() and to_tsvector() handle such strings.

    >>> print(search_same("foo-bar"))
    FTI data: 'bar':3 'foo':2 'foo-bar':1
    query: 'foo-bar' ... 'foo' ... 'bar'
    match: True

A '-' surrounded by numbers is treated as the sign of the right-hand number.

    >>> print(search_same("123-456"))
    FTI data: '-456':2 '123':1
    query: '123' ... '-456'
    match: True

Punctuation is handled consistently. If a string containing punctuation
appears in an FTI, it can also be passed to ftq(),and a search for this
string finds the indexed text.

    >>> punctuation = "'\"#$%*+,./:;<=>?@[\\]^`{}~"
    >>> for symbol in punctuation:
    ...     print(repr(symbol), search_same("foo%sbar" % symbol))
    ...
    "'" FTI data: 'bar':2 'foo':1 query: 'foo' ... 'bar' match: True
    '"' FTI data: 'bar':2 'foo':1 query: 'foo' ... 'bar' match: True
    '#' FTI data: 'bar':2 'foo':1 query: 'foo' ... 'bar' match: True
    '$' FTI data: 'bar':2 'foo':1 query: 'foo' ... 'bar' match: True
    '%' FTI data: 'bar':2 'foo':1 query: 'foo' ... 'bar' match: True
    '*' FTI data: 'bar':2 'foo':1 query: 'foo' ... 'bar' match: True
    '+' FTI data: 'bar':2 'foo':1 query: 'foo' ... 'bar' match: True
    ',' FTI data: 'bar':2 'foo':1 query: 'foo' ... 'bar' match: True
    '.' FTI data: 'foo.bar':1 query: 'foo.bar' match: True
    '/' FTI data: 'foo/bar':1 query: 'foo/bar' match: True
    ':' FTI data: 'bar':2 'foo':1 query: 'foo' ... 'bar' match: True
    ';' FTI data: 'bar':2 'foo':1 query: 'foo' ... 'bar' match: True
    '<' FTI data: 'bar':2 'foo':1 query: 'foo' ... 'bar' match: True
    '=' FTI data: 'bar':2 'foo':1 query: 'foo' ... 'bar' match: True
    '>' FTI data: 'bar':2 'foo':1 query: 'foo' ... 'bar' match: True
    '?' FTI data: 'bar':2 'foo':1 query: 'foo' ... 'bar' match: True
    '@' FTI data: 'bar':2 'foo':1 query: 'foo' ... 'bar' match: True
    '[' FTI data: 'bar':2 'foo':1 query: 'foo' ... 'bar' match: True
    '\\' FTI data: 'bar':2 'foo':1 query: 'foo' ... 'bar' match: True
    ']' FTI data: 'bar':2 'foo':1 query: 'foo' ... 'bar' match: True
    '^' FTI data: 'bar':2 'foo':1 query: 'foo' ... 'bar' match: True
    '`' FTI data: 'bar':2 'foo':1 query: 'foo' ... 'bar' match: True
    '{' FTI data: 'bar':2 'foo':1 query: 'foo' ... 'bar' match: True
    '}' FTI data: 'bar':2 'foo':1 query: 'foo' ... 'bar' match: True
    '~' FTI data: 'foo':1 '~bar':2 query: 'foo' ... '~bar' match: True

    >>> for symbol in punctuation:
    ...     print(
    ...         repr(symbol), search_same("aa %sbb%s cc" % (symbol, symbol))
    ...     )
    ...
    "'" FTI data: 'aa':1 'bb':2 'cc':3 query: 'aa' & 'bb' & 'cc' match: True
    '"' FTI data: 'aa':1 'bb':2 'cc':3 query: 'aa' & 'bb' & 'cc' match: True
    '#' FTI data: 'aa':1 'bb':2 'cc':3 query: 'aa' & 'bb' & 'cc' match: True
    '$' FTI data: 'aa':1 'bb':2 'cc':3 query: 'aa' & 'bb' & 'cc' match: True
    '%' FTI data: 'aa':1 'bb':2 'cc':3 query: 'aa' & 'bb' & 'cc' match: True
    '*' FTI data: 'aa':1 'bb':2 'cc':3 query: 'aa' & 'bb' & 'cc' match: True
    '+' FTI data: 'aa':1 'bb':2 'cc':3 query: 'aa' & 'bb' & 'cc' match: True
    ',' FTI data: 'aa':1 'bb':2 'cc':3 query: 'aa' & 'bb' & 'cc' match: True
    '.' FTI data: 'aa':1 'bb':2 'cc':3 query: 'aa' & 'bb' & 'cc' match: True
    '/' FTI data: '/bb':2 'aa':1 'cc':3 query: 'aa' & '/bb' & 'cc' match: True
    ':' FTI data: 'aa':1 'bb':2 'cc':3 query: 'aa' & 'bb' & 'cc' match: True
    ';' FTI data: 'aa':1 'bb':2 'cc':3 query: 'aa' & 'bb' & 'cc' match: True
    '<' FTI data: 'aa':1 'bb':2 'cc':3 query: 'aa' & 'bb' & 'cc' match: True
    '=' FTI data: 'aa':1 'bb':2 'cc':3 query: 'aa' & 'bb' & 'cc' match: True
    '>' FTI data: 'aa':1 'bb':2 'cc':3 query: 'aa' & 'bb' & 'cc' match: True
    '?' FTI data: 'aa':1 'bb':2 'cc':3 query: 'aa' & 'bb' & 'cc' match: True
    '@' FTI data: 'aa':1 'bb':2 'cc':3 query: 'aa' & 'bb' & 'cc' match: True
    '[' FTI data: 'aa':1 'bb':2 'cc':3 query: 'aa' & 'bb' & 'cc' match: True
    '\\' FTI data: 'aa':1 'bb':2 'cc':3 query: 'aa' & 'bb' & 'cc' match: True
    ']' FTI data: 'aa':1 'bb':2 'cc':3 query: 'aa' & 'bb' & 'cc' match: True
    '^' FTI data: 'aa':1 'bb':2 'cc':3 query: 'aa' & 'bb' & 'cc' match: True
    '`' FTI data: 'aa':1 'bb':2 'cc':3 query: 'aa' & 'bb' & 'cc' match: True
    '{' FTI data: 'aa':1 'bb':2 'cc':3 query: 'aa' & 'bb' & 'cc' match: True
    '}' FTI data: 'aa':1 'bb':2 'cc':3 query: 'aa' & 'bb' & 'cc' match: True
    '~' FTI data: 'aa':1 'bb':2 'cc':3 query: 'aa' & '~bb' & 'cc' match: False

XXX Abel Deuring 2012-06-20 bug=1015511: Note that the last line above
shows a bug: The FTI data for the string "aa ~bb~ cc" contains the words
'aa', 'bb', 'cc', while the ts_query object for the same text contains
'aa', '~bb', 'cc', hence the query does not match the string. More details_

XXX Abel Deuring 2012-06-20 bug=1015519: XML tags cannot be searched.

Tags are simply dropped from the FTI data. The terms show up without
brackets in parsed queries as a consequence of phrase operator stripping
added for PostgreSQL 9.6.

    >>> print(search("some text <div>whatever</div>", "<div>"))
    FTI data: 'text':2 'whatev':3 query: 'div' match: False

Of course, omitting '<' and '>'from the query does not help.

    >>> print(search("some text <div>whatever</div>", "div"))
    FTI data: 'text':2 'whatev':3 query: 'div' match: False

The symbols '&', '|' and '!' are treated as operators by to_tsquery();
to_tsvector() treats them as whitespace. ftq() converts the words 'AND',
'OR', 'NOT' are into these operators expected by to_tsquery(), and it
replaces the symbols '&', '|' and '!' with spaces. This avoids
surprising search results when the operator symbols appear accidentally
in search terms, e.g., by using a plain copy of a source code line as
the search term.

    >>> ftq("cool!")
    cool <=> 'cool'

    >>> print(search_same("Shell scripts usually start with #!/bin/sh."))
    FTI data: '/bin/sh':6 'script':2 'shell':1 'start':4 'usual':3
    query: 'shell' & 'script' & 'usual' & 'start' & '/bin/sh'
    match: True

    >>> print(search_same("int foo = (bar & ! baz) | bla;"))
    FTI data: 'bar':3 'baz':4 'bla':5 'foo':2 'int':1
    query: 'int' & 'foo' & 'bar' & 'baz' & 'bla'
    match: True

Queries containing only punctuation symbols yield an empty ts_query
object. Note that _ftq() first replaces the '!' with a ' '; later on,
_ftq() joins the two remaining terms '?' and '.' with the "AND"
operator '&'. Finally, to_tsquery() detects the AND combination of
two symbols that are not tokenized and returns null.

    >>> ftq("?!.")  # Bug 1020443
    ?&. <=> None

Email addresses are retained as a whole, both by to_tsvector() and by
ftq().

    >>> print(search_same("foo@bar.com"))
    FTI data: 'foo@bar.com':1 query: 'foo@bar.com' match: True

File names are retained as a whole.

    >>> print(search_same("foo-bar.txt"))
    FTI data: 'foo-bar.txt':1 query: 'foo-bar.txt' match: True

Some punctuation we pass through to tsearch2 for it to handle.
NB. This gets stemmed, see below.

    >>> print(search_same("shouldn't"))
    FTI data: 'shouldn':1 query: 'shouldn' match: True

Bug #44913 - Unicode characters in the wrong place.

    >>> print(search_same("abc-a\N{LATIN SMALL LETTER C WITH CEDILLA}"))
    FTI data: 'abc':2 'abc-aç':1 'aç':3
    query: 'abc-aç' ... 'abc' ... 'aç'
    match: True

Cut & Paste of 'Smart' quotes. Note that the quotation mark is retained
in the FTI.

    >>> print(search_same("a-a\N{RIGHT DOUBLE QUOTATION MARK}"))
    FTI data: 'a-a”':1 'a”':3 query: 'a-a”' ... 'a”' match: True

    >>> print(
    ...     search_same(
    ...         "\N{LEFT SINGLE QUOTATION MARK}a.a"
    ...         "\N{RIGHT SINGLE QUOTATION MARK}"
    ...     )
    ... )
    FTI data: 'a’':2 '‘a':1 query: '‘a' ... 'a’' match: True


Bug #44913 - Nothing but stopwords in a query needing repair

    >>> print(search_same("a)a"))
    FTI data:  query: None match: None


Stop words (words deemed too common in English to search on) are removed
from queries by tsearch2.

    >>> print(search_same("Don't do it harder!"))
    FTI data: 'harder':5 query: 'harder' match: True


Note that some queries will return None after compilation, because they
contained nothing but stop words or punctuation.

    >>> print(search_same("don't do it!"))
    FTI data:  query: None match: None

    >>> print(search_same(",,,"))
    FTI data:  query: None match: None


Queries containing nothing except whitespace, boolean operators and
punctuation will just return None.

Note in the fourth example below that the '-' left in the query by _ftq()
is ignored by to_tsquery().

    >>> ftq(" ")
    None <=> None
    >>> ftq("AND")
    None <=> None
    >>> ftq(" AND (!)")
    None <=> None
    >>> ftq("-")
    - <=> None


Words are also stemmed by tsearch2 (using the English stemmer).

    >>> ftq("administrators")
    administrators <=> 'administr'

    >>> ftq("administrate")
    administrate <=> 'administr'

Note that stemming is not always idempotent:

    >>> ftq("extension")
    extension <=> 'extens'
    >>> ftq("extens")
    extens <=> 'exten'

Dud queries are 'repaired', such as doubled operators, trailing operators
or invalid leading operators

    >>> ftq("hi AND OR mom")
    hi&mom <=> 'hi' & 'mom'

    >>> ftq("(hi OR OR hello) AND mom")
    (hi|hello)&mom <=> ( 'hi' | 'hello' ) & 'mom'

    >>> ftq("(hi OR AND hello) AND mom")
    (hi|hello)&mom <=> ( 'hi' | 'hello' ) & 'mom'

    >>> ftq("(hi OR NOT AND hello) AND mom")
    (hi|!hello)&mom <=> ( 'hi' | !'hello' ) & 'mom'

    >>> ftq("(hi OR - AND hello) AND mom")
    (hi|-&hello)&mom <=> ( 'hi' | 'hello' ) & 'mom'

    >>> ftq("hi AND mom AND")
    hi&mom <=> 'hi' & 'mom'

    >>> ftq("AND hi AND mom")
    hi&mom <=> 'hi' & 'mom'

    >>> ftq("(AND hi OR hello) AND mom")
    (hi|hello)&mom <=> ( 'hi' | 'hello' ) & 'mom'

    >>> ftq("() hi mom ( ) ((NOT OR((AND)))) :-)")
    (hi&mom&-) <=> 'hi' & 'mom'

    >>> ftq("(hi mom")
    hi&mom <=> 'hi' & 'mom'

    >>> ftq("(((hi mom")
    ((hi&mom)) <=> 'hi' & 'mom'

    >>> ftq("hi mom)")
    hi&mom <=> 'hi' & 'mom'

    >>> ftq("hi mom)))")
    ((hi&mom)) <=> 'hi' & 'mom'

    >>> ftq("hi (mom")
    hi&mom <=> 'hi' & 'mom'

    >>> ftq("hi) mom")
    hi&mom <=> 'hi' & 'mom'

    >>> ftq("(foo .")  # Bug 43245
    foo&. <=> 'foo'

    >>> ftq("(foo.")
    foo. <=> 'foo'

    Bug #54972

    >>> ftq("a[a\n[a")
    a[a&[a <=> None

    Bug #96698

    >>> ftq("f)(")
    f <=> 'f'

    Bug #174368

    >>> ftq(")foo(")
    foo <=> 'foo'

    Bug #160236

    >>> ftq("foo AND AND bar-baz")
    foo&bar-baz <=> 'foo' ... 'bar-baz' ... 'bar' ... 'baz'

    >>> ftq("foo OR OR bar.baz")
    foo|bar.baz <=> 'foo' | 'bar.baz'


Phrase Searching
----------------
We do not support searching for quoted phrases. This is technically
possible, but not trivial. The database side of implementing this would
simply be to make `ftq(text)` convert "a b" to (a&b). However, we then
need to filter the returned results and that filter needs to be aware of
what rows are being indexed.


Ranking
-------

We have ranking information stored in the indexes, as specified in fti.py.
The rank of a result is calculated using the ts_rank() function.

    >>> runsql(
    ...     r"""
    ...     SELECT
    ...         name, ts_rank(fti, ftq('gnome')) AS rank
    ...     FROM product
    ...     WHERE fti @@ ftq('gnome')
    ...     ORDER BY rank DESC, name
    ...     """
    ... )
    gnome-terminal            0.80
    applets                   0.69
    gnomebaker                0.28
    python-gnome2-dev         0.14
    evolution                 0.12

You can also build complex multi table queries and mush all the
ranked results together. This query does a full text search on
the Bug and Message tables, as well as substring name searches on
SourcepackageName.name and Product.name. The ts_rank() function returns an
float between 0 and 1, so I just chose some arbitrary constants for name
matches that seemed appropriate. It is also doing a full text search
against the Product table, and manually lowering the rank (again using
an arbitrary constant that seemed appropriate).

    >>> runsql(
    ...     r"""
    ...   SELECT title, max(ranking) FROM (
    ...    SELECT Bug.title,ts_rank(Bug.fti||Message.fti,ftq('firefox'))
    ...    AS ranking
    ...    FROM Bug, BugMessage, Message
    ...    WHERE Bug.id = BugMessage.bug AND Message.id = BugMessage.message
    ...       AND (Bug.fti @@ ftq('firefox') OR Message.fti @@ ftq('firefox'))
    ...    UNION
    ...    SELECT Bug.title, 0.70 AS ranking
    ...    FROM Bug, BugTask, SourcepackageName
    ...    WHERE Bug.id = BugTask.bug
    ...       AND BugTask.sourcepackagename = SourcepackageName.id
    ...       AND SourcepackageName.name LIKE lower('%firefox%')
    ...    UNION
    ...    SELECT Bug.title, 0.72 AS ranking
    ...    FROM Bug, BugTask, Product
    ...    WHERE Bug.id = BugTask.bug
    ...       AND BugTask.product = Product.id
    ...       AND Product.name LIKE lower('%firefox%')
    ...    UNION
    ...    SELECT Bug.title, ts_rank(Product.fti, ftq('firefox')) - 0.3
    ...    AS ranking
    ...    FROM Bug, BugTask, Product
    ...    WHERE Bug.id = BugTask.bug
    ...       AND BugTask.product = Product.id
    ...       AND Product.fti @@ ftq('firefox')
    ...    ) AS BugMatches
    ...   GROUP BY title
    ...   HAVING max(ranking) > 0.2
    ...   ORDER BY max(ranking) DESC, title
    ...   """
    ... )
    Firefox crashes when S... 0.72
    Firefox does not suppo... 0.72
    Firefox install instru... 0.72
    Reflow problems with c... 0.72
    Blackhole Trash folder    0.70
    Bug Title Test            0.70
    Printing doesn't work     0.70


Natural Language Phrase Query
-----------------------------

The standard boolean searches of tsearch2 are fine, but sometime you
want more fuzzy searches.

For example, the KDE bug tracker has a guided bug submission form where
the user first enters the summary of their problem. A list of similar
bug reports is then displayed. The key here is 'similar', we want bug
reports that have some words in common with the summary and we want the
ones that are the most similar listed first. We don't necessarily want
that all words are matched. So using a boolean AND search is too
restrictive and using a simple OR search would probably give more noise
than necessary. The KDE bug tracker is using MySQL fulltext indexes
which support 'natural language search'.

Unfortunately, tsearch2 doesn't implement a 'similar' or 'fuzzy' match
operator. But we can implement an algorithm similar to the MySQL one on
top of the basic boolean search. (The MySQL full text search algorithm
is described at
http://dev.mysql.com/doc/refman/5.0/en/fulltext-search.html) Basically,
the algorithm is simple, it removes stop words, short words and words
that appear in 50% or more of the rows (since these words are common,
they have less semantic value.) The remaining terms are then matched
against rows (probably using an OR search). The returned rows are sorted
by relevance computed using an algorithm similar to TD-IDF
(Term Frequency; Inverse Document Frequency).

Implementing something similar with tsearch2 is straightforward:
tsearch2 to_tsquery() already removes stop-words (it also stems the
words). Relevance can be computed using the ts_rank() or ts_rank_cd()
functions. These are not TD-IDF scoring functions, but they take into
account where the words appeared (in the case of ts_rank()) or proximity
of the words (in the case of ts_rank_cd()). Both scoring functions can
normalize based on document length. So the only part left to implement
is the >50% filtering part. Howevert the > 50% filtering is very expensive,
and so is processing every single returned item (> 200000 for common queries
on Ubuntu) - so we are disabling this and reworking from the ground up.


nl_term_candidates()
~~~~~~~~~~~~~~~~~~~~

To find the terms in a search phrase that are candidates for the search,
we can use the nl_term_candidates() function. This function uses ftq()
internally to removes stop words and other words that will be ignored
by tsearch2. All words are also stemmed.

    >>> from lp.services.database.nl_search import nl_term_candidates

    >>> for term in nl_term_candidates("When I start firefox, it crashes"):
    ...     print(term)
    ...
    start
    firefox
    crash

It returns an empty list when there is only stop-words in the query:

    >>> nl_term_candidates("how do I do this?")
    []

Except for the hyphenation character, all non-word characters are ignored:

    >>> for term in nl_term_candidates(
    ...     "Will the ''|'' character (inside a ''quoted'' string) " "work???"
    ... ):
    ...     print(term)
    charact
    insid
    quot
    string
    work


nl_phrase_search()
~~~~~~~~~~~~~~~~~~

To get the actual tsearch2 query that should be run, you will use the
nl_phrase_search() function. This one takes two mandatory parameters and
two optional ones. You pass in the search phrase and a database model class.

The original nl_phrase_search has proved slow, so there are now two
implementations in the core.

First we describe the slow implementation.

The select method of that class will be use to count the number of rows
that is matched by each term. Term matching 50% or more of the total
rows will be excluded from the final search.

    >>> from lp.services.database.nl_search import nl_phrase_search
    >>> from lp.answers.model.question import Question

More than 50% of the questions matches firefox:

    >>> from lp.services.database.interfaces import IStore
    >>> from lp.services.database.stormexpr import fti_search
    >>> question_count = IStore(Question).find(Question).count()
    >>> firefox_questions = (
    ...     IStore(Question)
    ...     .find(Question, fti_search(Question, "firefox"))
    ...     .count()
    ... )
    >>> float(firefox_questions) / question_count > 0.50
    True

So firefox will be removed from the final query:

    >>> print(
    ...     nl_phrase_search(
    ...         "system is slow when running firefox",
    ...         Question,
    ...         fast_enabled=False,
    ...     )
    ... )
    system|slow|run

    >>> nl_term_candidates("how do I do this?")
    []
    >>> nl_phrase_search("how do I do this?", Question)
    ''

The fast code path does not remove any terms. Rather it uses an & query over
all the terms combined with an & query for each ordinal-1 subset of the terms:

    >>> print(
    ...     nl_phrase_search(
    ...         "system is slow when running firefox on ubuntu", Question
    ...     )
    ... )
    ... # noqa
    (firefox&run&slow&system&ubuntu)|(run&slow&system&ubuntu)|(firefox&slow&system&ubuntu)|(firefox&run&system&ubuntu)|(firefox&run&slow&ubuntu)|(firefox&run&slow&system)

Short queries are expanded more simply:

    >>> print(nl_phrase_search("system is slow", Question))
    slow|system


Using other constraints
.......................

You can pass a third parameter to the function that will be used as
additional constraints to determine the total number of rows that
could be matched. For example, when searching questions on the firefox
product more than 50% have the word 'get' in (which surprisingly isn't
considered a stop word by tsearch2).

    >>> from lp.registry.interfaces.product import IProductSet
    >>> from lp.registry.model.product import Product
    >>> firefox_product = getUtility(IProductSet).getByName("firefox")

    >>> firefox_count = (
    ...     IStore(Question)
    ...     .find(Question, Question.product_id == firefox_product.id)
    ...     .count()
    ... )
    >>> get_questions = (
    ...     IStore(Question)
    ...     .find(Question, fti_search(Question, "get"))
    ...     .count()
    ... )
    >>> float(get_questions) / firefox_count > 0.50
    True

    >>> print(
    ...     nl_phrase_search(
    ...         "firefox gets very slow on flickr",
    ...         Question,
    ...         [Question.product == firefox_product, Product.active],
    ...         fast_enabled=False,
    ...     )
    ... )
    slow|flickr

When the query only has stop words in it, the returned query will be the empty
string:

    >>> nl_phrase_search("will not do it", Question)
    ''

When there are no candidate rows, only stemming and stop words removal
is done.

    >>> IStore(Question).find(Question, Question.product_id == -1).count()
    0
    >>> print(
    ...     nl_phrase_search(
    ...         "firefox is very slow on flickr",
    ...         Question,
    ...         [Question.product == -1],
    ...     )
    ... )
    (firefox&flickr&slow)|(flickr&slow)|(firefox&slow)|(firefox&flickr)


No keywords filtering with few rows
...................................

The 50% rule is really useful only when there are many rows. When there
only very few rows, that keyword elimination becomes a problem since
keywords could be eliminated. For that reason, when there are less than
5 candidates rows, keywords elimination is skipped.

For example, there are less than 5 questions filed on the
mozilla-firefox source package.

    >>> from lp.registry.interfaces.distribution import IDistributionSet
    >>> ubuntu = getUtility(IDistributionSet).getByName("ubuntu")
    >>> firefox_package = ubuntu.getSourcePackage("mozilla-firefox")
    >>> firefox_package_id = firefox_package.sourcepackagename.id
    >>> firefox_package_questions = IStore(Question).find(
    ...     Question,
    ...     Question.distribution_id == ubuntu.id,
    ...     Question.sourcepackagename_id == firefox_package_id,
    ... )
    >>> firefox_package_questions.count() < 5
    True

And more than half of these contain the keyword "firefox" in them:

    >>> firefox_questions = IStore(Question).find(
    ...     Question, fti_search(Question, "firefox")
    ... )
    >>> float(get_questions) / firefox_package_questions.count() > 0.50
    True

But the keyword is still keep because there are only less than 5
questions:

    >>> print(
    ...     nl_phrase_search(
    ...         "firefox is slow",
    ...         Question,
    ...         [
    ...             Question.distribution == ubuntu,
    ...             Question.sourcepackagename
    ...             == firefox_package.sourcepackagename,
    ...         ],
    ...     )
    ... )
    firefox|slow
