-- Copyright 2020 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

-- Status "2" is GitRepositoryStatus.AVAILABLE
UPDATE GitRepository SET status = 2 WHERE status IS NULL;

ALTER TABLE GitRepository
    ALTER COLUMN status SET NOT NULL;

CREATE INDEX gitrepository__date_created__status__idx
    ON GitRepository (date_created)
    -- 1 == CREATING
    WHERE status = 1;

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 17, 1);
