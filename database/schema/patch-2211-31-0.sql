-- Copyright 2024 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE Snap ADD COLUMN fetch_service_policy integer DEFAULT NULL;
COMMENT ON COLUMN Snap.fetch_service_policy IS 'Enum describing which fetch service policy to use when building this snap.';

ALTER TABLE RockRecipe ADD COLUMN fetch_service_policy integer DEFAULT NULL;
COMMENT ON COLUMN RockRecipe.fetch_service_policy IS 'Enum describing which fetch service policy to use when building this snap.';

ALTER TABLE CraftRecipe ADD COLUMN fetch_service_policy integer DEFAULT NULL;
COMMENT ON COLUMN CraftRecipe.fetch_service_policy IS 'Enum describing which fetch service policy to use when building this snap.';

INSERT INTO LaunchpadDatabaseRevision VALUES (2211, 31, 0);
