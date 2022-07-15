-- Copyright 2020 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

ALTER TABLE OCIRecipe ALTER COLUMN git_path DROP NOT NULL;

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 08, 4);
