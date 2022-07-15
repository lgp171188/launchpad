-- Copyright 2020 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

CREATE TABLE BinarySourceReference (
    id serial PRIMARY KEY,
    binary_package_release integer NOT NULL REFERENCES binarypackagerelease,
    source_package_release integer NOT NULL REFERENCES sourcepackagerelease,
    reference_type integer NOT NULL
);

COMMENT ON TABLE BinarySourceReference IS 'A reference from a binary package release to a source package release.';
COMMENT ON COLUMN BinarySourceReference.binary_package_release IS 'The referencing binary package release.';
COMMENT ON COLUMN BinarySourceReference.source_package_release IS 'The referenced source package release.';
COMMENT ON COLUMN BinarySourceReference.reference_type IS 'The type of the reference.';

CREATE INDEX binarysourcereference__bpr__type__idx
    ON BinarySourceReference (binary_package_release, reference_type);
CREATE INDEX binarysourcereference__spr__type__idx
    ON BinarySourceReference (source_package_release, reference_type);
CREATE UNIQUE INDEX binarysourcereference__bpr__spr__type__key
    ON BinarySourceReference (binary_package_release, source_package_release, reference_type);

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 13, 0);
