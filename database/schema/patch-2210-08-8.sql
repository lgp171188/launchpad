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
    ON OCIProject (project, ociprojectname) WHERE project IS NOT NULL;


-- Alter GitRepository table to allow ociprojectname + project
ALTER TABLE GitRepository
    DROP CONSTRAINT one_container,
    ADD CONSTRAINT one_container CHECK (
        -- Project
        (project IS NOT NULL AND distribution IS NULL AND sourcepackagename IS NULL AND ociprojectname IS NULL) OR
        -- Distribution source package
        (project IS NULL AND distribution IS NOT NULL AND sourcepackagename IS NOT NULL AND ociprojectname IS NULL) OR
        -- Distribution OCI project
        (project IS NULL AND distribution IS NOT NULL AND sourcepackagename IS NULL AND ociprojectname IS NOT NULL) OR
        -- Project OCI project
        (project IS NOT NULL AND distribution IS NULL AND sourcepackagename IS NULL AND ociprojectname IS NOT NULL) OR
        -- Personal
        (project IS NULL AND distribution IS NULL AND sourcepackagename IS NULL AND ociprojectname IS NULL));

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 8, 8);
