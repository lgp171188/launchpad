-- Copyright 2020 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE distribution
    ADD COLUMN oci_project_admin integer REFERENCES person;

COMMENT ON COLUMN distribution.oci_project_admin
    IS 'Person or team with privileges to manage OCI Projects.';

CREATE INDEX distribution__oci_project_admin__idx
    ON distribution (oci_project_admin);

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 14, 0);
