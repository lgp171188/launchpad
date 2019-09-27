-- Copyright 2019 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

CREATE TABLE DistroArchSeriesFilter (
    id serial PRIMARY KEY,
    distroarchseries integer NOT NULL REFERENCES distroarchseries,
    packageset integer NOT NULL REFERENCES packageset,
    sense integer NOT NULL,
    creator integer NOT NULL REFERENCES person,
    date_created timestamp without time zone DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC') NOT NULL,
    date_last_modified timestamp without time zone DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC') NOT NULL,
    CONSTRAINT distroarchseriesfilter__distroarchseries__key UNIQUE (distroarchseries)
);

COMMENT ON TABLE DistroArchSeriesFilter IS 'A filter for packages to be included in or excluded from an architecture in a distro series.';
COMMENT ON COLUMN DistroArchSeriesFilter.distroarchseries IS 'The distro arch series that this filter is for.';
COMMENT ON COLUMN DistroArchSeriesFilter.packageset IS 'The package set to be included in or excluded from this distro arch series.';
COMMENT ON COLUMN DistroArchSeriesFilter.sense IS 'Whether the filter represents packages to include or exclude from the distro arch series.';
COMMENT ON COLUMN DistroArchSeriesFilter.creator IS 'The user who created this filter.';
COMMENT ON COLUMN DistroArchSeriesFilter.date_created IS 'The time when this filter was created.';
COMMENT ON COLUMN DistroArchSeriesFilter.date_last_modified IS 'The time when this filter was last modified.';

CREATE INDEX distroarchseriesfilter__packageset__idx
    ON DistroArchSeriesFilter (packageset);

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 07, 0);
