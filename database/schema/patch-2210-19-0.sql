
-- Copyright 2020 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE Archive DROP COLUMN signing_key;
ALTER TABLE PackageUpload DROP COLUMN signing_key;
ALTER TABLE Revision DROP COLUMN gpgkey;
ALTER TABLE SignedCodeOfConduct DROP COLUMN signingkey;
ALTER TABLE SourcePackageRelease DROP COLUMN dscsigningkey;

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 19, 0);
