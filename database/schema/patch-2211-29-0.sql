-- Copyright 2024 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

CREATE TABLE CraftRecipe (
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
    auto_build_channels jsonb,
    is_stale boolean DEFAULT true NOT NULL,
    store_upload boolean DEFAULT false NOT NULL,
    store_name text,
    store_secrets text,
    store_channels jsonb,
    relative_build_score integer,
    CONSTRAINT valid_name CHECK (valid_name(name)),
    CONSTRAINT consistent_git_ref CHECK (
        (git_repository IS NULL) = (git_path IS NULL)),
    CONSTRAINT consistent_store_upload CHECK (
        NOT store_upload OR store_name IS NOT NULL)
);

COMMENT ON TABLE CraftRecipe IS 'A craft recipe.';
COMMENT ON COLUMN CraftRecipe.registrant IS 'The person who registered this craft recipe.';
COMMENT ON COLUMN CraftRecipe.owner IS 'The owner of this craft recipe.';
COMMENT ON COLUMN CraftRecipe.project IS 'The project that this craft recipe belongs to.';
COMMENT ON COLUMN CraftRecipe.name IS 'The name of the craft recipe, unique per owner and project.';
COMMENT ON COLUMN CraftRecipe.description IS 'A description of the craft recipe.';
COMMENT ON COLUMN CraftRecipe.git_repository IS 'A Git repository with a branch containing a craft.yaml recipe.';
COMMENT ON COLUMN CraftRecipe.git_path IS 'The path of the Git branch containing a craft.yaml recipe.';
COMMENT ON COLUMN CraftRecipe.build_path IS 'Subdirectory within the branch containing craft.yaml.';
COMMENT ON COLUMN CraftRecipe.require_virtualized IS 'If True, this craft package must be built only on a virtual machine.';
COMMENT ON COLUMN CraftRecipe.information_type IS 'Enum describing what type of information is stored, such as type of private or security related data, and used to determine how to apply an access policy.';
COMMENT ON COLUMN CraftRecipe.auto_build IS 'Whether this craft recipe is built automatically when its branch changes.';
COMMENT ON COLUMN CraftRecipe.auto_build_channels IS 'A dictionary mapping snap names to channels to use when building this craft recipe.';
COMMENT ON COLUMN CraftRecipe.is_stale IS 'True if this craft recipe has not been built since a branch was updated.';
COMMENT ON COLUMN CraftRecipe.store_upload IS 'Whether builds of this craft recipe are automatically uploaded to the store.';
COMMENT ON COLUMN CraftRecipe.store_name IS 'The registered name of this craft in the store.';
COMMENT ON COLUMN CraftRecipe.store_secrets IS 'Serialized secrets issued by the store and the login service to authorize uploads of this craft.';
COMMENT ON COLUMN CraftRecipe.store_channels IS 'Channels to release this craft to after uploading it to the store.';
COMMENT ON COLUMN CraftRecipe.relative_build_score IS 'A delta to the build score that is applied to all builds of this craft recipe.';

CREATE UNIQUE INDEX craftrecipe__owner__project__name__key
    ON CraftRecipe (owner, project, name);

CREATE INDEX craftrecipe__registrant__idx
    ON CraftRecipe (registrant);
CREATE INDEX craftrecipe__project__idx
    ON CraftRecipe (project);
CREATE INDEX craftrecipe__git_repository__idx
    ON CraftRecipe (git_repository);
CREATE INDEX craftrecipe__store_name__idx
    ON CraftRecipe (store_name);

CREATE TABLE CraftRecipeBuild (
    id serial PRIMARY KEY,
    build_request integer NOT NULL REFERENCES job,
    requester integer NOT NULL REFERENCES person,
    recipe integer NOT NULL REFERENCES craftrecipe,
    distro_arch_series integer NOT NULL REFERENCES distroarchseries,
    channels jsonb,
    processor integer NOT NULL REFERENCES processor,
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

COMMENT ON TABLE CraftRecipeBuild IS 'A build record for a craft recipe.';
COMMENT ON COLUMN CraftRecipeBuild.build_request IS 'The build request that caused this build to be created.';
COMMENT ON COLUMN CraftRecipeBuild.requester IS 'The person who requested this craft recipe build.';
COMMENT ON COLUMN CraftRecipeBuild.recipe IS 'The craft recipe to build.';
COMMENT ON COLUMN CraftRecipeBuild.distro_arch_series IS 'The distroarchseries that the craft recipe should build from.';
COMMENT ON COLUMN CraftRecipeBuild.channels IS 'A dictionary mapping snap names to channels to use for this build.';
COMMENT ON COLUMN CraftRecipeBuild.processor IS 'The processor that the craft recipe should be built for.';
COMMENT ON COLUMN CraftRecipeBuild.virtualized IS 'The virtualization setting required by this build farm job.';
COMMENT ON COLUMN CraftRecipeBuild.date_created IS 'When the build farm job record was created.';
COMMENT ON COLUMN CraftRecipeBuild.date_started IS 'When the build farm job started being processed.';
COMMENT ON COLUMN CraftRecipeBuild.date_finished IS 'When the build farm job finished being processed.';
COMMENT ON COLUMN CraftRecipeBuild.date_first_dispatched IS 'The instant the build was dispatched the first time.  This value will not get overridden if the build is retried.';
COMMENT ON COLUMN CraftRecipeBuild.builder IS 'The builder which processed this build farm job.';
COMMENT ON COLUMN CraftRecipeBuild.status IS 'The current build status.';
COMMENT ON COLUMN CraftRecipeBuild.log IS 'The log file for this build farm job stored in the librarian.';
COMMENT ON COLUMN CraftRecipeBuild.upload_log IS 'The upload log file for this build farm job stored in the librarian.';
COMMENT ON COLUMN CraftRecipeBuild.dependencies IS 'A Debian-like dependency line specifying the current missing dependencies for this build.';
COMMENT ON COLUMN CraftRecipeBuild.failure_count IS 'The number of consecutive failures on this job.  If excessive, the job may be terminated.';
COMMENT ON COLUMN CraftRecipeBuild.build_farm_job IS 'The build farm job with the base information.';
COMMENT ON COLUMN CraftRecipeBuild.revision_id IS 'The revision ID of the branch used for this build, if available.';
COMMENT ON COLUMN CraftRecipeBuild.store_upload_json_data IS 'Data that is related to the process of uploading a build to the store.';

CREATE INDEX craftrecipebuild__build_request__idx
    ON CraftRecipeBuild (build_request);
CREATE INDEX craftrecipebuild__requester__idx
    ON CraftRecipeBuild (requester);
CREATE INDEX craftrecipebuild__recipe__idx
    ON CraftRecipeBuild (recipe);
CREATE INDEX craftrecipebuild__distro_arch_series__idx
    ON CraftRecipeBuild (distro_arch_series);
CREATE INDEX craftrecipebuild__log__idx
    ON CraftRecipeBuild (log);
CREATE INDEX craftrecipebuild__upload_log__idx
    ON CraftRecipeBuild (upload_log);
CREATE INDEX craftrecipebuild__build_farm_job__idx
    ON CraftRecipeBuild (build_farm_job);

-- CraftRecipe.requestBuild
CREATE INDEX craftrecipebuild__recipe__das__status__idx
    ON CraftRecipeBuild (recipe, distro_arch_series, status);

-- CraftRecipe.builds, CraftRecipe.completed_builds,
-- CraftRecipe.pending_builds
CREATE INDEX craftrecipebuild__recipe__status__started__finished__created__id__idx
    ON CraftRecipeBuild (
        recipe, status, GREATEST(date_started, date_finished) DESC NULLS LAST,
        date_created DESC, id DESC);

-- CraftRecipeBuild.getMedianBuildDuration
CREATE INDEX craftrecipebuild__recipe__das__status__finished__idx
    ON CraftRecipeBuild (recipe, distro_arch_series, status, date_finished DESC)
    -- 1 == FULLYBUILT
    WHERE status = 1;

CREATE TABLE CraftFile (
    id serial PRIMARY KEY,
    build integer NOT NULL REFERENCES craftrecipebuild,
    library_file integer NOT NULL REFERENCES libraryfilealias
);

COMMENT ON TABLE CraftFile IS 'A link between a craft recipe build and a file in the librarian that it produces.';
COMMENT ON COLUMN CraftFile.build IS 'The craft recipe build producing this file.';
COMMENT ON COLUMN CraftFile.library_file IS 'A file in the librarian.';

CREATE INDEX craftfile__build__idx
    ON CraftFile (build);
CREATE INDEX craftfile__library_file__idx
    ON CraftFile (library_file);

CREATE TABLE CraftRecipeJob (
    job integer PRIMARY KEY REFERENCES job ON DELETE CASCADE NOT NULL,
    recipe integer NOT NULL REFERENCES craftrecipe,
    job_type integer NOT NULL,
    json_data jsonb NOT NULL
);

COMMENT ON TABLE CraftRecipeJob IS 'Contains references to jobs that are executed for a craft recipe.';
COMMENT ON COLUMN CraftRecipeJob.job IS 'A reference to a Job row that has all the common job details.';
COMMENT ON COLUMN CraftRecipeJob.recipe IS 'The craft recipe that this job is for.';
COMMENT ON COLUMN CraftRecipeJob.job_type IS 'The type of a job, such as a build request.';
COMMENT ON COLUMN CraftRecipeJob.json_data IS 'Data that is specific to a particular job type.';

CREATE INDEX craftrecipejob__recipe__job_type__job__idx
    ON CraftRecipeJob (recipe, job_type, job);

CREATE TABLE CraftRecipeBuildJob (
    job integer PRIMARY KEY REFERENCES job ON DELETE CASCADE NOT NULL,
    build integer REFERENCES craftrecipebuild NOT NULL,
    job_type integer NOT NULL,
    json_data jsonb NOT NULL
);

COMMENT ON TABLE CraftRecipeBuildJob IS 'Contains references to jobs that are executed for a build of a craft recipe.';
COMMENT ON COLUMN CraftRecipeBuildJob.job IS 'A reference to a Job row that has all the common job details.';
COMMENT ON COLUMN CraftRecipeBuildJob.build IS 'The craft recipe build that this job is for.';
COMMENT ON COLUMN CraftRecipeBuildJob.job_type IS 'The type of a job, such as a store upload.';
COMMENT ON COLUMN CraftRecipeBuildJob.json_data IS 'Data that is specific to a particular job type.';

CREATE INDEX craftrecipebuildjob__build__job_type__job__idx
    ON CraftRecipeBuildJob(build, job_type, job);

ALTER TABLE Webhook ADD COLUMN craft_recipe integer REFERENCES CraftRecipe;

ALTER TABLE Webhook DROP CONSTRAINT one_target;
ALTER TABLE Webhook
    ADD CONSTRAINT one_target CHECK (
        (public.null_count(ARRAY[git_repository, branch, snap, livefs, oci_recipe, charm_recipe, rock_recipe, craft_recipe, project, distribution]) = 9) AND
        (source_package_name IS NULL OR distribution IS NOT NULL)
    );

CREATE INDEX webhook__craft_recipe__id__idx
    ON Webhook (craft_recipe, id) WHERE craft_recipe IS NOT NULL;

INSERT INTO LaunchpadDatabaseRevision VALUES (2211, 29, 0);
