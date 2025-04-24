-- Copyright 2025 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE bugtask
    ADD COLUMN date_deferred timestamp without time zone;

COMMENT ON COLUMN bugtask.date_deferred
    IS 'The date when this bug task transitioned to the DEFERRED status.';

-- indexing bugtask.date_deferred in a hot patch

INSERT INTO LaunchpadDatabaseRevision VALUES (2211, 37, 0);
