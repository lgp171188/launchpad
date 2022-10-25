-- Copyright 2022 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE BugAttachment
    ALTER COLUMN libraryfile drop not null,
    ADD COLUMN url text,
    ADD CONSTRAINT exactly_one_reference CHECK ((libraryfile IS NULL) != (url IS NULL))
;

COMMENT ON COLUMN BugAttachment.url
    IS 'External URL of the attachment.';

INSERT INTO LaunchpadDatabaseRevision VALUES (2211, 11, 0);
