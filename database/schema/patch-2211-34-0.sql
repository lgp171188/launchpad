-- Copyright 2025 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE vulnerability ADD COLUMN cvss jsonb;
COMMENT ON COLUMN vulnerability.cvss IS 'Product-level CVSS score';

INSERT INTO LaunchpadDatabaseRevision VALUES (2211, 34, 0);
