-- Copyright 2022 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE Cve
    DROP COLUMN discoverer;

INSERT INTO LaunchpadDatabaseRevision VALUES (2211, 09, 0);
