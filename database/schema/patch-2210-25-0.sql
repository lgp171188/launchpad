-- Copyright 2021 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE GitRepository
    ADD COLUMN loose_objects integer DEFAULT 0 NOT NULL,
    ADD COLUMN packs integer DEFAULT 0 NOT NULL,
    ADD COLUMN date_last_repacked timestamp without time zone
        DEFAULT NULL,
    ADD COLUMN date_last_scanned timestamp without time zone
        DEFAULT NULL;

    COMMENT ON COLUMN GitRepository.date_last_scanned IS 'The datetime that packs and loose_objects were last updated for this repository.';
    COMMENT ON COLUMN GitRepository.date_last_repacked IS 'The datetime that the last repack request was executed successfully on Turnip.';

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 25, 0);
