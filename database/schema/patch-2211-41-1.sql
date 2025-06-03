-- Copyright 2025 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE CharmRecipe VALIDATE CONSTRAINT consistent_git_ref;

ALTER TABLE CharmRecipe VALIDATE CONSTRAINT consistent_vcs;

ALTER TABLE CharmRecipe VALIDATE CONSTRAINT valid_git_repository_url; 

CREATE INDEX charmrecipe__git_repository_url__idx ON CharmRecipe(git_repository_url);

INSERT INTO LaunchpadDatabaseRevision VALUES (2211, 41, 1);
