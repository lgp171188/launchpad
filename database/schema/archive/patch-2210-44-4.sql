-- Copyright 2022 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

CREATE UNIQUE INDEX binarypackagerelease__ci_build__bpn__format__key
    ON BinaryPackageRelease (ci_build, binarypackagename, binpackageformat)
    WHERE ci_build IS NOT NULL;
DROP INDEX binarypackagerelease__ci_build__bpn__key;

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 44, 4);
