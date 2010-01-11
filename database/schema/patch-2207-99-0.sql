-- Copyright 2009 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

-- The schema patch required for the Soyuz buildd generalisation, see
-- https://dev.launchpad.net/Soyuz/Specs/BuilddGeneralisation for details.
-- Bug #505725.

-- Changes needed to the `BuildQueue` table.

-- The 'processor' and the 'virtualized' columns will enable us to formulate
-- more straightforward queries for finding candidate jobs when builders
-- become idle.
ALTER TABLE ONLY buildqueue ADD COLUMN processor integer;
ALTER TABLE ONLY buildqueue ADD COLUMN virtualized boolean;

CREATE INDEX buildqueue__processor__virtualized__idx ON buildqueue USING btree (processor, virtualized) WHERE (processor IS NOT NULL);

INSERT INTO LaunchpadDatabaseRevision VALUES (2207, 99, 0);
