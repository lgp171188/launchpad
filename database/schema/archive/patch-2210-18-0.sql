-- Copyright 2020 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE OCIRecipe ADD COLUMN allow_internet boolean DEFAULT true NOT NULL;

COMMENT ON COLUMN OCIRecipe.allow_internet IS 'If True, builds of this OCIRecipe may allow access to external network resources.';

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 18, 0);
