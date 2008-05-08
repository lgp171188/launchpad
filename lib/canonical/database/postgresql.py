# Copyright 2004-2005 Canonical Ltd.  All rights reserved.
"""
PostgreSQL specific helper functions, such as database introspection
and table manipulation
"""

__metaclass__ = type

import re

from sqlbase import quote, quoteIdentifier, sqlvalues

def listReferences(cur, table, column, _state=None):
    """Return a list of all foreign key references to the given table column

    `table` and `column` are both case sensitive strings (so they should
    usually be lowercase strings as per PostgreSQL default behavior).

    `cur` is an open DB-API cursor

    returns `[(from_table, from_column, to_table, to_column, update, delete)]`

    `from` entries refer to the `to` entries. This method is recursive -
    not only does it return all references to the given table column, but
    also all references to those references etc. (indirect references).

    `update` is the update clause (eg. on update cascade)
    `delete` is the delete clause (eg. on delete cascade)

    Entries are returned in order traversed, so with care this can be used
    to change keys.

    >>> for r in listReferences(cur, 'a', 'aid'):
    ...     print repr(r)
    ('a', 'selfref', 'a', 'aid', u'a', u'a')
    ('b', 'aid', 'a', 'aid', u'c', u'c')
    ('c', 'aid', 'b', 'aid', u'a', u'a')
    ('d', 'aid', 'b', 'aid', u'a', u'a')

    Of course, there might not be any references

    >>> listReferences(cur, 'a', 'selfref')
    []

    """

    sql = """
        SELECT DISTINCT
            src_pg_class.relname AS srctable,
            src_pg_attribute.attname AS srccol,
            ref_pg_class.relname AS reftable,
            ref_pg_attribute.attname AS refcol,
            pg_constraint.confupdtype,
            pg_constraint.confdeltype
        FROM
            pg_constraint
                JOIN pg_class AS src_pg_class
                    ON src_pg_class.oid = pg_constraint.conrelid
                JOIN pg_class AS ref_pg_class
                    ON ref_pg_class.oid = pg_constraint.confrelid
                JOIN pg_attribute AS src_pg_attribute
                    ON src_pg_class.oid = src_pg_attribute.attrelid
                JOIN pg_attribute AS ref_pg_attribute
                    ON ref_pg_class.oid = ref_pg_attribute.attrelid,
            generate_series(0,10) pos(n)
        WHERE
            contype = 'f'
            AND ref_pg_class.relname = %(table)s
            AND ref_pg_attribute.attname = %(column)s
            AND src_pg_attribute.attnum = pg_constraint.conkey[n]
            AND ref_pg_attribute.attnum = pg_constraint.confkey[n]
            AND NOT src_pg_attribute.attisdropped
            AND NOT ref_pg_attribute.attisdropped
        ORDER BY src_pg_class.relname, src_pg_attribute.attname
        """
    cur.execute(sql, vars())

    # Recursive function. Create the list that stores our state.
    # We pass this down to subinvocations to avoid loops.
    if _state is None:
        _state = []

    for t in cur.fetchall():
        # t == (src_table, src_column, dest_table, dest_column, upd, del)
        if t not in _state: # Avoid loops
            _state.append(t)
            # Recurse, Locating references to the reference we just found.
            listReferences(cur, t[0], t[1], _state)
    # Don't sort. This way, we return the columns in order of distance
    # from the original (table, column), making it easier to change keys
    return _state

def listUniques(cur, table, column):
    '''Return a list of unique indexes on `table` that include the `column`

    `cur` must be an open DB-API cursor.

    Returns [ (column, [...]) ]. The column passed in will always be
    included in the tuple.

    Simple UNIQUE index

    >>> listUniques(cur, 'b', 'aid')
    [('aid',)]

    Primary keys are UNIQUE indexes too

    >>> listUniques(cur, 'a', 'aid')
    [('aid',)]

    Compound indexes

    >>> listUniques(cur, 'c', 'aid')
    [('aid', 'bid')]
    >>> listUniques(cur, 'c', 'bid')
    [('aid', 'bid')]

    And any combination

    >>> l = listUniques(cur, 'd', 'aid')
    >>> l.sort()
    >>> l
    [('aid',), ('aid', 'bid')]

    If there are no UNIQUE indexes using the secified column

    >>> listUniques(cur, 'a', 'selfref')
    []

    '''

    # Retrieve the attributes for the table
    attributes = {}
    sql = '''
        SELECT
            a.attnum,
            a.attname
        FROM
            pg_class AS t JOIN pg_attribute AS a ON t.oid = a.attrelid
        WHERE
            t.relname = %(table)s
            AND a.attnum > 0
        '''
    cur.execute(sql, vars())
    for num,name in cur.fetchall():
        attributes[int(num)] = name

    # Initialize our return value
    rv = []

    # Retrive the UNIQUE indexes.
    sql = '''
        SELECT
            i.indkey
        FROM
            pg_class AS t JOIN pg_index AS i ON i.indrelid = t.oid
        WHERE
            i.indisunique = true
            AND t.relname = %(table)s
        '''
    cur.execute(sql, vars())
    for indkey, in cur.fetchall():
        # We have a space seperated list of integer keys into the attribute
        # mapping. Ignore the 0's, as they indicate a function and we don't
        # handle them.
        keys = [
            attributes[int(key)]
                for key in indkey.split()
                    if int(key) > 0
            ]
        if column in keys:
            rv.append(tuple(keys))
    return rv

def listSequences(cur):
    """Return a list of (schema, sequence, table, column) tuples.

    `table` and `column` refer to the column that appears to be automatically
    populated from the sequence. They will be None if this sequence is
    standalone.

    >>> for r in listSequences(cur):
    ...     print repr(r)
    ('public', 'a_aid_seq', 'a', 'aid')
    ('public', 'standalone', None, None)

    """
    sql = """
        SELECT
            n.nspname AS schema,
            c.relname AS seqname
        FROM
            pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE
            c.relkind = 'S'
            AND n.nspname NOT IN ('pg_catalog', 'pg_toast')
            AND pg_table_is_visible(c.oid)
        ORDER BY schema, seqname
        """
    rv = []
    cur.execute(sql)
    for schema, sequence in list(cur.fetchall()):
        match = re.search('^(\w+)_(\w+)_seq$', sequence)
        if match is None:
            rv.append( (schema, sequence, None, None) )
        else:
            table = match.group(1)
            column = match.group(2)
            sql = """
                SELECT count(*)
                FROM
                    pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    JOIN pg_attribute a ON c.oid = a.attrelid
                WHERE
                    a.attnum > 0 AND NOT a.attisdropped
                    AND n.nspname = %(schema)s
                    AND c.relname = %(table)s
                    AND a.attname = %(column)s
                """
            cur.execute(sql, vars())
            num = cur.fetchone()[0]
            if num == 1:
                rv.append( (schema, sequence, table, column) )
            else:
                rv.append( (schema, sequence, None, None) )
    return rv

def prepare_resetSequences(cur):
    """Return SQL that will reset table sequences to match the data in them.
    """
    stmt = []
    for schema, sequence, table, column in listSequences(cur):
        if table is None or column is None:
            continue
        sql = "SELECT max(%s) FROM %s" % (
                quoteIdentifier(column), quoteIdentifier(table)
                )
        cur.execute(sql)
        last_value = cur.fetchone()[0]
        if last_value is None:
            last_value = 1
            flag = 'false'
        else:
            flag = 'true'
        sql = "setval(%s, %d, %s)" % (
                quote('%s.%s' % (schema, sequence)), int(last_value), flag
                )
        stmt.append(sql)
    stmt = 'SELECT ' + ', '.join(stmt)
    return stmt

def resetSequences(cur):
    """Reset table sequences to match the data in them.

    Goes through the database resetting the values of sequences to match
    what is in their corresponding tables, where corresponding tables are
    known.

    >>> cur.execute("SELECT nextval('a_aid_seq')")
    >>> int(cur.fetchone()[0])
    1
    >>> cur.execute("SELECT nextval('a_aid_seq')")
    >>> cur.execute("SELECT nextval('a_aid_seq')")
    >>> resetSequences(cur)
    >>> cur.execute("SELECT nextval('a_aid_seq')")
    >>> int(cur.fetchone()[0])
    1
    """
    cur.execute(prepare_resetSequences(cur))

# Regular expression used to parse row count estimate from EXPLAIN output
_rows_re = re.compile("rows=(\d+)\swidth=")

def estimateRowCount(cur, query):
    """Ask the PostgreSQL query optimizer for an estimated rowcount.

    Stats will only be acurate if the table has been ANALYZEd recently.
    With standard Ubuntu installs, the autovacuum daemon does this.

    >>> cur.execute("INSERT INTO A (selfref) VALUES (NULL)")
    >>> cur.execute("ANALYZE A")
    >>> estimateRowCount(cur, "SELECT * FROM A")
    1
    >>> cur.executemany(
    ...     "INSERT INTO A (selfref) VALUES (NULL)",
    ...     [(i,) for i in range(100)]
    ...     )
    >>> cur.execute("ANALYZE A")
    >>> estimateRowCount(cur, "SELECT * FROM A")
    101
    """
    cur.execute("EXPLAIN " + query)
    first_line = cur.fetchone()[0]
    match = _rows_re.search(first_line)
    if match is None:
        raise RuntimeError("Unexpected EXPLAIN output %s" % repr(first_line))
    return int(match.group(1))


def have_table(cur, table):
    """Is there a table of the given name?

    Returns boolean answer.

    >>> have_table(cur, 'thistabledoesnotexist_i_hope')
    False
    >>> cur.execute("CREATE TEMP TABLE atesttable (x integer)")
    >>> have_table(cur, 'atesttable')
    True
    >>> drop_tables(cur, 'atesttable')
    >>> have_table(cur, 'atesttable')
    False
    """
    cur.execute('''
        SELECT count(*) > 0
        FROM pg_tables
        WHERE tablename=%s
    ''' % str(quote(table)))
    return (cur.fetchall()[0][0] != 0)


def table_has_column(cur, table, column):
    """Does a table of the given name exist and have the given column?

    Returns boolean answer.

    >>> cur.execute("CREATE TEMP TABLE atesttable (x integer)")
    >>> table_has_column(cur, 'atesttable', 'x')
    True
    >>> table_has_column(cur, 'atesttable', 'z')
    False
    >>> table_has_column(cur, 'thistabledoesnotexist_i_hope', 'pphwt')
    False
    >>> drop_tables(cur, 'atesttable')
    >>> table_has_column(cur, 'atesttable', 'x')
    False
    """
    cur.execute('''
        SELECT count(*) > 0
        FROM pg_attribute
        JOIN pg_class ON pg_class.oid = attrelid
        WHERE relname=%s
            AND attname=%s
    ''' % sqlvalues(table, column))
    return (cur.fetchall()[0][0] != 0)


def drop_tables(cur, tables):
    """Drop given tables (a list, one name, or None), if they exist.

    >>> cur.execute("CREATE TEMP TABLE foo (a integer)")
    >>> have_table(cur, 'foo')
    True
    >>> table_has_column(cur, 'foo', 'a')
    True
    >>> cur.execute("CREATE TEMP TABLE bar (b varchar)")
    >>> have_table(cur, 'bar')
    True
    >>> cur.execute("INSERT INTO foo values (1)")
    >>> cur.execute("INSERT INTO bar values ('hi mom')")
    >>> drop_tables(cur, ['thistabledoesnotexist_i_hope', 'foo', 'bar'])
    >>> have_table(cur, 'foo')
    False
    >>> have_table(cur, 'bar')
    False
    >>> drop_tables(cur, [])    # No explosion
    >>> drop_tables(cur, None)  # No wailing sirens
    """
    if tables is None or len(tables) == 0:
        return
    if isinstance(tables, basestring):
        tables = [tables]

    # This syntax requires postgres 8.2 or better
    cur.execute("DROP TABLE IF EXISTS %s" % ','.join(tables))


def allow_sequential_scans(cur, permission):
    """Allow database to ignore indexes and scan sequentially when it wants?

    DO NOT USE THIS WITHOUT REVIEW BY A DBA.  When you find yourself wanting
    this function, chances are you're really hiding a bug in your code.

    This is an unfortunate hack.  In some cases we have found that postgres
    will resort to costly sequential scans when a perfectly good index is
    available.  Specifically, this happened when we deleted one-third or so of
    a table's rows without an ANALYZE (as done by autovacuum) on the indexed
    column(s).  Telling the database to regenerate its statistics for one
    primary-key indexed column costs almost nothing, but it will block for an
    autovacuum to complete.  Autovacuums can take a long time, and currently
    cannot be disabled temporarily or selectively.

    Instead, this function lets us tell the database to ignore the index
    degradation, and rely on autovacuum to restore it periodically.  Pass a
    True or a False to change the setting for the ongoing database session.
    Default in PostgreSQL is False, though we seem to have it set to True in
    some of our databases.

    >>> allow_sequential_scans(cur, True)
    >>> cur.execute("SHOW enable_seqscan")
    >>> print cur.fetchall()[0][0]
    on

    >>> allow_sequential_scans(cur, False)
    >>> cur.execute("SHOW enable_seqscan")
    >>> print cur.fetchall()[0][0]
    off
    """
    permission_value = 'false'
    if permission:
        permission_value = 'true'

    cur.execute("SET enable_seqscan=%s" % permission_value)


if __name__ == '__main__':
    import psycopg
    con = psycopg.connect('dbname=launchpad_dev user=launchpad')
    cur = con.cursor()

    for table, column in listReferences(cur, 'person', 'id'):
        print '%32s %32s' % (table, column)

