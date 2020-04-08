-- Copyright 2018 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE ArchiveFile
    ADD COLUMN date_created timestamp without time zone,
    ADD COLUMN date_superseded timestamp without time zone;

COMMENT ON COLUMN ArchiveFile.date_created IS 'The date when this file was created.';
COMMENT ON COLUMN ArchiveFile.date_superseded IS 'The date when this file ceased to hold its path in the archive, due to being removed or superseded by a newer version.';

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 09, 0);
