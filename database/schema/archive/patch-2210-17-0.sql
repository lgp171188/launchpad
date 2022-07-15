-- Copyright 2020 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE GitRepository ADD COLUMN status INTEGER;

-- ALTER COLUMN ... SET DEFAULT doesn't trigger a table rewrite,
-- while ADD COLUMN ... DEFAULT xx does. In pg <11 this operation is slow.
-- That's why we first create, and then we set the default value.
-- Data backfilling will be done in a hot patch instead of a fast downtime.
ALTER TABLE GitRepository ALTER COLUMN status SET DEFAULT 2;

COMMENT ON COLUMN GitRepository.status
    IS 'The current status of this git repository.';

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 17, 0);
