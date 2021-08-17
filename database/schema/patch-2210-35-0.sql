-- Copyright 2021 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE SnapBuild
    ADD COLUMN store_upload_revision integer;

COMMENT ON COLUMN SnapBuild.store_upload_revision IS 'The revision number assigned to this build on the last store upload.';

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 35, 0);