-- Copyright 2020 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE OCIRecipeBuild ADD COLUMN build_request integer REFERENCES job;

COMMENT ON COLUMN OCIRecipeBuild.build_request IS 'The build request that caused this build to be created.';

CREATE INDEX ocirecipebuild__build_request__idx ON OCIRecipeBuild (build_request);

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 15, 1);
