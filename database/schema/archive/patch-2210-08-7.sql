-- Copyright 2020 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

CREATE TABLE OCIRecipeBuildJob (
    job integer PRIMARY KEY REFERENCES Job ON DELETE CASCADE NOT NULL,
    build integer REFERENCES ocirecipebuild NOT NULL,
    job_type integer NOT NULL,
    json_data jsonb NOT NULL
);

COMMENT ON TABLE OCIRecipeBuildJob IS 'Contains references to jobs that are executed for a build of an OCI recipe.';
COMMENT ON COLUMN OCIRecipeBuildJob.job IS 'A reference to a Job row that has all the common job details.';
COMMENT ON COLUMN OCIRecipeBuildJob.build IS 'The OCI recipe build that this job is for.';
COMMENT ON COLUMN OCIRecipeBuildJob.job_type IS 'The type of a job, such as a registry push.';
COMMENT ON COLUMN OCIRecipeBuildJob.json_data IS 'Data that is specific to a particular job type.';

CREATE INDEX ocirecipebuildjob__build__job_type__job__idx
    ON OCIRecipeBuildJob (build, job_type, job);
CREATE INDEX ocirecipebuildjob__job__job_type__idx
    ON OCIRecipeBuildJob (job, job_type);

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 08, 7);
