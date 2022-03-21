-- Copyright 2022 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE RevisionStatusArtifact
    ADD COLUMN date_created timestamp without time zone;

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 45, 0);
