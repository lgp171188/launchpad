-- Copyright 2025 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE CharmRecipeBuild ADD COLUMN craft_platform text;
ALTER TABLE RockRecipeBuild ADD COLUMN craft_platform text;
ALTER TABLE SnapBuild ADD COLUMN craft_platform text;
ALTER TABLE SourcePackageRecipeBuild ADD COLUMN craft_platform text;

COMMENT ON COLUMN CharmRecipeBuild.craft_platform IS 'The platform name from the Charm recipe for which the Charm artifact is built.';
COMMENT ON COLUMN RockRecipeBuild.craft_platform IS 'The platform name from the Rock recipe for which the Rock artifact is built.'; 
COMMENT ON COLUMN SnapBuild.craft_platform IS 'The platform name from the Snap recipe for which the Snap artifact is built.';
COMMENT ON COLUMN SourcePackageRecipeBuild.craft_platform IS 'The platform name from the Source recipe for which the Source artifact is built.';

CREATE INDEX charmrecipebuild__craft_platform__idx
    ON CharmRecipeBuild (craft_platform);
CREATE INDEX rockrecipebuild__craft_platform__idx
    ON RockRecipeBuild (craft_platform);
CREATE INDEX snapbuild__craft_platform__idx
    ON SnapBuild (craft_platform);
CREATE INDEX sourcepackagerecipebuild__craft_platform__idx
    ON SourcePackageRecipeBuild (craft_platform);

INSERT INTO LaunchpadDatabaseRevision VALUES (2211, 33, 0);
