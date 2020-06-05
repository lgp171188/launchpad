-- Copyright 2020 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE GitRepository ADD COLUMN status INTEGER;

COMMENT ON COLUMN GitRepository.status
    IS 'The current situation of this git repository.';

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 17, 0);
