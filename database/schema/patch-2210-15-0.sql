-- Copyright 2020 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

CREATE TABLE OCIRecipeJob (
    id serial PRIMARY KEY,
    job INTEGER NOT NULL REFERENCES Job,
    oci_recipe INTEGER NOT NULL REFERENCES OCIRecipe,
    job_type INTEGER NOT NULL,
    json_data TEXT NOT NULL
);

CREATE INDEX ocirecipejob__oci_recipe__job_type__job__idx
  ON OCIRecipeJob(oci_recipe, job_type, job);

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 15, 0);
