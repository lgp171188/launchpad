-- Copyright 2021 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

CREATE TABLE RevisionStatusReport (
    id serial PRIMARY KEY,
    name text NOT NULL,
    git_repository integer REFERENCES gitrepository NOT NULL,
    commit_sha1 character(40) NOT NULL,
    status INTEGER NOT NULL,
    external_url text,
    description text,
    result integer,
    date_created timestamp without time zone DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC') NOT NULL,
    date_started timestamp without time zone DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC') NOT NULL,
    date_finished timestamp without time zone
);

COMMENT ON TABLE RevisionStatusReport IS 'This table links the submitted reports to the target git references.';
COMMENT ON COLUMN RevisionStatusReport.name IS 'Name of the report.';
COMMENT ON COLUMN RevisionStatusReport.status IS 'One of the RevisionStatus enum values: Queued, Started, Completed, FailedToStart.';
COMMENT ON COLUMN RevisionStatusReport.external_url IS 'External URL to view result of report.';
COMMENT ON COLUMN RevisionStatusReport.description IS 'Text description of the result.';
COMMENT ON COLUMN RevisionStatusReport.git_repository IS 'Reference to the GitRepository.';
COMMENT ON COLUMN RevisionStatusReport.commit_sha1 IS 'The commit sha1 for the report.';
COMMENT ON COLUMN RevisionStatusReport.result IS 'One of the RevisionStatusResult enum values: Success, Failed, Skipped, Cancelled.';
COMMENT ON COLUMN RevisionStatusReport.date_created IS 'DateTime that report was created.';
COMMENT ON COLUMN RevisionStatusReport.date_started IS 'DateTime that report was started.';
COMMENT ON COLUMN RevisionStatusReport.date_finished IS 'DateTime that report was completed.';

CREATE INDEX revision_status_report__git_repository__idx
    ON RevisionStatusReport (git_repository);

CREATE TABLE RevisionStatusArtifact (
    id serial PRIMARY KEY,
    library_file integer REFERENCES libraryfilealias,
    revision_status integer REFERENCES RevisionStatusReport
);

COMMENT ON TABLE RevisionStatusArtifact IS 'A thin wrapper around LibraryFileAlias.';
COMMENT ON COLUMN RevisionStatusArtifact.library_file IS 'Reference to LibraryFileAlias.';
COMMENT ON COLUMN RevisionStatusArtifact.revision_status IS 'Reference to RevisionStatusReport.';

CREATE INDEX revision_status_artifact__library_file__idx
    ON RevisionStatusArtifact (library_file);
CREATE INDEX revision_status_artifact__revision_status__idx
    ON RevisionStatusArtifact (revision_status);

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 37, 0);
