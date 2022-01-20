-- Copyright 2022 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE Bug
    ADD COLUMN lock_status integer,
    ADD COLUMN lock_reason text;

-- ALTER COLUMN ... SET DEFAULT doesn't trigger a table rewrite,
-- while ADD COLUMN ... DEFAULT xx does. In pg <11 this operation is slow.
-- That's why we first create, and then we set the default value.
-- Data backfilling will be done in a garbo job instead of a fast downtime.

ALTER TABLE Bug
    ALTER COLUMN lock_status
    -- 0 = UNLOCKED
    SET DEFAULT 0;

COMMENT ON COLUMN Bug.lock_status IS 'The current lock status of this bug.';

COMMENT ON COLUMN Bug.lock_reason IS 'The reason for locking this bug.';

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 38, 0);
