SET client_min_messages=ERROR;

ALTER TABLE Branch
  ADD COLUMN date_last_modified TIMESTAMP WITHOUT TIME ZONE;

/*
The date_last_modified for a branch is the maximum of the
revision_date of the tip revision or the date created.
*/

UPDATE Branch
SET date_last_modified = date_created;

UPDATE Branch
SET date_last_modified = Revision.revision_date
FROM Revision
WHERE Branch.last_scanned_id = Revision.revision_id
AND Revision.revision_date > Branch.date_last_modified;

ALTER TABLE Branch
  ALTER COLUMN date_last_modified SET NOT NULL,
  ALTER COLUMN date_last_modified SET DEFAULT timezone('UTC'::text, now());

INSERT INTO LaunchpadDatabaseRevision VALUES (87, 93, 0);

