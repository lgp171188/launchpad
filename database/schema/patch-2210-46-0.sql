-- Copyright 2021 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

-- Replace all PL/Python2 functions with PL/Python3 equivalents.

CREATE EXTENSION IF NOT EXISTS plpython3u WITH SCHEMA pg_catalog;

COMMENT ON EXTENSION plpython3u IS 'PL/Python3U untrusted procedural language';

CREATE OR REPLACE FUNCTION _ftq(text) RETURNS text
    LANGUAGE plpython3u IMMUTABLE STRICT
    AS $_$
        import re

        # I think this method would be more robust if we used a real
        # tokenizer and parser to generate the query string, but we need
        # something suitable for use as a stored procedure which currently
        # means no external dependencies.

        query = args[0]
        ## plpy.debug('1 query is %s' % repr(query))

        # Replace tsquery operators with ' '. '<' begins all the phrase
        # search operators, and a standalone '>' is fine.
        query = re.sub('[|&!<]', ' ', query)

        # Normalize whitespace
        query = re.sub("\s+"," ", query)

        # Convert AND, OR, NOT to tsearch2 punctuation
        query = re.sub(r"\bAND\b", "&", query)
        query = re.sub(r"\bOR\b", "|", query)
        query = re.sub(r"\bNOT\b", " !", query)
        ## plpy.debug('2 query is %s' % repr(query))

        # Deal with unwanted punctuation.
        # ':' is used in queries to specify a weight of a word.
        # '\' is treated differently in to_tsvector() and to_tsquery().
        punctuation = r'[:\\]'
        query = re.sub(r"%s+" % (punctuation,), " ", query)
        ## plpy.debug('3 query is %s' % repr(query))

        # Now that we have handle case sensitive booleans, convert to lowercase
        query = query.lower()

        # Remove unpartnered bracket on the left and right
        query = re.sub(r"(?ux) ^ ( [^(]* ) \)", r"(\1)", query)
        query = re.sub(r"(?ux) \( ( [^)]* ) $", r"(\1)", query)

        # Remove spurious brackets
        query = re.sub(r"\(([^\&\|]*?)\)", r" \1 ", query)
        ## plpy.debug('5 query is %s' % repr(query))

        # Insert & between tokens without an existing boolean operator
        # ( not proceeded by (|&!
        query = re.sub(r"(?<![\(\|\&\!])\s*\(", "&(", query)
        ## plpy.debug('6 query is %s' % repr(query))
        # ) not followed by )|&
        query = re.sub(r"\)(?!\s*(\)|\||\&|\s*$))", ")&", query)
        ## plpy.debug('6.1 query is %s' % repr(query))
        # Whitespace not proceded by (|&! not followed by &|
        query = re.sub(r"(?<![\(\|\&\!\s])\s+(?![\&\|\s])", "&", query)
        ## plpy.debug('7 query is %s' % repr(query))

        # Detect and repair syntax errors - we are lenient because
        # this input is generally from users.

        # Fix unbalanced brackets
        openings = query.count("(")
        closings = query.count(")")
        if openings > closings:
            query = query + " ) "*(openings-closings)
        elif closings > openings:
            query = " ( "*(closings-openings) + query
        ## plpy.debug('8 query is %s' % repr(query))

        # Strip ' character that do not have letters on both sides
        query = re.sub(r"((?<!\w)'|'(?!\w))", "", query)

        # Brackets containing nothing but whitespace and booleans, recursive
        last = ""
        while last != query:
            last = query
            query = re.sub(r"\([\s\&\|\!]*\)", "", query)
        ## plpy.debug('9 query is %s' % repr(query))

        # An & or | following a (
        query = re.sub(r"(?<=\()[\&\|\s]+", "", query)
        ## plpy.debug('10 query is %s' % repr(query))

        # An &, | or ! immediatly before a )
        query = re.sub(r"[\&\|\!\s]*[\&\|\!]+\s*(?=\))", "", query)
        ## plpy.debug('11 query is %s' % repr(query))

        # An &,| or ! followed by another boolean.
        query = re.sub(r"(?ux) \s* ( [\&\|\!] ) [\s\&\|]+", r"\1", query)
        ## plpy.debug('12 query is %s' % repr(query))

        # Leading & or |
        query = re.sub(r"^[\s\&\|]+", "", query)
        ## plpy.debug('13 query is %s' % repr(query))

        # Trailing &, | or !
        query = re.sub(r"[\&\|\!\s]+$", "", query)
        ## plpy.debug('14 query is %s' % repr(query))

        # If we have nothing but whitespace and tsearch2 operators,
        # return NULL.
        if re.search(r"^[\&\|\!\s\(\)]*$", query) is not None:
            return None

        ## plpy.debug('15 query is %s' % repr(query))

        return query or None
        $_$;

CREATE OR REPLACE FUNCTION assert_patch_applied(major integer, minor integer, patch integer) RETURNS boolean
    LANGUAGE plpython3u STABLE
    AS $$
    rv = plpy.execute("""
        SELECT * FROM LaunchpadDatabaseRevision
        WHERE major=%d AND minor=%d AND patch=%d
        """ % (major, minor, patch))
    if len(rv) == 0:
        raise Exception(
            'patch-%d-%02d-%d not applied.' % (major, minor, patch))
    else:
        return True
$$;

CREATE OR REPLACE FUNCTION valid_bug_name(text) RETURNS boolean
    LANGUAGE plpython3u IMMUTABLE STRICT
    AS $_$
    import re
    name = args[0]
    pat = r"^[a-z][a-z0-9+\.\-]+$"
    if re.match(pat, name):
        return 1
    return 0
$_$;

CREATE OR REPLACE FUNCTION valid_name(text) RETURNS boolean
    LANGUAGE plpython3u IMMUTABLE STRICT
    AS $$
    import re
    name = args[0]
    pat = r"^[a-z0-9][a-z0-9\+\.\-]*\Z"
    if re.match(pat, name):
        return 1
    return 0
$$;

CREATE OR REPLACE FUNCTION debversion_sort_key(version text) RETURNS text
    LANGUAGE plpython3u IMMUTABLE STRICT
    AS $_$
    # If this method is altered, then any functional indexes using it
    # need to be rebuilt.
    import re

    VERRE = re.compile("(?:([0-9]+):)?(.+?)(?:-([^-]+))?$")

    MAP = "0123456789ABCDEFGHIJKLMNOPQRSTUV"

    epoch, version, release = VERRE.match(args[0]).groups()
    key = []
    for part, part_weight in ((epoch, 3000), (version, 2000), (release, 1000)):
        if not part:
            continue
        i = 0
        l = len(part)
        while i != l:
            c = part[i]
            if c.isdigit():
                key.append(part_weight)
                j = i
                while i != l and part[i].isdigit(): i += 1
                key.append(part_weight+int(part[j:i] or "0"))
            elif c == "~":
                key.append(0)
                i += 1
            elif c.isalpha():
                key.append(part_weight+ord(c))
                i += 1
            else:
                key.append(part_weight+256+ord(c))
                i += 1
        if not key or key[-1] != part_weight:
            key.append(part_weight)
            key.append(part_weight)
    key.append(1)

    # Encode our key and return it
    #
    result = []
    for value in key:
        if not value:
            result.append("000")
        else:
            element = []
            while value:
                element.insert(0, MAP[value & 0x1F])
                value >>= 5
            element_len = len(element)
            if element_len < 3:
                element.insert(0, "0"*(3-element_len))
            elif element_len == 3:
                pass
            elif element_len < 35:
                element.insert(0, MAP[element_len-4])
                element.insert(0, "X")
            elif element_len < 1027:
                element.insert(0, MAP[(element_len-4) & 0x1F])
                element.insert(0, MAP[(element_len-4) & 0x3E0])
                element.insert(0, "Y")
            else:
                raise ValueError("Number too large")
            result.extend(element)
    return "".join(result)
$_$;

CREATE OR REPLACE FUNCTION ftiupdate() RETURNS trigger
    LANGUAGE plpython3u
    AS $_$
    new = TD["new"]
    args = TD["args"][:]

    # Short circuit if none of the relevant columns have been
    # modified and fti is not being set to NULL (setting the fti
    # column to NULL is thus how we can force a rebuild of the fti
    # column).
    if TD["event"] == "UPDATE" and new["fti"] != None:
        old = TD["old"]
        relevant_modification = False
        for column_name in args[::2]:
            if new[column_name] != old[column_name]:
                relevant_modification = True
                break
        if not relevant_modification:
            return "OK"

    # Generate an SQL statement that turns the requested
    # column values into a weighted tsvector
    sql = []
    for i in range(0, len(args), 2):
        sql.append(
                "setweight(to_tsvector('default', coalesce("
                "substring(ltrim($%d) from 1 for 2500),'')),"
                "CAST($%d AS \"char\"))" % (i + 1, i + 2))
        args[i] = new[args[i]]

    sql = "SELECT %s AS fti" % "||".join(sql)

    # Execute and store in the fti column
    plan = plpy.prepare(sql, ["text", "char"] * (len(args) // 2))
    new["fti"] = plpy.execute(plan, args, 1)[0]["fti"]

    # Tell PostgreSQL we have modified the data
    return "MODIFY"
$_$;

CREATE OR REPLACE FUNCTION ftq(text) RETURNS tsquery
    LANGUAGE plpython3u IMMUTABLE STRICT
    AS $_$
        p = plpy.prepare(
            "SELECT to_tsquery('default', _ftq($1)) AS x", ["text"])
        query = plpy.execute(p, args, 1)[0]["x"]
        return query or None
        $_$;

CREATE OR REPLACE FUNCTION milestone_sort_key(dateexpected timestamp without time zone, name text) RETURNS text
    LANGUAGE plpython3u IMMUTABLE
    AS $$
    # If this method is altered, then any functional indexes using it
    # need to be rebuilt.
    import re
    import datetime

    date_expected, name = args

    def substitute_filled_numbers(match):
        return match.group(0).zfill(5)

    name = re.sub('\d+', substitute_filled_numbers, name)
    if date_expected is None:
        # NULL dates are considered to be in the future.
        date_expected = datetime.datetime(datetime.MAXYEAR, 1, 1)
    return '%s %s' % (date_expected, name)
$$;

CREATE OR REPLACE FUNCTION mv_validpersonorteamcache_emailaddress() RETURNS trigger
    LANGUAGE plpython3u SECURITY DEFINER
    AS $_$
    # This trigger function keeps the ValidPersonOrTeamCache materialized
    # view in sync when updates are made to the EmailAddress table.
    # Note that if the corresponding person is a team, changes to this table
    # have no effect.
    PREF = 4 # Constant indicating preferred email address

    if "delete_plan" not in SD:
        param_types = ["int4"]

        SD["is_team"] = plpy.prepare("""
            SELECT teamowner IS NOT NULL AS is_team FROM Person WHERE id = $1
            """, param_types)

        SD["delete_plan"] = plpy.prepare("""
            DELETE FROM ValidPersonOrTeamCache WHERE id = $1
            """, param_types)

        SD["insert_plan"] = plpy.prepare("""
            INSERT INTO ValidPersonOrTeamCache (id) VALUES ($1)
            """, param_types)

        SD["maybe_insert_plan"] = plpy.prepare("""
            INSERT INTO ValidPersonOrTeamCache (id)
            SELECT Person.id
            FROM Person
                JOIN EmailAddress ON Person.id = EmailAddress.person
                LEFT OUTER JOIN ValidPersonOrTeamCache
                    ON Person.id = ValidPersonOrTeamCache.id
            WHERE Person.id = $1
                AND ValidPersonOrTeamCache.id IS NULL
                AND status = %(PREF)d
                AND merged IS NULL
                -- AND password IS NOT NULL
            """ % vars(), param_types)

    def is_team(person_id):
        """Return true if person_id corresponds to a team"""
        if person_id is None:
            return False
        return plpy.execute(SD["is_team"], [person_id], 1)[0]["is_team"]

    class NoneDict:
        def __getitem__(self, key):
            return None

    old = TD["old"] or NoneDict()
    new = TD["new"] or NoneDict()

    #plpy.info("old.id     == %s" % old["id"])
    #plpy.info("old.person == %s" % old["person"])
    #plpy.info("old.status == %s" % old["status"])
    #plpy.info("new.id     == %s" % new["id"])
    #plpy.info("new.person == %s" % new["person"])
    #plpy.info("new.status == %s" % new["status"])

    # Short circuit if neither person nor status has changed
    if old["person"] == new["person"] and old["status"] == new["status"]:
        return

    # Short circuit if we are not mucking around with preferred email
    # addresses
    if old["status"] != PREF and new["status"] != PREF:
        return

    # Note that we have a constraint ensuring that there is only one
    # status == PREF email address per person at any point in time.
    # This simplifies our logic, as we know that if old.status == PREF,
    # old.person does not have any other preferred email addresses.
    # Also if new.status == PREF, we know new.person previously did not
    # have a preferred email address.

    if old["person"] != new["person"]:
        if old["status"] == PREF and not is_team(old["person"]):
            # old.person is no longer valid, unless they are a team
            plpy.execute(SD["delete_plan"], [old["person"]])
        if new["status"] == PREF and not is_team(new["person"]):
            # new["person"] is now valid, or unchanged if they are a team
            plpy.execute(SD["insert_plan"], [new["person"]])

    elif old["status"] == PREF and not is_team(old["person"]):
        # No longer valid, or unchanged if they are a team
        plpy.execute(SD["delete_plan"], [old["person"]])

    elif new["status"] == PREF and not is_team(new["person"]):
        # May now be valid, or unchanged if they are a team.
        plpy.execute(SD["maybe_insert_plan"], [new["person"]])
$_$;

CREATE OR REPLACE FUNCTION mv_validpersonorteamcache_person() RETURNS trigger
    LANGUAGE plpython3u SECURITY DEFINER
    AS $_$
    # This trigger function could be simplified by simply issuing
    # one DELETE followed by one INSERT statement. However, we want to minimize
    # expensive writes so we use this more complex logic.
    PREF = 4 # Constant indicating preferred email address

    if "delete_plan" not in SD:
        param_types = ["int4"]

        SD["delete_plan"] = plpy.prepare("""
            DELETE FROM ValidPersonOrTeamCache WHERE id = $1
            """, param_types)

        SD["maybe_insert_plan"] = plpy.prepare("""
            INSERT INTO ValidPersonOrTeamCache (id)
            SELECT Person.id
            FROM Person
                LEFT OUTER JOIN EmailAddress
                    ON Person.id = EmailAddress.person AND status = %(PREF)d
                LEFT OUTER JOIN ValidPersonOrTeamCache
                    ON Person.id = ValidPersonOrTeamCache.id
            WHERE Person.id = $1
                AND ValidPersonOrTeamCache.id IS NULL
                AND merged IS NULL
                AND (teamowner IS NOT NULL OR EmailAddress.id IS NOT NULL)
            """ % vars(), param_types)

    new = TD["new"]
    old = TD["old"]

    # We should always have new, as this is not a DELETE trigger
    assert new is not None, 'New is None'

    person_id = new["id"]
    query_params = [person_id] # All the same

    # Short circuit if this is a new person (not team), as it cannot
    # be valid until a status == 4 EmailAddress entry has been created
    # (unless it is a team, in which case it is valid on creation)
    if old is None:
        if new["teamowner"] is not None:
            plpy.execute(SD["maybe_insert_plan"], query_params)
        return

    # Short circuit if there are no relevant changes
    if (new["teamowner"] == old["teamowner"]
        and new["merged"] == old["merged"]):
        return

    # This function is only dealing with updates to the Person table.
    # This means we do not have to worry about EmailAddress changes here

    if (new["merged"] is not None or new["teamowner"] is None):
        plpy.execute(SD["delete_plan"], query_params)
    else:
        plpy.execute(SD["maybe_insert_plan"], query_params)
$_$;

CREATE OR REPLACE FUNCTION name_blacklist_match(text, integer) RETURNS integer
    LANGUAGE plpython3u STABLE STRICT SECURITY DEFINER
    SET search_path TO 'public'
    AS $_$
    import re
    name = args[0]
    user_id = args[1]

    # Initialize shared storage, shared between invocations.
    if "regexp_select_plan" not in SD:

        # All the blacklist regexps except the ones we are an admin
        # for. These we do not check since they are not blacklisted to us.
        SD["regexp_select_plan"] = plpy.prepare("""
            SELECT id, regexp FROM NameBlacklist
            WHERE admin IS NULL OR admin NOT IN (
                SELECT team FROM TeamParticipation
                WHERE person = $1)
            ORDER BY id
            """, ["integer"])

        # Storage for compiled regexps
        SD["compiled"] = {}

        # admins is a celebrity and its id is immutable.
        admins_id = plpy.execute(
            "SELECT id FROM Person WHERE name='admins'")[0]["id"]

        SD["admin_select_plan"] = plpy.prepare("""
            SELECT TRUE FROM TeamParticipation
            WHERE
                TeamParticipation.team = %d
                AND TeamParticipation.person = $1
            LIMIT 1
            """ % admins_id, ["integer"])

        # All the blacklist regexps except those that have an admin because
        # members of ~admin can use any name that any other admin can use.
        SD["admin_regexp_select_plan"] = plpy.prepare("""
            SELECT id, regexp FROM NameBlacklist
            WHERE admin IS NULL
            ORDER BY id
            """, ["integer"])


    compiled = SD["compiled"]

    # Names are never blacklisted for Lauchpad admins.
    if user_id is not None and plpy.execute(
        SD["admin_select_plan"], [user_id]).nrows() > 0:
        blacklist_plan = "admin_regexp_select_plan"
    else:
        blacklist_plan = "regexp_select_plan"

    for row in plpy.execute(SD[blacklist_plan], [user_id]):
        regexp_id = row["id"]
        regexp_txt = row["regexp"]
        if (compiled.get(regexp_id) is None
            or compiled[regexp_id][0] != regexp_txt):
            regexp = re.compile(regexp_txt, re.IGNORECASE | re.VERBOSE)
            compiled[regexp_id] = (regexp_txt, regexp)
        else:
            regexp = compiled[regexp_id][1]
        if regexp.search(name) is not None:
            return regexp_id
    return None
$_$;

CREATE OR REPLACE FUNCTION person_sort_key(displayname text, name text) RETURNS text
    LANGUAGE plpython3u IMMUTABLE STRICT
    AS $$
    # NB: If this implementation is changed, the person_sort_idx needs to be
    # rebuilt along with any other indexes using it.
    import re

    try:
        strip_re = SD["strip_re"]
    except KeyError:
        strip_re = re.compile("(?:[^\w\s]|[\d_])")
        SD["strip_re"] = strip_re

    displayname, name = args

    # Strip noise out of displayname. We do not have to bother with
    # name, as we know it is just plain ascii.
    displayname = strip_re.sub('', displayname.lower())
    return "%s, %s" % (displayname.strip(), name)
$$;

CREATE OR REPLACE FUNCTION sane_version(text) RETURNS boolean
    LANGUAGE plpython3u IMMUTABLE STRICT
    AS $_$
    import re
    if re.search("""^(?ix)
        [0-9a-z]
        ( [0-9a-z] | [0-9a-z.-]*[0-9a-z] )*
        $""", args[0]):
        return 1
    return 0
$_$;

CREATE OR REPLACE FUNCTION sha1(text) RETURNS character
    LANGUAGE plpython3u IMMUTABLE STRICT
    AS $$
    import hashlib
    return hashlib.sha1(args[0].encode()).hexdigest()
$$;

CREATE OR REPLACE FUNCTION ulower(text) RETURNS text
    LANGUAGE plpython3u IMMUTABLE STRICT
    AS $$
    return args[0].lower()
$$;

CREATE OR REPLACE FUNCTION update_database_stats() RETURNS void
    LANGUAGE plpython3u SECURITY DEFINER
    SET search_path TO 'public'
    AS $_$
    import re
    import subprocess

    # Prune DatabaseTableStats and insert current data.
    # First, detect if the statistics have been reset.
    stats_reset = plpy.execute("""
        SELECT *
        FROM
            pg_catalog.pg_stat_user_tables AS NowStat,
            DatabaseTableStats AS LastStat
        WHERE
            LastStat.date_created = (
                SELECT max(date_created) FROM DatabaseTableStats)
            AND NowStat.schemaname = LastStat.schemaname
            AND NowStat.relname = LastStat.relname
            AND (
                NowStat.seq_scan < LastStat.seq_scan
                OR NowStat.idx_scan < LastStat.idx_scan
                OR NowStat.n_tup_ins < LastStat.n_tup_ins
                OR NowStat.n_tup_upd < LastStat.n_tup_upd
                OR NowStat.n_tup_del < LastStat.n_tup_del
                OR NowStat.n_tup_hot_upd < LastStat.n_tup_hot_upd)
        LIMIT 1
        """, 1).nrows() > 0
    if stats_reset:
        # The database stats have been reset. We cannot calculate
        # deltas because we do not know when this happened. So we trash
        # our records as they are now useless to us. We could be more
        # sophisticated about this, but this should only happen
        # when an admin explicitly resets the statistics or if the
        # database is rebuilt.
        plpy.notice("Stats wraparound. Purging DatabaseTableStats")
        plpy.execute("DELETE FROM DatabaseTableStats")
    else:
        plpy.execute("""
            DELETE FROM DatabaseTableStats
            WHERE date_created < (CURRENT_TIMESTAMP AT TIME ZONE 'UTC'
                - CAST('21 days' AS interval));
            """)
    # Insert current data.
    plpy.execute("""
        INSERT INTO DatabaseTableStats
            SELECT
                CURRENT_TIMESTAMP AT TIME ZONE 'UTC',
                schemaname, relname, seq_scan, seq_tup_read,
                coalesce(idx_scan, 0), coalesce(idx_tup_fetch, 0),
                n_tup_ins, n_tup_upd, n_tup_del,
                n_tup_hot_upd, n_live_tup, n_dead_tup, last_vacuum,
                last_autovacuum, last_analyze, last_autoanalyze
            FROM pg_catalog.pg_stat_user_tables;
        """)

    # Prune DatabaseCpuStats. Calculate CPU utilization information
    # and insert current data.
    plpy.execute("""
        DELETE FROM DatabaseCpuStats
        WHERE date_created < (CURRENT_TIMESTAMP AT TIME ZONE 'UTC'
            - CAST('21 days' AS interval));
        """)
    dbname = plpy.execute(
        "SELECT current_database() AS dbname", 1)[0]['dbname']
    ps = subprocess.Popen(
        ["ps", "-C", "postgres", "--no-headers", "-o", "cp,args"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT)
    stdout, stderr = ps.communicate()
    cpus = {}
    # We make the username match non-greedy so the trailing \d eats
    # trailing digits from the database username. This collapses
    # lpnet1, lpnet2 etc. into just lpnet.
    ps_re = re.compile(
        r"(?m)^\s*(\d+)\spostgres:\s(\w+?)\d*\s%s\s" % dbname)
    for ps_match in ps_re.finditer(stdout):
        cpu, username = ps_match.groups()
        cpus[username] = int(cpu) + cpus.setdefault(username, 0)
    cpu_ins = plpy.prepare(
        "INSERT INTO DatabaseCpuStats (username, cpu) VALUES ($1, $2)",
        ["text", "integer"])
    for cpu_tuple in cpus.items():
        plpy.execute(cpu_ins, cpu_tuple)
$_$;

CREATE OR REPLACE FUNCTION valid_absolute_url(text) RETURNS boolean
    LANGUAGE plpython3u IMMUTABLE STRICT
    AS $$
    from urllib.parse import urlparse, uses_netloc
    # Extend list of schemes that specify netloc.
    if 'bzr' not in uses_netloc:
        uses_netloc.insert(0, 'bzr')
        uses_netloc.insert(0, 'bzr+ssh')
        uses_netloc.insert(0, 'ssh') # Mercurial
    (scheme, netloc, path, params, query, fragment) = urlparse(args[0])
    return bool(scheme and netloc)
$$;

CREATE OR REPLACE FUNCTION valid_branch_name(text) RETURNS boolean
    LANGUAGE plpython3u IMMUTABLE STRICT
    AS $$
    import re
    name = args[0]
    pat = r"^(?i)[a-z0-9][a-z0-9+\.\-@_]*\Z"
    if re.match(pat, name):
        return 1
    return 0
$$;

CREATE OR REPLACE FUNCTION valid_cve(text) RETURNS boolean
    LANGUAGE plpython3u IMMUTABLE STRICT
    AS $_$
    import re
    name = args[0]
    pat = r"^(19|20)\d{2}-\d{4,}$"
    if re.match(pat, name):
        return 1
    return 0
$_$;

CREATE OR REPLACE FUNCTION valid_debian_version(text) RETURNS boolean
    LANGUAGE plpython3u IMMUTABLE STRICT
    AS $_$
    import re
    m = re.search("""^(?ix)
        ([0-9]+:)?
        ([0-9a-z][a-z0-9+:.~-]*?)
        (-[a-z0-9+.~]+)?
        $""", args[0])
    if m is None:
        return 0
    epoch, version, revision = m.groups()
    if not epoch:
        # Can''t contain : if no epoch
        if ":" in version:
            return 0
    if not revision:
        # Can''t contain - if no revision
        if "-" in version:
            return 0
    return 1
$_$;

CREATE OR REPLACE FUNCTION valid_fingerprint(text) RETURNS boolean
    LANGUAGE plpython3u IMMUTABLE STRICT
    AS $$
    import re
    if re.match(r"[\dA-F]{40}", args[0]) is not None:
        return 1
    else:
        return 0
$$;

CREATE OR REPLACE FUNCTION valid_git_repository_name(text) RETURNS boolean
    LANGUAGE plpython3u IMMUTABLE STRICT
    AS $$
    import re
    name = args[0]
    pat = r"^(?i)[a-z0-9][a-z0-9+\.\-@_]*\Z"
    if not name.endswith(".git") and re.match(pat, name):
        return 1
    return 0
$$;

CREATE OR REPLACE FUNCTION valid_keyid(text) RETURNS boolean
    LANGUAGE plpython3u IMMUTABLE STRICT
    AS $$
    import re
    if re.match(r"[\dA-F]{8}", args[0]) is not None:
        return 1
    else:
        return 0
$$;

CREATE OR REPLACE FUNCTION valid_regexp(text) RETURNS boolean
    LANGUAGE plpython3u IMMUTABLE STRICT
    AS $$
    import re
    try:
        re.compile(args[0])
    except Exception:
        return False
    else:
        return True
$$;

CREATE OR REPLACE FUNCTION version_sort_key(version text) RETURNS text
    LANGUAGE plpython3u IMMUTABLE STRICT
    AS $$
    # If this method is altered, then any functional indexes using it
    # need to be rebuilt.
    import re

    [version] = args

    def substitute_filled_numbers(match):
        # Prepend "~" so that version numbers will show up first
        # when sorted descending, i.e. [3, 2c, 2b, 1, c, b, a] instead
        # of [c, b, a, 3, 2c, 2b, 1]. "~" has the highest ASCII value
        # of visible ASCII characters.
        return '~' + match.group(0).zfill(5)

    return re.sub('\d+', substitute_filled_numbers, version)
$$;

DROP EXTENSION plpythonu;

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 46, 0);
