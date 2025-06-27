-- Copyright 2025 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

CREATE OR REPLACE FUNCTION public.sane_version(text) RETURNS boolean
    LANGUAGE plpython3u IMMUTABLE STRICT
    AS $_$
    import re
    if re.search("""^
        [0-9a-z]
        ( [0-9a-z] | [0-9a-z.-]*[0-9a-z] )*
        $""", args[0], re.IGNORECASE | re.VERBOSE):
        return 1
    return 0
$_$;

CREATE OR REPLACE FUNCTION public.valid_branch_name(text) RETURNS boolean
    LANGUAGE plpython3u IMMUTABLE STRICT
    AS $$
    import re
    name = args[0]
    pat = r"^[a-z0-9][a-z0-9+\.\-@_]*\Z"
    if re.match(pat, name, re.IGNORECASE):
        return 1
    return 0
$$;

CREATE OR REPLACE FUNCTION public.valid_debian_version(text) RETURNS boolean
    LANGUAGE plpython3u IMMUTABLE STRICT
    AS $_$
    import re
    m = re.search("""^
        ([0-9]+:)?
        ([0-9a-z][a-z0-9+:.~-]*?)
        (-[a-z0-9+.~]+)?
        $""", args[0], re.IGNORECASE | re.VERBOSE)
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

CREATE OR REPLACE FUNCTION public.valid_git_repository_name(text) RETURNS boolean
    LANGUAGE plpython3u IMMUTABLE STRICT
    AS $$
    import re
    name = args[0]
    pat = r"^[a-z0-9][a-z0-9+\.\-@_]*\Z"
    if not name.endswith(".git") and re.match(pat, name, re.IGNORECASE):
        return 1
    return 0
$$;


INSERT INTO LaunchpadDatabaseRevision VALUES (2211, 42, 0);
