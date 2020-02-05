-- Copyright 2019 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

CREATE TABLE OCIRecipe (
    id serial PRIMARY KEY,
    date_created timestamp without time zone DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC') NOT NULL,
    date_last_modified timestamp without time zone DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC') NOT NULL,
    registrant integer NOT NULL REFERENCES person,
    owner integer NOT NULL REFERENCES person,
    oci_project integer NOT NULL REFERENCES ociproject,
    name text NOT NULL,
    description text,
    official boolean DEFAULT false NOT NULL,
    git_repository integer REFERENCES gitrepository,
    git_path text NOT NULL,
    build_file text NOT NULL,
    require_virtualized boolean DEFAULT true NOT NULL,
    build_daily boolean DEFAULT false NOT NULL
);

COMMENT ON TABLE OCIRecipe IS 'A recipe for building Open Container Initiative images.';
COMMENT ON COLUMN OCIRecipe.date_created IS 'The date on which this recipe was created in Launchpad.';
COMMENT ON COLUMN OCIRecipe.date_last_modified IS 'The date on which this recipe was last modified in Launchpad.';
COMMENT ON COLUMN OCIRecipe.registrant IS 'The user who registered this recipe.';
COMMENT ON COLUMN OCIRecipe.owner IS 'The owner of the recipe.';
COMMENT ON COLUMN OCIRecipe.oci_project IS 'The OCI project that this recipe is for.';
COMMENT ON COLUMN OCIRecipe.official IS 'True if this recipe is official for its OCI project.';
COMMENT ON COLUMN OCIRecipe.name IS 'The name of this recipe.';
COMMENT ON COLUMN OCIRecipe.description IS 'A short description of this recipe.';
COMMENT ON COLUMN OCIRecipe.git_repository IS 'A Git repository with a branch containing an OCI recipe.';
COMMENT ON COLUMN OCIRecipe.git_path IS 'The branch within this recipe''s Git repository where its build files are maintained.';
COMMENT ON COLUMN OCIRecipe.build_file IS 'The relative path to the file within this recipe''s branch that defines how to build the recipe.';
COMMENT ON COLUMN OCIRecipe.require_virtualized IS 'If True, this recipe must be built only on a virtual machine.';
COMMENT ON COLUMN OCIRecipe.build_daily IS 'If True, this recipe should be built daily.';

CREATE UNIQUE INDEX ocirecipe__owner__oci_project__name__key
    ON OCIRecipe (owner, oci_project, name);
CREATE UNIQUE INDEX ocirecipe__oci_project__name__official__key
    ON OCIRecipe (oci_project, name)
    WHERE official;
CREATE INDEX ocirecipe__registrant__idx ON OCIRecipe (registrant);
CREATE INDEX ocirecipe__oci_project__idx ON OCIRecipe (oci_project);
CREATE INDEX ocirecipe__git_repository__idx ON OCIRecipe (git_repository);

CREATE TABLE OCIRecipeArch (
    recipe integer NOT NULL REFERENCES ocirecipe,
    processor integer NOT NULL REFERENCES processor,
    PRIMARY KEY (recipe, processor)
);

COMMENT ON TABLE OCIRecipeArch IS 'The architectures an OCI recipe should be built for.';
COMMENT ON COLUMN OCIRecipeArch.recipe IS 'The OCI recipe for which an architecture is specified.';
COMMENT ON COLUMN OCIRecipeArch.processor IS 'The architecture for which the OCI recipe should be built.';

CREATE TABLE OCIRecipeBuild (
    id serial PRIMARY KEY,
    requester integer NOT NULL REFERENCES person,
    recipe integer NOT NULL REFERENCES ocirecipe,
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
    build_farm_job integer NOT NULL REFERENCES buildfarmjob
);

COMMENT ON TABLE OCIRecipeBuild IS 'A build record for an OCI recipe.';
COMMENT ON COLUMN OCIRecipeBuild.requester IS 'The person who requested this OCI recipe build.';
COMMENT ON COLUMN OCIRecipeBuild.recipe IS 'The OCI recipe to build.';
COMMENT ON COLUMN OCIRecipeBuild.processor IS 'The processor that the OCI recipe should be built for.';
COMMENT ON COLUMN OCIRecipeBuild.virtualized IS 'The virtualization setting required by this build farm job.';
COMMENT ON COLUMN OCIRecipeBuild.date_created IS 'When the build farm job record was created.';
COMMENT ON COLUMN OCIRecipeBuild.date_started IS 'When the build farm job started being processed.';
COMMENT ON COLUMN OCIRecipeBuild.date_finished IS 'When the build farm job finished being processed.';
COMMENT ON COLUMN OCIRecipeBuild.date_first_dispatched IS 'The instant the build was dispatched the first time.  This value will not get overridden if the build is retried.';
COMMENT ON COLUMN OCIRecipeBuild.builder IS 'The builder which processed this build farm job.';
COMMENT ON COLUMN OCIRecipeBuild.status IS 'The current build status.';
COMMENT ON COLUMN OCIRecipeBuild.log IS 'The log file for this build farm job stored in the librarian.';
COMMENT ON COLUMN OCIRecipeBuild.upload_log IS 'The upload log file for this build farm job stored in the librarian.';
COMMENT ON COLUMN OCIRecipeBuild.dependencies IS 'A Debian-like dependency line specifying the current missing dependencies for this build.';
COMMENT ON COLUMN OCIRecipeBuild.failure_count IS 'The number of consecutive failures on this job.  If excessive, the job may be terminated.';
COMMENT ON COLUMN OCIRecipeBuild.build_farm_job IS 'The build farm job with the base information.';

CREATE INDEX ocirecipebuild__requester__idx
    ON OCIRecipeBuild (requester);
CREATE INDEX ocirecipebuild__recipe__idx
    ON OCIRecipeBuild (recipe);
CREATE INDEX ocirecipebuild__log__idx
    ON OCIRecipeBuild (log);
CREATE INDEX ocirecipebuild__upload_log__idx
    ON OCIRecipeBuild (upload_log);
CREATE INDEX ocirecipebuild__build_farm_job__idx
    ON OCIRecipeBuild (build_farm_job);

-- OCIRecipe.requestBuild
CREATE INDEX ocirecipebuild__recipe__processor__status__idx
    ON OCIRecipeBuild (recipe, processor, status);

-- OCIRecipe.builds, OCIRecipe.completed_builds, OCIRecipe.pending_builds
CREATE INDEX ocirecipebuild__recipe__status__started__finished__created__id__idx
    ON OCIRecipeBuild (
        recipe, status, GREATEST(date_started, date_finished) DESC NULLS LAST,
        date_created DESC, id DESC);

-- OCIRecipeBuild.getMedianBuildDuration
CREATE INDEX ocirecipebuild__recipe__processor__status__finished__idx
    ON OCIRecipeBuild (recipe, processor, status, date_finished DESC)
    -- 1 == FULLYBUILT
    WHERE status = 1;

CREATE TABLE OCIFile (
    id serial PRIMARY key,
    build integer NOT NULL REFERENCES ocirecipebuild,
    library_file integer NOT NULL REFERENCES libraryfilealias,
    layer_file_digest character(80)
);

CREATE UNIQUE INDEX ocifile__build__layer_file_digest__key
    ON OCIFile (build, layer_file_digest);
CREATE INDEX ocifile__library_file__idx
    ON OCIFile (library_file);
CREATE INDEX ocifile__layer_file_digest__idx
    ON OCIFile (layer_file_digest);

COMMENT ON TABLE OCIFile IS 'A link between an OCI recipe build and a file in the librarian that it produces.';
COMMENT ON COLUMN OCIFile.build IS 'The OCI recipe build producing this file.';
COMMENT ON COLUMN OCIFile.library_file IS 'A file in the librarian.';
COMMENT ON COLUMN OCIFile.layer_file_digest IS 'Content-addressable hash of the file''s contents, used for reassembling image layers when pushing a build to a registry.  This hash is in an opaque format generated by the OCI build tool.';

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 08, 3);
