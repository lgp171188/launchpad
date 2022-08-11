-- Copyright 2022 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE BugTask
    ADD COLUMN status_explanation text,
    ADD COLUMN importance_explanation text;

COMMENT ON COLUMN BugTask.status_explanation IS 'An optional explanation for the current status of this bugtask.';

COMMENT ON COLUMN BugTask.importance_explanation IS 'An optional explanation for the current importance of this bugtask.';

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 45, 0);
