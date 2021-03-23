-- Copyright 2021 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE BugSubscriptionFilter
    ALTER COLUMN structuralsubscription SET NOT NULL;

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 27, 0);
