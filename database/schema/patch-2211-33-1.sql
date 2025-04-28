-- Copyright 2025 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE SourcePackageRecipeBuild DROP COLUMN craft_platform;
ALTER TABLE CraftRecipeBuild ADD COLUMN craft_platform text;

COMMENT ON COLUMN CraftRecipeBuild.craft_platform IS 'The platform name from the Source recipe for which the Source artifact is built.';

INSERT INTO LaunchpadDatabaseRevision VALUES (2211, 33, 1);
