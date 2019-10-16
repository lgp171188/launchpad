-- Copyright 2019 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

CREATE TABLE OCIProjectName (
    id serial PRIMARY KEY,
    name text NOT NULL,
    CONSTRAINT valid_name CHECK (valid_name(name))
);

COMMENT ON TABLE OCIProjectName IS 'A name of an Open Container Initiative project.';
COMMENT ON COLUMN OCIProjectName.name IS 'A lowercase name identifying an OCI project.';

CREATE UNIQUE INDEX ociprojectname__name__key ON OCIProjectName (name);
CREATE INDEX ociprojectname__name__trgm ON OCIProjectName
    USING gin (name trgm.gin_trgm_ops);

CREATE TABLE OCIProject (
    id serial PRIMARY KEY,
    date_created timestamp without time zone DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC') NOT NULL,
    date_last_modified timestamp without time zone DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC') NOT NULL,
    registrant integer NOT NULL REFERENCES person,
    distribution integer NOT NULL REFERENCES distribution,
    ociprojectname integer NOT NULL REFERENCES ociprojectname,
    description text,
    bug_reporting_guidelines text,
    bug_reported_acknowledgement text,
    enable_bugfiling_duplicate_search boolean DEFAULT true NOT NULL
);

COMMENT ON TABLE OCIProject IS 'A project containing Open Container Initiative recipes.';
COMMENT ON COLUMN OCIProject.date_created IS 'The date on which this OCI project was created in Launchpad.';
COMMENT ON COLUMN OCIProject.date_last_modified IS 'The date on which this OCI project was last modified in Launchpad.';
COMMENT ON COLUMN OCIProject.registrant IS 'The user who registered this OCI project.';
COMMENT ON COLUMN OCIProject.distribution IS 'The distribution that this OCI project belongs to.';
COMMENT ON COLUMN OCIProject.ociprojectname IS 'The name of this OCI project.';
COMMENT ON COLUMN OCIProject.description IS 'A short description of this OCI project.';
COMMENT ON COLUMN OCIProject.bug_reporting_guidelines IS 'Guidelines to the end user for reporting bugs on this OCI project';
COMMENT ON COLUMN OCIProject.bug_reported_acknowledgement IS 'A message of acknowledgement to display to a bug reporter after they''ve reported a new bug.';
COMMENT ON COLUMN OCIProject.enable_bugfiling_duplicate_search IS 'Enable/disable a search for possible duplicates when a bug is filed.';

CREATE UNIQUE INDEX ociproject__distribution__ociprojectname__key
    ON OCIProject (distribution, ociprojectname)
    WHERE distribution IS NOT NULL;
CREATE INDEX ociproject__registrant__idx
    ON OCIProject (registrant);

CREATE TABLE OCIProjectSeries (
    id serial PRIMARY KEY,
    ociproject integer NOT NULL REFERENCES ociproject,
    name text NOT NULL,
    summary text NOT NULL,
    date_created timestamp without time zone DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC') NOT NULL,
    registrant integer NOT NULL REFERENCES person,
    -- 2 == DEVELOPMENT
    status integer DEFAULT 2 NOT NULL,
    CONSTRAINT valid_name CHECK (valid_name(name))
);

COMMENT ON TABLE OCIProjectSeries IS 'A series of an Open Container Initiative project, used to allow tracking bugs against multiple versions of images.';
COMMENT ON COLUMN OCIProjectSeries.ociproject IS 'The OCI project that this series belongs to.';
COMMENT ON COLUMN OCIProjectSeries.name IS 'The name of this series.';
COMMENT ON COLUMN OCIProjectSeries.summary IS 'A brief summary of this series.';
COMMENT ON COLUMN OCIProjectSeries.date_created IS 'The date on which this series was created in Launchpad.';
COMMENT ON COLUMN OCIProjectSeries.registrant IS 'The user who registered this series.';
COMMENT ON COLUMN OCIProjectSeries.status IS 'The current status of this series.';

CREATE UNIQUE INDEX ociprojectseries__ociproject__name__key
    ON OCIProjectSeries (ociproject, name);
CREATE INDEX ociprojectseries__registrant__idx
    ON OCIProjectSeries (registrant);

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 08, 0);
