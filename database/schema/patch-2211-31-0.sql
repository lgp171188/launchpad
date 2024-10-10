-- Copyright 2024 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

-- Note that adding `DEFAULT 1` to this new column won't backfill the whole
-- table (which could be time-expensive for the Snaps table in particular
-- since it will have a lot of entries). Instead, the default value will be
-- returned the next time the row is accessed. See
-- https://www.postgresql.org/docs/current/ddl-alter.html#DDL-ALTER-ADDING-A-COLUMN
-- for more details.

-- The default value of 1 will point to 'strict' policy for the fetch service
ALTER TABLE Snap ADD COLUMN fetch_service_policy integer DEFAULT 1 NOT NULL;
COMMENT ON COLUMN Snap.fetch_service_policy IS 'Enum describing which fetch service policy to use when building this snap.';

ALTER TABLE RockRecipe ADD COLUMN fetch_service_policy integer DEFAULT 1 NOT NULL;
COMMENT ON COLUMN RockRecipe.fetch_service_policy IS 'Enum describing which fetch service policy to use when building this snap.';

ALTER TABLE CraftRecipe ADD COLUMN fetch_service_policy integer DEFAULT 1 NOT NULL;
COMMENT ON COLUMN CraftRecipe.fetch_service_policy IS 'Enum describing which fetch service policy to use when building this snap.';

INSERT INTO LaunchpadDatabaseRevision VALUES (2211, 31, 0);
