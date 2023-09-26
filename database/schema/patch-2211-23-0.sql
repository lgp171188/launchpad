-- Copyright 2023 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE Snap ADD COLUMN pro_enable boolean;

COMMENT ON COLUMN Snap.pro_enable IS 'Whether the use of private archive dependencies of the base is allowed.';

INSERT INTO LaunchpadDatabaseRevision VALUES (2211, 23, 0);
