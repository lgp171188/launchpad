-- Copyright 2022 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE Archive
    ADD COLUMN official boolean DEFAULT FALSE NOT NULL;

COMMENT ON COLUMN Archive.official
    IS 'True if this archive is an official source of packages for its distribution; false if it is an unofficial add-on.';

UPDATE archive SET official = true WHERE purpose IN (1, 4);

INSERT INTO LaunchpadDatabaseRevision VALUES (2211, 10, 0);
