-- Copyright 2021 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE Distribution
    ADD COLUMN oci_credentials INTEGER REFERENCES OCIRegistryCredentials;

COMMENT ON COLUMN Distribution.oci_credentials IS 'Credentials and URL to use for uploading all OCI Images in this distribution to a registry.';

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 24, 0);
