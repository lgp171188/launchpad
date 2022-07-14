-- Copyright 2019-2020 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

-- Create/replace indexes.  Previously we had a variety of indexes including
-- (distribution, sourcepackagename) with non-NULL distribution but omitting
-- the condition that sourcepackagename is also non-NULL.  Replace each of
-- these with a pair of indexes, one for non-NULL sourcepackagename and one
-- for non-NULL ociprojectname.

CREATE UNIQUE INDEX gitrepository__owner__distribution__spn__name__key
    ON GitRepository (owner, distribution, sourcepackagename, name)
    WHERE distribution IS NOT NULL AND sourcepackagename IS NOT NULL;
CREATE UNIQUE INDEX gitrepository__owner__distribution__ocipn__name__key
    ON GitRepository (owner, distribution, ociprojectname, name)
    WHERE distribution IS NOT NULL AND ociprojectname IS NOT NULL;
DROP INDEX old__gitrepository__owner__distribution__sourcepackagename__name__key;

CREATE UNIQUE INDEX gitrepository__distribution__spn__target_default__key
    ON GitRepository (distribution, sourcepackagename)
    WHERE
        distribution IS NOT NULL AND sourcepackagename IS NOT NULL
        AND target_default;
CREATE UNIQUE INDEX gitrepository__distribution__ocipn__target_default__key
    ON GitRepository (distribution, ociprojectname)
    WHERE
        distribution IS NOT NULL AND ociprojectname IS NOT NULL
        AND target_default;
DROP INDEX old__gitrepository__distribution__spn__target_default__key;

CREATE UNIQUE INDEX gitrepository__owner__distribution__spn__owner_default__key
    ON GitRepository (owner, distribution, sourcepackagename)
    WHERE
        distribution IS NOT NULL AND sourcepackagename IS NOT NULL
        AND owner_default;
CREATE UNIQUE INDEX gitrepository__owner__distribution__ocipn__owner_default__key
    ON GitRepository (owner, distribution, ociprojectname)
    WHERE
        distribution IS NOT NULL AND ociprojectname IS NOT NULL
        AND owner_default;
DROP INDEX old__gitrepository__owner__distribution__spn__owner_default__key;

CREATE INDEX gitrepository__distribution__spn__date_last_modified__idx
    ON GitRepository (distribution, sourcepackagename, date_last_modified)
    WHERE distribution IS NOT NULL AND sourcepackagename IS NOT NULL;
CREATE INDEX gitrepository__distribution__ocipn__date_last_modified__idx
    ON GitRepository (distribution, ociprojectname, date_last_modified)
    WHERE distribution IS NOT NULL AND ociprojectname IS NOT NULL;
DROP INDEX old__gitrepository__distribution__spn__date_last_modified__idx;

CREATE INDEX gitrepository__distribution__spn__id__idx
    ON GitRepository (distribution, sourcepackagename, id)
    WHERE distribution IS NOT NULL AND sourcepackagename IS NOT NULL;
CREATE INDEX gitrepository__distribution__ocipn__id__idx
    ON GitRepository (distribution, ociprojectname, id)
    WHERE distribution IS NOT NULL AND ociprojectname IS NOT NULL;
DROP INDEX old__gitrepository__distribution__spn__id__idx;

CREATE INDEX gitrepository__owner__distribution__spn__date_last_modified__idx
    ON GitRepository (
        owner, distribution, sourcepackagename, date_last_modified)
    WHERE distribution IS NOT NULL AND sourcepackagename IS NOT NULL;
CREATE INDEX gitrepository__owner__distribution__ocipn__date_last_modified__idx
    ON GitRepository (owner, distribution, ociprojectname, date_last_modified)
    WHERE distribution IS NOT NULL AND ociprojectname IS NOT NULL;
DROP INDEX old__gitrepository__owner__distribution__spn__date_last_modified__idx;

CREATE INDEX gitrepository__owner__distribution__spn__id__idx
    ON GitRepository (owner, distribution, sourcepackagename, id)
    WHERE distribution IS NOT NULL AND sourcepackagename IS NOT NULL;
CREATE INDEX gitrepository__owner__distribution__ocipn__id__idx
    ON GitRepository (owner, distribution, ociprojectname, id)
    WHERE distribution IS NOT NULL AND ociprojectname IS NOT NULL;
DROP INDEX old__gitrepository__owner__distribution__spn__id__idx;

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 08, 2);
