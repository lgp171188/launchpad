-- Copyright 2022 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

-- Replaced by format-specific validation in BinaryPackageRelease.__init__.
ALTER TABLE BinaryPackageName DROP CONSTRAINT valid_name;

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 44, 3);
