-- Copyright 2021 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE Snap
    ADD COLUMN project INT,
    ADD CONSTRAINT snap__project__fk
        FOREIGN KEY (project) REFERENCES Product(id);

COMMENT ON COLUMN Snap.project IS 'The project which is the pillar for this Snap';

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 26, 1);
