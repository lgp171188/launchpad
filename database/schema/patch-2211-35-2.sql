-- Copyright 2025 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

-- drop sourcepackageseries empty table since we will not use it
DROP TABLE IF EXISTS sourcepackageseries;

INSERT INTO LaunchpadDatabaseRevision VALUES (2211, 35, 2);
