-- Copyright 2023 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE ArchiveFile ADD COLUMN date_removed timestamp without time zone;

COMMENT ON COLUMN ArchiveFile.date_removed IS 'The date when this file was entirely removed from the published archive.';

INSERT INTO LaunchpadDatabaseRevision VALUES (2211, 15, 1);
