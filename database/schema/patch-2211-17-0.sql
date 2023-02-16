-- Copyright 2023 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE Distribution
    ADD COLUMN code_admin integer REFERENCES Person;

COMMENT ON COLUMN Distribution.code_admin IS 'The person or team responsible for managing the source code for packages in this distribution.';

CREATE INDEX distribution__code_admin__idx
    ON distribution (code_admin);

INSERT INTO LaunchpadDatabaseRevision VALUES (2211, 17, 0);
