-- Copyright 2020 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

CREATE INDEX binarypackagerelease__binarypackagename__version_text__idx
    ON BinaryPackageRelease (binarypackagename, (version::text));
CREATE INDEX sourcepackagerelease__sourcepackagename__version_text__idx
    ON SourcePackageRelease (sourcepackagename, (version::text));

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 21, 0);
