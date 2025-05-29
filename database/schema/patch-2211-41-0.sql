-- Copyright 2025 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE CharmRecipe
    ADD COLUMN git_repository_url text;

ALTER TABLE CharmRecipe
    DROP CONSTRAINT consistent_git_ref,
    ADD CONSTRAINT consistent_git_ref CHECK (((git_repository IS NULL) AND (git_repository_url IS NULL)) = (git_path IS NULL)) NOT VALID;

ALTER TABLE CharmRecipe
    ADD CONSTRAINT consistent_vcs CHECK (null_count(ARRAY[git_repository, octet_length(git_repository_url)]) >= 1) NOT VALID;

ALTER TABLE CharmRecipe
    ADD CONSTRAINT valid_git_repository_url CHECK (valid_absolute_url(git_repository_url)) NOT VALID;

COMMENT ON COLUMN CharmRecipe.git_repository_url IS 'A URL to a Git repository with a branch containing a charm recipe.';

INSERT INTO LaunchpadDatabaseRevision VALUES (2211, 41, 0);
