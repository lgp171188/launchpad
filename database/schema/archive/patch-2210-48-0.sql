-- Copyright 2022 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE SnapBuild
    ADD COLUMN target_architectures text[];

COMMENT ON COLUMN SnapBuild.target_architectures IS 'A list of target architectures for a snap build.';

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 48, 0);
