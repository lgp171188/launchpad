-- Copyright 2020 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;


CREATE TABLE signingkey (
    id serial PRIMARY KEY,
    key_type integer NOT NULL,
    description text NULL,
    fingerprint text NOT NULL,
    public_key bytea NOT NULL,
    date_created timestamp without time zone NOT NULL
        DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC')
);


CREATE TABLE archivesigningkey (
    id serial PRIMARY KEY,
    archive integer NOT NULL REFERENCES archive,
    distro_series integer NULL REFERENCES distroseries,
    signing_key integer NOT NULL REFERENCES signingkey,
    date_created timestamp without time zone NOT NULL
        DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC')
);


CREATE INDEX archivesigningkey__archive__idx
    ON archivesigningkey(archive);

CREATE INDEX archivesigningkey__distro_series__idx
    ON archivesigningkey(distro_series);

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 12, 0);

