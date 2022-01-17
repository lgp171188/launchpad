-- Copyright 2022 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

CREATE TABLE CIBuild (
    id serial PRIMARY KEY,
    git_repository integer NOT NULL REFERENCES gitrepository,
    commit_sha1 character(40) NOT NULL,
    distro_arch_series integer NOT NULL REFERENCES distroarchseries,
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
    failure_count integer DEFAULT 0 NOT NULL,
    build_farm_job integer NOT NULL REFERENCES buildfarmjob
);

COMMENT ON TABLE CIBuild IS 'A build record for a CI job.';
COMMENT ON COLUMN CIBuild.git_repository IS 'The Git repository for this CI job.';
COMMENT ON COLUMN CIBuild.commit_sha1 IS 'The Git commit ID for this CI job.';
COMMENT ON COLUMN CIBuild.distro_arch_series IS 'The distroarchseries that this CI job should run on.';
COMMENT ON COLUMN CIBuild.processor IS 'The processor that this CI job should run on.';
COMMENT ON COLUMN CIBuild.virtualized IS 'The virtualization setting required by this build farm job.';
COMMENT ON COLUMN CIBuild.date_created IS 'When the build farm job record was created.';
COMMENT ON COLUMN CIBuild.date_started IS 'When the build farm job started being processed.';
COMMENT ON COLUMN CIBuild.date_finished IS 'When the build farm job finished being processed.';
COMMENT ON COLUMN CIBuild.date_first_dispatched IS 'The instant the build was dispatched the first time.  This value will not get overridden if the build is retried.';
COMMENT ON COLUMN CIBuild.builder IS 'The builder which processed this build farm job.';
COMMENT ON COLUMN CIBuild.status IS 'The current build status.';
COMMENT ON COLUMN CIBuild.log IS 'The log file for this build farm job stored in the librarian.';
COMMENT ON COLUMN CIBuild.upload_log IS 'The upload log file for this build farm job stored in the librarian.';
COMMENT ON COLUMN CIBuild.failure_count IS 'The number of consecutive failures on this job.  If excessive, the job may be terminated.';
COMMENT ON COLUMN CIBuild.build_farm_job IS 'The build farm job with the base information.';

CREATE INDEX cibuild__distro_arch_series__idx
    ON CIBuild (distro_arch_series);
CREATE INDEX cibuild__log__idx
    ON CIBuild (log);
CREATE INDEX cibuild__upload_log__idx
    ON CIBuild (upload_log);
CREATE INDEX cibuild__build_farm_job__idx
    ON CIBuild (build_farm_job);

-- CIBuildSet.requestBuild
CREATE INDEX cibuild__commit__das__status__idx
    ON CIBuild (git_repository, commit_sha1, distro_arch_series, status);

-- builds listings
CREATE INDEX cibuild__commit__status__started__finished__created__id__idx
    ON CIBuild (
        git_repository, commit_sha1, status,
        GREATEST(date_started, date_finished) DESC NULLS LAST,
        date_created DESC, id DESC);

-- CIBuild.getMedianBuildDuration
CREATE INDEX cibuild__git_repository__das__status__finished__idx
    ON CIBuild (git_repository, distro_arch_series, status, date_finished DESC)
    -- 1 == FULLYBUILT
    WHERE status = 1;

ALTER TABLE RevisionStatusReport
    ADD COLUMN ci_build integer REFERENCES cibuild;

COMMENT ON COLUMN RevisionStatusReport.ci_build IS 'The CI build that produced this report.';

CREATE UNIQUE INDEX revisionstatusreport__ci_build__name__idx
    ON RevisionStatusReport (ci_build, name)
    WHERE ci_build IS NOT NULL;

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 40, 0);
