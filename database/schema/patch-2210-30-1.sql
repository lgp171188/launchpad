-- Copyright 2021 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

CREATE TABLE SnapBaseArch (
    snap_base integer NOT NULL REFERENCES snapbase,
    processor integer NOT NULL REFERENCES processor,
    PRIMARY KEY (snap_base, processor)
);

COMMENT ON TABLE SnapBaseArch IS 'The architectures that a snap base supports.';
COMMENT ON COLUMN SnapBaseArch.snap_base IS 'The snap base for which a supported architecture is specified.';
COMMENT ON COLUMN SnapBaseArch.processor IS 'A supported architecture for this snap base.';

-- Initialize with all possibilities for each corresponding distroseries,
-- preserving previous behaviour.
INSERT INTO SnapBaseArch (snap_base, processor)
    SELECT SnapBase.id, DistroArchSeries.processor
    FROM SnapBase, DistroArchSeries
    WHERE
        SnapBase.distro_series = DistroArchSeries.distroseries
        AND DistroArchSeries.enabled;

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 30, 1);
