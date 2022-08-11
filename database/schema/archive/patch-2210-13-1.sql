-- Copyright 2020 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

CREATE INDEX sourcepackagepublishinghistory__archive__status__datepublished__idx
    ON SourcePackagePublishingHistory (archive, status)
    WHERE datepublished IS NULL;
CREATE INDEX binarypackagepublishinghistory__archive__status__datepublished__idx
    ON BinaryPackagePublishingHistory (archive, status)
    WHERE datepublished IS NULL;

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 13, 1);
