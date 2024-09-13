-- Copyright 2024 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

CREATE TABLE RockBase (
    id serial PRIMARY KEY,
    date_created timestamp without time zone DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC') NOT NULL,
    registrant integer NOT NULL REFERENCES person,
    distro_series integer NOT NULL REFERENCES distroseries,
    build_channels text NOT NULL
);

CREATE INDEX rockbase__registrant__idx ON RockBase (registrant);
CREATE UNIQUE INDEX rockbase__distro_series__key ON RockBase (distro_series);

COMMENT ON TABLE RockBase IS 'A base for rocks.';
COMMENT ON COLUMN RockBase.date_created IS 'The date on which this base was created in Launchpad.';
COMMENT ON COLUMN RockBase.registrant IS 'The user who registered this base.';
COMMENT ON COLUMN RockBase.distro_series IS 'The distro series for this base.';
COMMENT ON COLUMN RockBase.build_channels IS 'A dictionary mapping snap names to channels to use when building rock recipes that specify this base.';

CREATE TABLE RockBaseArch (
    rock_base integer NOT NULL REFERENCES rockbase,
    processor integer NOT NULL REFERENCES processor,
    PRIMARY KEY (rock_base, processor)
);

COMMENT ON TABLE RockBaseArch IS 'The architectures that a rock base supports.';
COMMENT ON COLUMN RockBaseArch.rock_base IS 'The rock base for which a supported architecture is specified.';
COMMENT ON COLUMN RockBaseArch.processor IS 'A supported architecture for this rock base.';

INSERT INTO LaunchpadDatabaseRevision VALUES (2211, 28, 1);
