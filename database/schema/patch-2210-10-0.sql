-- Copyright 2019 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE Webhook ADD COLUMN livefs integer REFERENCES livefs;

ALTER TABLE Webhook DROP CONSTRAINT one_target;
ALTER TABLE Webhook ADD CONSTRAINT one_target CHECK (null_count(ARRAY[git_repository, branch, snap, livefs]) = 3);

CREATE INDEX webhook__livefs__id__idx
    ON webhook(livefs, id) WHERE livefs IS NOT NULL;

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 10, 0);
