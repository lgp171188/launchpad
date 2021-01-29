-- Copyright 2016 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

-- OCIRecipe privacy model is based only on ownership, similarly to Archives.
ALTER TABLE OCIRecipe ADD COLUMN private boolean DEFAULT false NOT NULL;

COMMENT ON COLUMN OCIRecipe.private
    IS 'Whether or not this OCI recipe is private.';


INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 26, 0);
