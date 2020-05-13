-- Copyright 2020 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE OCIProject ADD COLUMN project integer REFERENCES product;

ALTER TABLE OCIProject ALTER COLUMN distribution
    DROP NOT NULL,
    ADD CONSTRAINT one_container
        CHECK ((project IS NULL) != (distribution IS NULL));

COMMENT ON COLUMN OCIProject.project
    IS 'The project that this OCI project is associated with.';

CREATE INDEX ociproject__project__idx ON OCIProject (project);
CREATE UNIQUE INDEX ociproject__project__ociprojectname__key
    ON OCIProject (project, ociprojectname);

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 8, 8);
