-- Copyright 2023 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE CharmRecipe ADD COLUMN relative_build_score integer;
ALTER TABLE GitRepository ADD COLUMN relative_build_score integer;
ALTER TABLE Snap ADD COLUMN relative_build_score integer;

COMMENT ON COLUMN CharmRecipe.relative_build_score IS 'A delta to the build score that is applied to all builds of this charm recipe.';
COMMENT ON COLUMN GitRepository.relative_build_score IS 'A delta to the build score that is applied to all builds of this Git repository.';
COMMENT ON COLUMN Snap.relative_build_score IS 'A delta to the build score that is applied to all builds of this snap recipe.';

INSERT INTO LaunchpadDatabaseRevision VALUES (2211, 16, 0);
