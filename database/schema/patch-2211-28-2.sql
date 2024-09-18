-- Copyright 2024 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE RockRecipe ADD COLUMN use_fetch_service boolean DEFAULT false NOT NULL;

COMMENT ON COLUMN RockRecipe.use_fetch_service IS 'Whether to use the fetch-service in place of the builder-proxy when building this rock.';

INSERT INTO LaunchpadDatabaseRevision VALUES (2211, 28, 2);
