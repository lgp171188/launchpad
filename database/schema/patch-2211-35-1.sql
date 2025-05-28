-- Copyright 2025 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE bugpresence DROP COLUMN project;
ALTER TABLE bugpresence ADD COLUMN product integer REFERENCES product;

CREATE INDEX bugpresence__product__idx ON bugpresence (product);

COMMENT ON COLUMN bugpresence.product IS 'The product that this bug presence
 row is related to.';

INSERT INTO LaunchpadDatabaseRevision VALUES (2211, 35, 1);
