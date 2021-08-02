-- Copyright 2021 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE signedcodeofconduct
    ADD COLUMN affirmed boolean;
ALTER TABLE signedcodeofconduct
    ADD COLUMN version text;

COMMENT ON COLUMN signedcodeofconduct.affirmed IS 'Code of conduct was affirmed via website interaction.';

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 34, 0);
