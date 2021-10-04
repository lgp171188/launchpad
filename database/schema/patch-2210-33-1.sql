-- Copyright 2021 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

CREATE INDEX snap__is_stale__auto_build__idx
    ON Snap(is_stale, auto_build);
CREATE INDEX charmrecipe__is_stale__auto_build__idx
    ON CharmRecipe(is_stale, auto_build);

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 33, 1);
