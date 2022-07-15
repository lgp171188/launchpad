-- Copyright 2020 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

CREATE TABLE OCIRecipeJob (
    job integer PRIMARY KEY REFERENCES Job ON DELETE CASCADE NOT NULL,
    recipe INTEGER NOT NULL REFERENCES OCIRecipe,
    job_type INTEGER NOT NULL,
    json_data jsonb NOT NULL
);

CREATE INDEX ocirecipejob__recipe__job_type__job__idx
  ON OCIRecipeJob(recipe, job_type, job);

COMMENT ON TABLE OCIRecipeJob IS 'Contains references to jobs that are executed for an OCI Recipe.';
COMMENT ON COLUMN OCIRecipeJob.job IS 'A reference to a Job row that has all the common job details.';
COMMENT ON COLUMN OCIRecipeJob.recipe IS 'The OCI recipe that this job is for.';
COMMENT ON COLUMN OCIRecipeJob.job_type IS 'The type of a job, such as a build request.';
COMMENT ON COLUMN OCIRecipeJob.json_data IS 'Data that is specific to a particular job type.';

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 15, 0);
