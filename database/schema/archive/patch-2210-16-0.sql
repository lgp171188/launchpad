-- Copyright 2020 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE OCIFile
ADD COLUMN date_last_used timestamp without time zone
    DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC') NOT NULL;

COMMENT ON COLUMN OCIFile.date_last_used IS 'The datetime this file was last used in a build.';

CREATE INDEX ocifile__date_last_used__idx
    ON OCIFile (date_last_used);

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 16, 0);
