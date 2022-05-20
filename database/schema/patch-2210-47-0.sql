-- Copyright 2022 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE Distribution
    ADD COLUMN security_admin integer REFERENCES Person;

COMMENT ON COLUMN Distribution.security_admin IS 'The person or team responsible for managing security vulnerabilities in this distribution.';

CREATE INDEX distribution__security_admin__idx
    ON distribution (security_admin);

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 47, 0);
