-- Copyright 2020 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

CREATE INDEX binarypackagereleasedownloadcount__index_only_scan__idx
    ON binarypackagereleasedownloadcount (
	archive, binary_package_release, day, country, count);

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 01, 4);
