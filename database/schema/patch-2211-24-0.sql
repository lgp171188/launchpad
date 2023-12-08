-- Copyright 2023 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE Snap 
    ALTER COLUMN pro_enable SET NOT NULL;

INSERT INTO LaunchpadDatabaseRevision VALUES (2211, 24, 0);
