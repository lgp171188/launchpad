-- Copyright 2019 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE Webhook ADD COLUMN oci_recipe integer REFERENCES OCIRecipe;

ALTER TABLE Webhook DROP CONSTRAINT one_target;
ALTER TABLE Webhook ADD CONSTRAINT one_target CHECK (null_count(ARRAY[git_repository, branch, snap, livefs, oci_recipe]) = 4);

CREATE INDEX webhook__oci_recipe__id__idx
    ON webhook(oci_recipe, id) WHERE oci_recipe IS NOT NULL;

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 10, 1);
