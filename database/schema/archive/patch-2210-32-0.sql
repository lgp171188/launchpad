-- Copyright 2021 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

-- Archive.buildd_secret is no longer used.
ALTER TABLE Archive DROP CONSTRAINT valid_buildd_secret;

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 32, 0);
