-- Copyright 2025 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE CharmRecipe ADD COLUMN use_fetch_service boolean DEFAULT false NOT NULL;
COMMENT ON COLUMN CharmRecipe.use_fetch_service IS 'Whether to use the fetch-service in place of the builder-proxy when building this charm.';

-- The default value of 1 will point to the 'strict' policy for the
-- 'fetch_service_policy' column
ALTER TABLE CharmRecipe ADD COLUMN fetch_service_policy integer DEFAULT 1 NOT NULL;
COMMENT ON COLUMN CharmRecipe.fetch_service_policy IS 'Enum describing which fetch service policy to use when building this charm.';

INSERT INTO LaunchpadDatabaseRevision VALUES (2211, 39, 0);
