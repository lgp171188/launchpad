-- Copyright 2021 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE OCIRecipe
    ADD COLUMN image_name TEXT DEFAULT NULL;

COMMENT ON COLUMN OCIRecipe.image_name IS 'Image name to use on upload to registry.';

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 24, 1);
