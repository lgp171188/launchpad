-- Copyright 2020 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

ALTER TABLE OCIRecipe ADD CONSTRAINT consistent_git_ref CHECK ((git_repository IS NULL) = (git_path IS NULL));

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 08, 5);
