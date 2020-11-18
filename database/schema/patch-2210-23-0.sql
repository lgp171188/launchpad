-- Copyright 2020 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE Distribution
    -- 0 == SERIES
    ADD COLUMN default_traversal_policy integer DEFAULT 0 NOT NULL,
    ADD COLUMN redirect_default_traversal boolean DEFAULT false NOT NULL;

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 23, 0);
