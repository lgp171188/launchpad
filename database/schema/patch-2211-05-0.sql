-- Copyright 2022 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE BinaryPackagePublishingHistory
    ADD COLUMN sourcepackagename integer REFERENCES SourcePackageName;

COMMENT ON COLUMN BinaryPackagePublishingHistory.sourcepackagename
    IS 'The name of the source package that built this binary.';

INSERT INTO LaunchpadDatabaseRevision VALUES (2211, 05, 0);
