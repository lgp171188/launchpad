-- Copyright 2020 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE OCIRecipe ADD COLUMN build_path text DEFAULT '.' NOT NULL;

COMMENT ON COLUMN OCIRecipe.build_path IS 'Directory to use for build context and OCIRecipe.build_file location.';

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 20, 0);
