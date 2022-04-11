-- Copyright 2022 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE CIBuild ADD COLUMN jobs jsonb;

COMMENT ON COLUMN CIBuild.jobs IS 'The status of the individual jobs in this CI build.';

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 40, 1);
