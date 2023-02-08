-- Copyright 2023 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

-- Allow efficient queries of the state of a path at a given time.
CREATE INDEX archivefile__archive__date_created__date_superseded__path__idx
    ON ArchiveFile (archive, date_created, date_superseded, path)
    WHERE date_created IS NOT NULL;

-- Only one file may hold a given path at once.
CREATE UNIQUE INDEX archivefile__archive__path__date_superseded__key
    ON ArchiveFile (archive, path)
    WHERE date_superseded IS NULL;

INSERT INTO LaunchpadDatabaseRevision VALUES (2211, 15, 0);
