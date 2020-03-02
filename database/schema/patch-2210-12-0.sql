-- Copyright 2020 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;


CREATE TABLE signingkey (
    id serial PRIMARY KEY,
    key_type integer NOT NULL,
    description text,
    fingerprint text NOT NULL,
    public_key bytea NOT NULL,
    date_created timestamp without time zone NOT NULL
        DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC'),

    -- This unique constraint is needed because ArchiveSigningKey has a
    -- compound foreign key using both columns.
    CONSTRAINT signingkey__id__key_type__key
        UNIQUE(id, key_type),

    CONSTRAINT signingkey__key_type__fingerprint__key
        UNIQUE (key_type, fingerprint)
);


CREATE TABLE archivesigningkey (
    id serial PRIMARY KEY,
    archive integer NOT NULL REFERENCES archive,
    earliest_distro_series integer REFERENCES distroseries,
    key_type integer NOT NULL,
    signing_key integer NOT NULL,
    date_created timestamp without time zone NOT NULL
        DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC'),

    CONSTRAINT archivesigningkey__signing_key__fk
        FOREIGN KEY (signing_key, key_type)
        REFERENCES signingkey (id, key_type),

    CONSTRAINT archivesigningkey__archive__key_type__earliest_distro_series__key
        UNIQUE(archive, key_type, earliest_distro_series)
);


INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 12, 0);

