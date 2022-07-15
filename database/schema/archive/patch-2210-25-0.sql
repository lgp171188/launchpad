-- Copyright 2021 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE GitRepository
    ADD COLUMN loose_object_count integer,
    ADD COLUMN pack_count integer,
    ADD COLUMN date_last_repacked timestamp without time zone,
    ADD COLUMN date_last_scanned timestamp without time zone;

COMMENT ON COLUMN GitRepository.date_last_scanned IS 'The datetime that packs and loose_objects were last updated for this repository.';
COMMENT ON COLUMN GitRepository.date_last_repacked IS 'The datetime that the last repack request was executed successfully on Turnip.';

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 25, 0);
