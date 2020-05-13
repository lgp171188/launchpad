-- Copyright 2020 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

-- Change indexes to allow project + ociprojectname on GitRepository.


-- Create indexes similar to distribution ones, but for project.
CREATE UNIQUE INDEX gitrepository__project__ocipn__target_default__key
    ON GitRepository (project, ociprojectname)
    WHERE project IS NOT NULL
        AND ociprojectname IS NOT NULL
        AND target_default;

CREATE UNIQUE INDEX gitrepository__owner__project__ocipn__name__key
    ON GitRepository (owner, project, ociprojectname, name)
    WHERE project IS NOT NULL
        AND ociprojectname IS NOT NULL;

CREATE UNIQUE INDEX gitrepository__owner__project__ocipn__owner_default__key
    ON GitRepository (owner, project, ociprojectname)
    WHERE project IS NOT NULL
        AND ociprojectname IS NOT NULL
        AND owner_default;

CREATE INDEX gitrepository__project__ocipn__date_last_modified__idx
    ON GitRepository (project, ociprojectname, date_last_modified)
    WHERE project IS NOT NULL
        AND ociprojectname IS NOT NULL;

CREATE INDEX gitrepository__project__ocipn__id__idx
    ON GitRepository (project, ociprojectname, id)
    WHERE project IS NOT NULL
        AND ociprojectname IS NOT NULL;

CREATE INDEX gitrepository__owner__project__ocipn__date_last_modified__
    ON GitRepository (owner, project, ociprojectname, date_last_modified)
    WHERE project IS NOT NULL
        AND ociprojectname IS NOT NULL;

CREATE INDEX gitrepository__owner__project__ocipn__id__idx
    ON GitRepository (owner, project, ociprojectname, id)
    WHERE project IS NOT NULL
        AND ociprojectname IS NOT NULL;

-- Update unique indexes to allow project + ociproject

-- Unique owner / project / name.
CREATE UNIQUE INDEX gitrepository__owner__project__name__key
    ON GitRepository (owner, project, name)
    WHERE project IS NOT NULL
        AND ociprojectname IS NULL;

CREATE UNIQUE INDEX gitrepository__owner__project__name__oci__key
    ON GitRepository (owner, project, name)
    WHERE project IS NOT NULL
        AND ociprojectname IS NOT NULL;

DROP INDEX old__gitrepository__owner__project__name__key;


-- Unique owner_default for owner_project.
CREATE UNIQUE INDEX gitrepository__owner__project__owner_default__key
    ON GitRepository (owner, project)
    WHERE project IS NOT NULL
        AND ociprojectname IS NULL
        AND owner_default;

CREATE UNIQUE INDEX gitrepository__owner__project__owner_default__oci__key
    ON GitRepository (owner, project)
    WHERE project IS NOT NULL
        AND ociprojectname IS NOT NULL
        AND owner_default;

DROP INDEX old__gitrepository__owner__project__owner_default__key;


-- Unique target_defaul for project.
CREATE UNIQUE INDEX gitrepository__project__target_default__key
    ON GitRepository (project)
    WHERE project IS NOT NULL
        AND ociprojectname IS NULL
        AND target_default;

CREATE UNIQUE INDEX gitrepository__project__target_default__oci__key
    ON GitRepository (project)
    WHERE project IS NOT NULL
        AND ociprojectname IS NOT NULL
        AND target_default;

DROP INDEX old__gitrepository__project__target_default__key;

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 8, 9);
