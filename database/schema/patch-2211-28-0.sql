-- Copyright 2024 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

CREATE TABLE RockRecipe (
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

COMMENT ON TABLE RockRecipe IS 'A rock recipe.';
COMMENT ON COLUMN RockRecipe.registrant IS 'The person who registered this rock recipe.';
COMMENT ON COLUMN RockRecipe.owner IS 'The owner of this rock recipe.';
COMMENT ON COLUMN RockRecipe.project IS 'The project that this rock recipe belongs to.';
COMMENT ON COLUMN RockRecipe.name IS 'The name of the rock recipe, unique per owner and project.';
COMMENT ON COLUMN RockRecipe.description IS 'A description of the rock recipe.';
COMMENT ON COLUMN RockRecipe.git_repository IS 'A Git repository with a branch containing a rockcraft.yaml recipe.';
COMMENT ON COLUMN RockRecipe.git_path IS 'The path of the Git branch containing a rockcraft.yaml recipe.';
COMMENT ON COLUMN RockRecipe.build_path IS 'Subdirectory within the branch containing rockcraft.yaml.';
COMMENT ON COLUMN RockRecipe.require_virtualized IS 'If True, this snap package must be built only on a virtual machine.';
COMMENT ON COLUMN RockRecipe.information_type IS 'Enum describing what type of information is stored, such as type of private or security related data, and used to determine how to apply an access policy.';
COMMENT ON COLUMN RockRecipe.auto_build IS 'Whether this rock recipe is built automatically when its branch changes.';
COMMENT ON COLUMN RockRecipe.auto_build_channels IS 'A dictionary mapping snap names to channels to use when building this rock recipe.';
COMMENT ON COLUMN RockRecipe.is_stale IS 'True if this rock recipe has not been built since a branch was updated.';
COMMENT ON COLUMN RockRecipe.store_upload IS 'Whether builds of this rock recipe are automatically uploaded to the store.';
COMMENT ON COLUMN RockRecipe.store_name IS 'The registered name of this rock in the store.';
COMMENT ON COLUMN RockRecipe.store_secrets IS 'Serialized secrets issued by the store and the login service to authorize uploads of this rock.';
COMMENT ON COLUMN RockRecipe.store_channels IS 'Channels to release this rock to after uploading it to the store.';
COMMENT ON COLUMN RockRecipe.relative_build_score IS 'A delta to the build score that is applied to all builds of this rock recipe.';

CREATE UNIQUE INDEX rockrecipe__owner__project__name__key
    ON RockRecipe (owner, project, name);

CREATE INDEX rockrecipe__registrant__idx
    ON RockRecipe (registrant);
CREATE INDEX rockrecipe__project__idx
    ON RockRecipe (project);
CREATE INDEX rockrecipe__git_repository__idx
    ON RockRecipe (git_repository);
CREATE INDEX rockrecipe__store_name__idx
    ON RockRecipe (store_name);
CREATE INDEX rockrecipe__is_stale__auto_build__idx
    ON RockRecipe(is_stale, auto_build);

CREATE TABLE RockRecipeBuild (
    id serial PRIMARY KEY,
    build_request integer NOT NULL REFERENCES job,
    requester integer NOT NULL REFERENCES person,
    recipe integer NOT NULL REFERENCES rockrecipe,
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

COMMENT ON TABLE RockRecipeBuild IS 'A build record for a rock recipe.';
COMMENT ON COLUMN RockRecipeBuild.build_request IS 'The build request that caused this build to be created.';
COMMENT ON COLUMN RockRecipeBuild.requester IS 'The person who requested this rock recipe build.';
COMMENT ON COLUMN RockRecipeBuild.recipe IS 'The rock recipe to build.';
COMMENT ON COLUMN RockRecipeBuild.distro_arch_series IS 'The distroarchseries that the rock recipe should build from.';
COMMENT ON COLUMN RockRecipeBuild.channels IS 'A dictionary mapping snap names to channels to use for this build.';
COMMENT ON COLUMN RockRecipeBuild.processor IS 'The processor that the rock recipe should be built for.';
COMMENT ON COLUMN RockRecipeBuild.virtualized IS 'The virtualization setting required by this build farm job.';
COMMENT ON COLUMN RockRecipeBuild.date_created IS 'When the build farm job record was created.';
COMMENT ON COLUMN RockRecipeBuild.date_started IS 'When the build farm job started being processed.';
COMMENT ON COLUMN RockRecipeBuild.date_finished IS 'When the build farm job finished being processed.';
COMMENT ON COLUMN RockRecipeBuild.date_first_dispatched IS 'The instant the build was dispatched the first time.  This value will not get overridden if the build is retried.';
COMMENT ON COLUMN RockRecipeBuild.builder IS 'The builder which processed this build farm job.';
COMMENT ON COLUMN RockRecipeBuild.status IS 'The current build status.';
COMMENT ON COLUMN RockRecipeBuild.log IS 'The log file for this build farm job stored in the librarian.';
COMMENT ON COLUMN RockRecipeBuild.upload_log IS 'The upload log file for this build farm job stored in the librarian.';
COMMENT ON COLUMN RockRecipeBuild.dependencies IS 'A Debian-like dependency line specifying the current missing dependencies for this build.';
COMMENT ON COLUMN RockRecipeBuild.failure_count IS 'The number of consecutive failures on this job.  If excessive, the job may be terminated.';
COMMENT ON COLUMN RockRecipeBuild.build_farm_job IS 'The build farm job with the base information.';
COMMENT ON COLUMN RockRecipeBuild.revision_id IS 'The revision ID of the branch used for this build, if available.';
COMMENT ON COLUMN RockRecipeBuild.store_upload_json_data IS 'Data that is related to the process of uploading a build to the store.';

CREATE INDEX rockrecipebuild__build_request__idx
    ON RockRecipeBuild (build_request);
CREATE INDEX rockrecipebuild__requester__idx
    ON RockRecipeBuild (requester);
CREATE INDEX rockrecipebuild__recipe__idx
    ON RockRecipeBuild (recipe);
CREATE INDEX rockrecipebuild__distro_arch_series__idx
    ON RockRecipeBuild (distro_arch_series);
CREATE INDEX rockrecipebuild__log__idx
    ON RockRecipeBuild (log);
CREATE INDEX rockrecipebuild__upload_log__idx
    ON RockRecipeBuild (upload_log);
CREATE INDEX rockrecipebuild__build_farm_job__idx
    ON RockRecipeBuild (build_farm_job);

-- RockRecipe.requestBuild
CREATE INDEX rockrecipebuild__recipe__das__status__idx
    ON RockRecipeBuild (recipe, distro_arch_series, status);

-- RockRecipe.builds, RockRecipe.completed_builds,
-- RockRecipe.pending_builds
CREATE INDEX rockrecipebuild__recipe__status__started__finished__created__id__idx
    ON RockRecipeBuild (
        recipe, status, GREATEST(date_started, date_finished) DESC NULLS LAST,
        date_created DESC, id DESC);

-- RockRecipeBuild.getMedianBuildDuration
CREATE INDEX rockrecipebuild__recipe__das__status__finished__idx
    ON RockRecipeBuild (recipe, distro_arch_series, status, date_finished DESC)
    -- 1 == FULLYBUILT
    WHERE status = 1;

CREATE TABLE RockFile (
    id serial PRIMARY KEY,
    build integer NOT NULL REFERENCES rockrecipebuild,
    library_file integer NOT NULL REFERENCES libraryfilealias
);

COMMENT ON TABLE RockFile IS 'A link between a rock recipe build and a file in the librarian that it produces.';
COMMENT ON COLUMN RockFile.build IS 'The rock recipe build producing this file.';
COMMENT ON COLUMN RockFile.library_file IS 'A file in the librarian.';

CREATE INDEX rockfile__build__idx
    ON RockFile (build);
CREATE INDEX rockfile__library_file__idx
    ON RockFile (library_file);

CREATE TABLE RockRecipeJob (
    job integer PRIMARY KEY REFERENCES job ON DELETE CASCADE NOT NULL,
    recipe integer NOT NULL REFERENCES rockrecipe,
    job_type integer NOT NULL,
    json_data jsonb NOT NULL
);

COMMENT ON TABLE RockRecipeJob IS 'Contains references to jobs that are executed for a rock recipe.';
COMMENT ON COLUMN RockRecipeJob.job IS 'A reference to a Job row that has all the common job details.';
COMMENT ON COLUMN RockRecipeJob.recipe IS 'The rock recipe that this job is for.';
COMMENT ON COLUMN RockRecipeJob.job_type IS 'The type of a job, such as a build request.';
COMMENT ON COLUMN RockRecipeJob.json_data IS 'Data that is specific to a particular job type.';

CREATE INDEX rockrecipejob__recipe__job_type__job__idx
    ON RockRecipeJob (recipe, job_type, job);

CREATE TABLE RockRecipeBuildJob (
    job integer PRIMARY KEY REFERENCES job ON DELETE CASCADE NOT NULL,
    build integer REFERENCES rockrecipebuild NOT NULL,
    job_type integer NOT NULL,
    json_data jsonb NOT NULL
);

COMMENT ON TABLE RockRecipeBuildJob IS 'Contains references to jobs that are executed for a build of a rock recipe.';
COMMENT ON COLUMN RockRecipeBuildJob.job IS 'A reference to a Job row that has all the common job details.';
COMMENT ON COLUMN RockRecipeBuildJob.build IS 'The rock recipe build that this job is for.';
COMMENT ON COLUMN RockRecipeBuildJob.job_type IS 'The type of a job, such as a store upload.';
COMMENT ON COLUMN RockRecipeBuildJob.json_data IS 'Data that is specific to a particular job type.';

CREATE INDEX rockrecipebuildjob__build__job_type__job__idx
    ON RockRecipeBuildJob(build, job_type, job);

ALTER TABLE Webhook ADD COLUMN rock_recipe integer REFERENCES RockRecipe;

ALTER TABLE Webhook DROP CONSTRAINT one_target;
ALTER TABLE Webhook
    ADD CONSTRAINT one_target CHECK (
        (public.null_count(ARRAY[git_repository, branch, snap, livefs, oci_recipe, charm_recipe, rock_recipe, project, distribution]) = 8) AND
        (source_package_name IS NULL OR distribution IS NOT NULL)
    );

CREATE INDEX webhook__rock_recipe__id__idx
    ON Webhook (rock_recipe, id) WHERE rock_recipe IS NOT NULL;

INSERT INTO LaunchpadDatabaseRevision VALUES (2211, 28, 0);
