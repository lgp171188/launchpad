-- Copyright 2025 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE bugattachment DROP CONSTRAINT exactly_one_reference;

ALTER TABLE bugattachment ADD CONSTRAINT exactly_one_reference CHECK (
    ((libraryfile IS NOT NULL)::int +
     (url IS NOT NULL)::int +
     (vulnerability_patches IS NOT NULL)::int) = 1
) NOT VALID;

INSERT INTO LaunchpadDatabaseRevision VALUES (2211, 38, 0);
