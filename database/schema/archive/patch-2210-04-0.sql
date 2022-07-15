-- Copyright 2019 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE LiveFS ADD COLUMN keep_binary_files_interval interval DEFAULT interval '1 day';

COMMENT ON COLUMN LiveFS.keep_binary_files_interval IS 'Keep binary files attached to builds of this live filesystem for at least this long.';

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 04, 0);
