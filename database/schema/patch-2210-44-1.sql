-- Copyright 2022 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

-- STEP 2, HOT

CREATE INDEX sourcepackagerelease__ci_build__idx
    ON SourcePackageRelease (ci_build);

ALTER TABLE SourcePackageRelease
    VALIDATE CONSTRAINT at_most_one_build,
    VALIDATE CONSTRAINT debian_columns;

ALTER TABLE SourcePackagePublishingHistory
    VALIDATE CONSTRAINT debian_columns,
    VALIDATE CONSTRAINT no_debian_channel;

CREATE UNIQUE INDEX binarypackagerelease__build__bpn__key
    ON BinaryPackageRelease (build, binarypackagename)
    WHERE build IS NOT NULL;
CREATE UNIQUE INDEX binarypackagerelease__ci_build__bpn__key
    ON BinaryPackageRelease (ci_build, binarypackagename)
    WHERE ci_build IS NOT NULL;
CREATE INDEX binarypackagerelease__ci_build__idx
    ON BinaryPackageRelease (ci_build);

ALTER TABLE BinaryPackageRelease
    VALIDATE CONSTRAINT one_build,
    VALIDATE CONSTRAINT debian_columns;

ALTER TABLE BinaryPackagePublishingHistory
    VALIDATE CONSTRAINT debian_columns,
    VALIDATE CONSTRAINT no_debian_channel;

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 44, 1);
