-- Copyright 2020 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE OCIProject ADD COLUMN product integer REFERENCES product;

COMMENT ON COLUMN OCIProject.product
    IS 'The project that this OCI project is associated with.';

CREATE INDEX ociproject__product__idx ON OCIProject (product);

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 16, 0);
