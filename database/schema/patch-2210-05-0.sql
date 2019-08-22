-- Copyright 2019 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

CREATE INDEX snap__git_repository_url__idx ON Snap (git_repository_url);
CREATE INDEX snap__store_name__idx ON Snap (store_name);

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 05, 0);
