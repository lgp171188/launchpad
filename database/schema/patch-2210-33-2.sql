-- Copyright 2021 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

CREATE TABLE CharmBase (
    id serial PRIMARY KEY,
    date_created timestamp without time zone DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC') NOT NULL,
    registrant integer NOT NULL REFERENCES person,
    distro_series integer NOT NULL REFERENCES distroseries,
    build_snap_channels text NOT NULL
);

CREATE INDEX charmbase__registrant__idx ON CharmBase (registrant);
CREATE UNIQUE INDEX charmbase__distro_series__key ON CharmBase (distro_series);

COMMENT ON TABLE CharmBase IS 'A base for charms.';
COMMENT ON COLUMN CharmBase.date_created IS 'The date on which this base was created in Launchpad.';
COMMENT ON COLUMN CharmBase.registrant IS 'The user who registered this base.';
COMMENT ON COLUMN CharmBase.distro_series IS 'The distro series for this base.';
COMMENT ON COLUMN CharmBase.build_snap_channels IS 'A dictionary mapping snap names to channels to use when building charm recipes that specify this base.';

CREATE TABLE CharmBaseArch (
    charm_base integer NOT NULL REFERENCES charmbase,
    processor integer NOT NULL REFERENCES processor,
    PRIMARY KEY (charm_base, processor)
);

COMMENT ON TABLE CharmBaseArch IS 'The architectures that a charm base supports.';
COMMENT ON COLUMN CharmBaseArch.charm_base IS 'The charm base for which a supported architecture is specified.';
COMMENT ON COLUMN CharmBaseArch.processor IS 'A supported architecture for this charm base.';

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 33, 2);
