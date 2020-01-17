-- Copyright 2019 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

CREATE INDEX binarypackagepublishinghistory__archive__bpr__idx
    ON binarypackagepublishinghistory (archive, binarypackagerelease);

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 01, 3);
