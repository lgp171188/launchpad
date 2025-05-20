-- Copyright 2025 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages = ERROR;

CREATE INDEX charmrecipebuild__craft_platform__idx
    ON CharmRecipeBuild (craft_platform);
CREATE INDEX rockrecipebuild__craft_platform__idx
    ON RockRecipeBuild (craft_platform);
CREATE INDEX snapbuild__craft_platform__idx
    ON SnapBuild (craft_platform);
CREATE INDEX craftrecipebuild__craft_platform__idx
    ON CraftRecipeBuild (craft_platform);

INSERT INTO LaunchpadDatabaseRevision VALUES (2211, 33, 2);
