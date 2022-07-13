-- Copyright 2022 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE NameBlacklist RENAME TO NameBlocklist;
COMMENT ON TABLE NameBlocklist IS 'A list of regular expressions used to block names.';
COMMENT ON COLUMN NameBlocklist.admin IS 'The person who can override the blocked name.';

ALTER SEQUENCE nameblacklist_id_seq RENAME TO nameblocklist_id_seq;
ALTER INDEX nameblacklist_pkey RENAME TO nameblocklist_pkey;
ALTER INDEX nameblacklist__regexp__key RENAME TO nameblocklist__regexp__key;

CREATE OR REPLACE FUNCTION name_blocklist_match(text, integer) RETURNS integer
    LANGUAGE plpython3u STABLE STRICT SECURITY DEFINER
    SET search_path TO 'public'
    AS $_$
    import re
    name = args[0]
    user_id = args[1]

    # Initialize shared storage, shared between invocations.
    if "regexp_select_plan" not in SD:

        # All the blocklist regexps except the ones we are an admin
        # for. These we do not check since they are not blocklisted to us.
        SD["regexp_select_plan"] = plpy.prepare("""
            SELECT id, regexp FROM NameBlocklist
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

        # All the blocklist regexps except those that have an admin because
        # members of ~admin can use any name that any other admin can use.
        SD["admin_regexp_select_plan"] = plpy.prepare("""
            SELECT id, regexp FROM NameBlocklist
            WHERE admin IS NULL
            ORDER BY id
            """, ["integer"])


    compiled = SD["compiled"]

    # Names are never blocklisted for Lauchpad admins.
    if user_id is not None and plpy.execute(
        SD["admin_select_plan"], [user_id]).nrows() > 0:
        blocklist_plan = "admin_regexp_select_plan"
    else:
        blocklist_plan = "regexp_select_plan"

    for row in plpy.execute(SD[blocklist_plan], [user_id]):
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

COMMENT ON FUNCTION public.name_blocklist_match(text, integer) IS 'Return the id of the row in the NameBlocklist table that matches the given name, or NULL if no regexps in the NameBlocklist table match.';

CREATE OR REPLACE FUNCTION is_blocklisted_name(text, integer) RETURNS boolean
    LANGUAGE sql STABLE STRICT SECURITY DEFINER
    SET search_path TO 'public'
    AS $_$
    SELECT COALESCE(name_blocklist_match($1, $2)::boolean, FALSE);
$_$;

COMMENT ON FUNCTION public.is_blocklisted_name(text, integer) IS 'Return TRUE if any regular expressions stored in the NameBlocklist table match the given name, otherwise return FALSE.';

-- Temporary aliases for old names, needed until they're no longer
-- referenced in code.

CREATE VIEW NameBlacklist AS SELECT * FROM NameBlocklist;

CREATE OR REPLACE FUNCTION name_blacklist_match(text, integer) RETURNS integer
    LANGUAGE sql STABLE STRICT SECURITY DEFINER
    SET search_path TO 'public'
    AS $_$
    SELECT name_blocklist_match($1, $2);
$_$;

CREATE OR REPLACE FUNCTION is_blacklisted_name(text, integer) RETURNS boolean
    LANGUAGE sql STABLE STRICT SECURITY DEFINER
    SET search_path TO 'public'
    AS $_$
    SELECT is_blocklisted_name($1, $2);
$_$;

INSERT INTO LaunchpadDatabaseRevision VALUES (2211, 01, 0);
