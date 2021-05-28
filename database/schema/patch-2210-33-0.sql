-- Copyright 2021 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

CREATE TABLE CharmRecipe (
    id serial PRIMARY KEY,
    date_created timestamp without time zone DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC') NOT NULL,
    date_last_modified timestamp without time zone DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC') NOT NULL,
    registrant integer NOT NULL REFERENCES person,
    owner integer NOT NULL REFERENCES person,
    project integer NOT NULL REFERENCES product,
    name text NOT NULL,
    description text,
    git_repository integer REFERENCES gitrepository,
    git_path text,
    build_path text,
    require_virtualized boolean DEFAULT true NOT NULL,
    information_type integer NOT NULL,
    access_policy integer,
    access_grants integer[],
    auto_build boolean DEFAULT false NOT NULL,
    auto_build_channels text,
    is_stale boolean DEFAULT true NOT NULL,
    store_upload boolean DEFAULT false NOT NULL,
    store_name text,
    store_secrets text,
    store_channels jsonb,
    CONSTRAINT valid_name CHECK (valid_name(name)),
    CONSTRAINT consistent_git_ref CHECK (
        (git_repository IS NULL) = (git_path IS NULL)),
    CONSTRAINT consistent_store_upload CHECK (
        NOT store_upload OR store_name IS NOT NULL)
);

COMMENT ON TABLE CharmRecipe IS 'A charm recipe.';
COMMENT ON COLUMN CharmRecipe.registrant IS 'The person who registered this charm recipe.';
COMMENT ON COLUMN CharmRecipe.owner IS 'The owner of this charm recipe.';
COMMENT ON COLUMN CharmRecipe.project IS 'The project that this charm recipe belongs to.';
COMMENT ON COLUMN CharmRecipe.name IS 'The name of the charm recipe, unique per owner and project.';
COMMENT ON COLUMN CharmRecipe.description IS 'A description of the charm recipe.';
COMMENT ON COLUMN CharmRecipe.git_repository IS 'A Git repository with a branch containing a charmcraft.yaml recipe.';
COMMENT ON COLUMN CharmRecipe.git_path IS 'The path of the Git branch containing a charmcraft.yaml recipe.';
COMMENT ON COLUMN CharmRecipe.build_path IS 'Subdirectory within the branch containing charmcraft.yaml.';
COMMENT ON COLUMN CharmRecipe.require_virtualized IS 'If True, this snap package must be built only on a virtual machine.';
COMMENT ON COLUMN CharmRecipe.information_type IS 'Enum describing what type of information is stored, such as type of private or security related data, and used to determine how to apply an access policy.';
COMMENT ON COLUMN CharmRecipe.auto_build IS 'Whether this charm recipe is built automatically when its branch changes.';
COMMENT ON COLUMN CharmRecipe.auto_build_channels IS 'A dictionary mapping snap names to channels to use when building this charm recipe.';
COMMENT ON COLUMN CharmRecipe.is_stale IS 'True if this charm recipe has not been built since a branch was updated.';
COMMENT ON COLUMN CharmRecipe.store_upload IS 'Whether builds of this charm recipe are automatically uploaded to the store.';
COMMENT ON COLUMN CharmRecipe.store_name IS 'The registered name of this charm in the store.';
COMMENT ON COLUMN CharmRecipe.store_secrets IS 'Serialized secrets issued by the store and the login service to authorize uploads of this charm.';
COMMENT ON COLUMN CharmRecipe.store_channels IS 'Channels to release this charm to after uploading it to the store.';

CREATE UNIQUE INDEX charmrecipe__owner__project__name__key
    ON CharmRecipe (owner, project, name);

CREATE INDEX charmrecipe__registrant__idx
    ON CharmRecipe (registrant);
CREATE INDEX charmrecipe__project__idx
    ON CharmRecipe (project);
CREATE INDEX charmrecipe__git_repository__idx
    ON CharmRecipe (git_repository);
CREATE INDEX charmrecipe__store_name__idx
    ON CharmRecipe (store_name);

CREATE TABLE CharmRecipeBuild (
    id serial PRIMARY KEY,
    build_request integer NOT NULL REFERENCES job,
    requester integer NOT NULL REFERENCES person,
    recipe integer NOT NULL REFERENCES charmrecipe,
    processor integer NOT NULL REFERENCES processor,
    channels jsonb,
    virtualized boolean NOT NULL,
    date_created timestamp without time zone DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC') NOT NULL,
    date_started timestamp without time zone,
    date_finished timestamp without time zone,
    date_first_dispatched timestamp without time zone,
    builder integer REFERENCES builder,
    status integer NOT NULL,
    log integer REFERENCES libraryfilealias,
    upload_log integer REFERENCES libraryfilealias,
    dependencies text,
    failure_count integer DEFAULT 0 NOT NULL,
    build_farm_job integer NOT NULL REFERENCES buildfarmjob,
    revision_id text,
    store_upload_json_data jsonb
);

COMMENT ON TABLE CharmRecipeBuild IS 'A build record for a charm recipe.';
COMMENT ON COLUMN CharmRecipeBuild.build_request IS 'The build request that caused this build to be created.';
COMMENT ON COLUMN CharmRecipeBuild.requester IS 'The person who requested this charm recipe build.';
COMMENT ON COLUMN CharmRecipeBuild.recipe IS 'The charm recipe to build.';
COMMENT ON COLUMN CharmRecipeBuild.processor IS 'The processor that the charm recipe should be built for.';
COMMENT ON COLUMN CharmRecipeBuild.channels IS 'A dictionary mapping snap names to channels to use for this build.';
COMMENT ON COLUMN CharmRecipeBuild.virtualized IS 'The virtualization setting required by this build farm job.';
COMMENT ON COLUMN CharmRecipeBuild.date_created IS 'When the build farm job record was created.';
COMMENT ON COLUMN CharmRecipeBuild.date_started IS 'When the build farm job started being processed.';
COMMENT ON COLUMN CharmRecipeBuild.date_finished IS 'When the build farm job finished being processed.';
COMMENT ON COLUMN CharmRecipeBuild.date_first_dispatched IS 'The instant the build was dispatched the first time.  This value will not get overridden if the build is retried.';
COMMENT ON COLUMN CharmRecipeBuild.builder IS 'The builder which processed this build farm job.';
COMMENT ON COLUMN CharmRecipeBuild.status IS 'The current build status.';
COMMENT ON COLUMN CharmRecipeBuild.log IS 'The log file for this build farm job stored in the librarian.';
COMMENT ON COLUMN CharmRecipeBuild.upload_log IS 'The upload log file for this build farm job stored in the librarian.';
COMMENT ON COLUMN CharmRecipeBuild.dependencies IS 'A Debian-like dependency line specifying the current missing dependencies for this build.';
COMMENT ON COLUMN CharmRecipeBuild.failure_count IS 'The number of consecutive failures on this job.  If excessive, the job may be terminated.';
COMMENT ON COLUMN CharmRecipeBuild.build_farm_job IS 'The build farm job with the base information.';
COMMENT ON COLUMN CharmRecipeBuild.revision_id IS 'The revision ID of the branch used for this build, if available.';
COMMENT ON COLUMN CharmRecipeBuild.store_upload_json_data IS 'Data that is related to the process of uploading a build to the store.';

CREATE INDEX charmrecipebuild__build_request__idx
    ON CharmRecipeBuild (build_request);
CREATE INDEX charmrecipebuild__requester__idx
    ON CharmRecipeBuild (requester);
CREATE INDEX charmrecipebuild__recipe__idx
    ON CharmRecipeBuild (recipe);
CREATE INDEX charmrecipebuild__log__idx
    ON CharmRecipeBuild (log);
CREATE INDEX charmrecipebuild__upload_log__idx
    ON CharmRecipeBuild (upload_log);
CREATE INDEX charmrecipebuild__build_farm_job__idx
    ON CharmRecipeBuild (build_farm_job);

-- CharmRecipe.requestBuild
CREATE INDEX charmrecipebuild__recipe__processor__status__idx
    ON CharmRecipeBuild (recipe, processor, status);

-- CharmRecipe.builds, CharmRecipe.completed_builds,
-- CharmRecipe.pending_builds
CREATE INDEX charmrecipebuild__recipe__status__started__finished__created__id__idx
    ON CharmRecipeBuild (
        recipe, status, GREATEST(date_started, date_finished) DESC NULLS LAST,
        date_created DESC, id DESC);

-- CharmRecipeBuild.getMedianBuildDuration
CREATE INDEX charmrecipebuild__recipe__processor__status__finished__idx
    ON CharmRecipeBuild (recipe, processor, status, date_finished DESC)
    -- 1 == FULLYBUILT
    WHERE status = 1;

CREATE TABLE CharmFile (
    id serial PRIMARY KEY,
    build integer NOT NULL REFERENCES charmrecipebuild,
    library_file integer NOT NULL REFERENCES libraryfilealias
);

COMMENT ON TABLE CharmFile IS 'A link between a charm recipe build and a file in the librarian that it produces.';
COMMENT ON COLUMN CharmFile.build IS 'The charm recipe build producing this file.';
COMMENT ON COLUMN CharmFile.library_file IS 'A file in the librarian.';

CREATE INDEX charmfile__build__idx
    ON CharmFile (build);
CREATE INDEX charmfile__library_file__idx
    ON CharmFile (library_file);

CREATE TABLE CharmRecipeJob (
    job integer PRIMARY KEY REFERENCES job ON DELETE CASCADE NOT NULL,
    recipe integer NOT NULL REFERENCES charmrecipe,
    job_type integer NOT NULL,
    json_data jsonb NOT NULL
);

COMMENT ON TABLE CharmRecipeJob IS 'Contains references to jobs that are executed for a charm recipe.';
COMMENT ON COLUMN CharmRecipeJob.job IS 'A reference to a Job row that has all the common job details.';
COMMENT ON COLUMN CharmRecipeJob.recipe IS 'The charm recipe that this job is for.';
COMMENT ON COLUMN CharmRecipeJob.job_type IS 'The type of a job, such as a build request.';
COMMENT ON COLUMN CharmRecipeJob.json_data IS 'Data that is specific to a particular job type.';

CREATE INDEX charmrecipejob__recipe__job_type__job__idx
    ON CharmRecipeJob (recipe, job_type, job);

CREATE TABLE CharmRecipeBuildJob (
    job integer PRIMARY KEY REFERENCES job ON DELETE CASCADE NOT NULL,
    build integer REFERENCES charmrecipebuild NOT NULL,
    job_type integer NOT NULL,
    json_data jsonb NOT NULL
);

COMMENT ON TABLE CharmRecipeBuildJob IS 'Contains references to jobs that are executed for a build of a charm recipe.';
COMMENT ON COLUMN CharmRecipeBuildJob.job IS 'A reference to a Job row that has all the common job details.';
COMMENT ON COLUMN CharmRecipeBuildJob.build IS 'The charm recipe build that this job is for.';
COMMENT ON COLUMN CharmRecipeBuildJob.job_type IS 'The type of a job, such as a store upload.';
COMMENT ON COLUMN CharmRecipeBuildJob.json_data IS 'Data that is specific to a particular job type.';

CREATE INDEX charmrecipebuildjob__build__job_type__job__idx
    ON CharmRecipeBuildJob(build, job_type, job);

ALTER TABLE Webhook ADD COLUMN charm_recipe integer REFERENCES CharmRecipe;

ALTER TABLE Webhook DROP CONSTRAINT one_target;
ALTER TABLE Webhook
    ADD CONSTRAINT one_target CHECK (
        null_count(ARRAY[git_repository, branch, snap, livefs, oci_recipe,
                         charm_recipe]) = 5);

CREATE INDEX webhook__charm_recipe__id__idx
    ON Webhook (charm_recipe, id) WHERE charm_recipe IS NOT NULL;

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 33, 0);
