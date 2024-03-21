-- Copyright 2024 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE Archive ADD COLUMN metadata_overrides jsonb;

COMMENT ON COLUMN Archive.metadata_overrides IS 'A JSON object containing metadata overrides for this archive.';

INSERT INTO LaunchpadDatabaseRevision VALUES (2211, 27, 0);
