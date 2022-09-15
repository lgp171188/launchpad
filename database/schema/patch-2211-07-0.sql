-- Copyright 2022 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE Cve
    ADD COLUMN discovered_by text;

COMMENT ON COLUMN Cve.discovered_by
    IS 'The name of person(s) or organization that discovered the CVE';

INSERT INTO LaunchpadDatabaseRevision VALUES (2211, 07, 0);
