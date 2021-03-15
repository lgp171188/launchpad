-- Copyright 2021 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

CREATE INDEX gitrepository__loose_object_count__pack_count__idx
ON GitRepository(loose_object_count, pack_count)
WHERE status = 2;

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 28, 0);
