-- Copyright 2022 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE RevisionStatusArtifact
    ADD COLUMN date_created timestamp without time zone DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC') NOT NULL;

UPDATE RevisionStatusArtifact
SET date_created = LibraryFileAlias.date_created
FROM LibraryFileAlias
WHERE RevisionStatusArtifact.library_file = LibraryFileAlias.id;

CREATE INDEX revisionstatusartifact__report__type__created__idx
    ON RevisionStatusArtifact (report, type, date_created DESC);
DROP INDEX revisionstatusartifact__report__type__idx;

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 37, 1);
