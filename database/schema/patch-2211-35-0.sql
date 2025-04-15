-- Copyright 2025 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

CREATE TABLE bugpresence (
    id serial PRIMARY KEY,
    bug integer NOT NULL REFERENCES bug,
    project integer REFERENCES project,
    distribution integer REFERENCES distribution,
    source_package_name integer REFERENCES sourcepackagename,
    git_repository integer REFERENCES gitrepository,
    break_fix_data JSONB
);

CREATE INDEX bugpresence__bug__idx ON bugpresence (bug);
CREATE INDEX bugpresence__project__idx ON bugpresence (project);
CREATE INDEX bugpresence__distribution__idx ON bugpresence (distribution);
CREATE INDEX bugpresence__source_package_name__idx
  ON bugpresence (source_package_name);
CREATE INDEX bugpresence__git_repository__idx ON bugpresence (git_repository);

COMMENT ON TABLE bugpresence IS 'Stores information about points in the code
 history (like commit IDs and versions) of various entities like a project, a
 distribution, or a distribution source package when something was broken
 and/or when it was fixed.';
COMMENT ON COLUMN bugpresence.bug IS 'The bug that this bug presence row is
 related to.';
COMMENT ON COLUMN bugpresence.project IS 'The project that this bug presence
 row is related to.';
COMMENT ON COLUMN bugpresence.distribution IS 'The distribution that this bug
 presence row is related to.';
COMMENT ON COLUMN bugpresence.source_package_name IS 'The source package name
 that this bug presence row relates to.';
COMMENT ON COLUMN bugpresence.git_repository IS 'The git repository that this
 bug presence row is related to.';
COMMENT ON COLUMN bugpresence.break_fix_data IS 'Information about the commits
 that caused an issue (break) and the commits that fixed the issue (fix).';

CREATE TABLE sourcepackageseries (
    id serial PRIMARY KEY,
    distroseries integer NOT NULL REFERENCES distroseries,
    source_package_name integer NOT NULL REFERENCES sourcepackagename,
    name TEXT NOT NULL,
    status integer NOT NULL,
    repositories JSONB,
    CONSTRAINT valid_name CHECK (valid_name(name))
);

CREATE INDEX sourcepackageseries__distroseries__idx
  ON sourcepackageseries (distroseries);
CREATE INDEX sourcepackageseries__source_package_name__idx
  ON sourcepackageseries (source_package_name);
CREATE INDEX sourcepackageseries__name__idx
  ON sourcepackageseries (name);
CREATE INDEX sourcepackageseries__status__idx
  ON sourcepackageseries (status);

COMMENT ON TABLE sourcepackageseries IS 'The per-package series of a source
 package in a distroseries.';
COMMENT ON COLUMN sourcepackageseries.distroseries IS 'The distroseries of
 this sourcepackageseries.';
COMMENT ON COLUMN sourcepackageseries.source_package_name IS 'The
 sourcepackagename of this sourcepackageseries.';
COMMENT ON COLUMN sourcepackageseries.name IS 'The name of this
 sourcepackageseries.';
COMMENT ON COLUMN sourcepackageseries.status IS 'The status of this
 sourcepackageseries.';
COMMENT ON COLUMN sourcepackageseries.repositories IS 'Repositories related to
 this sourcepackageseries.';

INSERT INTO LaunchpadDatabaseRevision VALUES (2211, 35, 0);
