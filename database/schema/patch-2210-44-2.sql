-- Copyright 2022 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

-- STEP 3, COLD

-- Replaced by binarypackagerelease__build__bpn__key.
ALTER TABLE BinaryPackageRelease
    DROP CONSTRAINT binarypackagerelease_build_name_uniq;

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 44, 2);
