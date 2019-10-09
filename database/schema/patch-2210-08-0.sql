-- Copyright 2019 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

CREATE TABLE OCIRecipeName (
    id serial PRIMARY KEY,
    name text NOT NULL,
    CONSTRAINT valid_name CHECK (valid_name(name))
);

COMMENT ON TABLE OCIRecipeName IS 'A name of an Open Container Initiative recipe.';
COMMENT ON COLUMN OCIRecipeName.name IS 'A lowercase name identifying an OCI recipe.';

CREATE INDEX ocirecipename__name__trgm ON OCIRecipeName
    USING gin (name trgm.gin_trgm_ops);

CREATE TABLE OCIRecipeTarget (
    id serial PRIMARY KEY,
    date_created timestamp without time zone DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC') NOT NULL,
    date_last_modified timestamp without time zone DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC') NOT NULL,
    registrant integer NOT NULL REFERENCES person,
    distribution integer NOT NULL REFERENCES distribution,
    ocirecipename integer NOT NULL REFERENCES ocirecipename,
    description text,
    bug_reporting_guidelines text,
    bug_reported_acknowledgement text,
    enable_bugfiling_duplicate_search boolean DEFAULT true NOT NULL
);

COMMENT ON TABLE OCIRecipeTarget IS 'A target (pillar and name) for Open Container Initiative recipes.';
COMMENT ON COLUMN OCIRecipeTarget.date_created IS 'The date on which this target was created in Launchpad.';
COMMENT ON COLUMN OCIRecipeTarget.date_last_modified IS 'The date on which this target was last modified in Launchpad.';
COMMENT ON COLUMN OCIRecipeTarget.registrant IS 'The user who registered this target.';
COMMENT ON COLUMN OCIRecipeTarget.distribution IS 'The distribution that this target belongs to.';
COMMENT ON COLUMN OCIRecipeTarget.ocirecipename IS 'The name of this target.';
COMMENT ON COLUMN OCIRecipeTarget.description IS 'A short description of this target.';
COMMENT ON COLUMN OCIRecipeTarget.bug_reporting_guidelines IS 'Guidelines to the end user for reporting bugs on this target';
COMMENT ON COLUMN OCIRecipeTarget.bug_reported_acknowledgement IS 'A message of acknowledgement to display to a bug reporter after they''ve reported a new bug.';
COMMENT ON COLUMN OCIRecipeTarget.enable_bugfiling_duplicate_search IS 'Enable/disable a search for possible duplicates when a bug is filed.';

CREATE UNIQUE INDEX ocirecipetarget__distribution__ocirecipename__key
    ON OCIRecipeTarget (distribution, ocirecipename)
    WHERE distribution IS NOT NULL;

CREATE TABLE OCIRecipeTargetSeries (
    id serial PRIMARY KEY,
    ocirecipetarget integer NOT NULL REFERENCES ocirecipetarget,
    name text NOT NULL,
    CONSTRAINT valid_name CHECK (valid_name(name))
);

COMMENT ON TABLE OCIRecipeTargetSeries IS 'A series of an Open Container Initiative recipe target, used to allow tracking bugs against multiple versions of images.';
COMMENT ON COLUMN OCIRecipeTargetSeries.ocirecipetarget IS 'The target that this series belongs to.';
COMMENT ON COLUMN OCIRecipeTargetSeries.name IS 'The name of this series.';

CREATE UNIQUE INDEX ocirecipetargetseries__ocirecipetarget__name__key
    ON OCIRecipeTargetSeries (ocirecipetarget, name);

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 08, 0);
