-- Copyright 2009 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

ALTER TABLE Archive
    ADD COLUMN build_debug_symbols boolean
    DEFAULT false;

INSERT INTO LaunchpadDatabaseRevision VALUES (2207, 99, 0);
