-- Copyright 2025 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE bugattachment VALIDATE CONSTRAINT exactly_one_reference;

INSERT INTO LaunchpadDatabaseRevision VALUES (2211, 38, 1);
