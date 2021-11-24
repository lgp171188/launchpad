-- Copyright 2021 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

CREATE TABLE RevisionStatusReport (
    id serial PRIMARY KEY,
    git_repository integer REFERENCES gitrepository NOT NULL,
    commit_sha1 character(40) NOT NULL,
    name text NOT NULL,
    url text,
    description text,
    result integer,
    date_created timestamp without time zone DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC') NOT NULL,
    creator integer REFERENCES Person,
    date_started timestamp without time zone,
    date_finished timestamp without time zone,
    log integer
);

COMMENT ON TABLE RevisionStatusReport IS 'A status check for a code revision.';
COMMENT ON COLUMN RevisionStatusReport.git_repository IS 'The Git repository for this report..';
COMMENT ON COLUMN RevisionStatusReport.commit_sha1 IS 'The commit sha1 for the report.';
COMMENT ON COLUMN RevisionStatusReport.name IS 'Name of the report.';
COMMENT ON COLUMN RevisionStatusReport.url IS 'External URL to view result of report.';
COMMENT ON COLUMN RevisionStatusReport.description IS 'Text description of the result.';
COMMENT ON COLUMN RevisionStatusReport.result IS 'The result of the check job for this revision.';
COMMENT ON COLUMN RevisionStatusReport.date_created IS 'DateTime that report was created.';
COMMENT ON COLUMN RevisionStatusReport.creator IS 'The person that created the report.';
COMMENT ON COLUMN RevisionStatusReport.date_started IS 'DateTime that report was started.';
COMMENT ON COLUMN RevisionStatusReport.date_finished IS 'DateTime that report was completed.';
COMMENT ON COLUMN RevisionStatusReport.log IS 'The artifact produced for this report.';

CREATE INDEX revisionstatusreport__git_repository__commit_sha1__idx
    ON RevisionStatusReport (git_repository, commit_sha1);

CREATE INDEX revisionstatusreport__creator__idx
    ON RevisionStatusReport (creator);

CREATE TABLE RevisionStatusArtifact (
    id serial PRIMARY KEY,
    library_file integer REFERENCES libraryfilealias,
    report integer REFERENCES RevisionStatusReport
);

COMMENT ON TABLE RevisionStatusArtifact IS 'An artifact produced by a status check for a code revision.';
COMMENT ON COLUMN RevisionStatusArtifact.library_file IS 'LibraryFileAlias storing the contents of the artifact.';
COMMENT ON COLUMN RevisionStatusArtifact.report IS 'A link back to the report that the artifact was produced by.';

CREATE INDEX revision_status_artifact__library_file__idx
    ON RevisionStatusArtifact (library_file);
CREATE INDEX revision_status_artifact__report__idx
    ON RevisionStatusArtifact (report);

ALTER TABLE RevisionStatusReport
    ADD CONSTRAINT log_fkey FOREIGN KEY (log) REFERENCES RevisionStatusArtifact (id);

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 37, 0);
