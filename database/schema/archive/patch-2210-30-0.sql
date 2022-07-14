-- Copyright 2021 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE ArchiveDependency
    ADD COLUMN snap_base integer REFERENCES snapbase,
    ALTER COLUMN archive DROP NOT NULL,
    ADD CONSTRAINT one_parent CHECK (null_count(ARRAY[archive, snap_base]) = 1);

CREATE INDEX archivedependency__snap_base__idx
    ON ArchiveDependency (snap_base);

COMMENT ON TABLE ArchiveDependency IS 'This table maps a given parent (archive or snap base) to all other archives it should depend on.';
COMMENT ON COLUMN ArchiveDependency.snap_base IS 'The snap base that has this dependency.';

ALTER TABLE SnapBuild ADD COLUMN snap_base integer REFERENCES snapbase;

COMMENT ON COLUMN SnapBuild.snap_base IS 'The snap base to use for this build.';

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 30, 0);
