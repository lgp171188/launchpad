-- Copyright 2009 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE BugTask
ADD COLUMN date_milestone_set TIMESTAMP WITHOUT TIME ZONE;

CREATE TRIGGER set_bugtask_date_milestone_set_t
    AFTER INSERT OR UPDATE ON BugTask
    FOR EACH ROW
    EXECUTE PROCEDURE set_bugtask_date_milestone_set();


INSERT INTO LaunchpadDatabaseRevision VALUES (2109, 32, 0);
