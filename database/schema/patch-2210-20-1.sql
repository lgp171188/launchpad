-- Copyright 2020 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE OCIRecipe ADD COLUMN build_args jsonb;

COMMENT ON COLUMN OCIRecipe.build_args IS 'ARGs to be used when building the OCI Recipe.';

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 20, 1);
