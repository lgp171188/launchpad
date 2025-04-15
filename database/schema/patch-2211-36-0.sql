-- Copyright 2025 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE bugattachment ADD COLUMN vulnerability_patches jsonb;
COMMENT ON COLUMN bugattachment.vulnerability_patches
    IS 'Information about the patches for the associated vulnerability.';

INSERT INTO LaunchpadDatabaseRevision VALUES (2211, 36, 0);
