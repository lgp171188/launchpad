-- Copyright 2022 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE SnapBase
    ADD COLUMN features jsonb;
;

COMMENT ON COLUMN SnapBase.features
    IS 'The features supported by this base.';

INSERT INTO LaunchpadDatabaseRevision VALUES (2211, 06, 0);
