-- Copyright 2020 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

CREATE INDEX gitrepository__status__idx ON GitRepository (status);

ALTER TABLE GitRepository
    ALTER COLUMN status
        SET DEFAULT 1,
    ALTER COLUMN status SET NOT NULL;

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 17, 1);
