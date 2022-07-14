-- Copyright 2020 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;


CREATE TABLE packageuploadlog (
    id serial PRIMARY KEY,
    package_upload integer NOT NULL REFERENCES packageupload,
    date_created timestamp without time zone NOT NULL
        DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC'),
    reviewer integer NOT NULL REFERENCES person,
    old_status integer NOT NULL,
    new_status integer NOT NULL,
    comment text
);

CREATE INDEX packageuploadlog__package_upload__date_created__idx
    ON packageuploadlog(package_upload, date_created);

CREATE INDEX packageuploadlog__reviewer__idx ON packageuploadlog(reviewer);


INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 11, 0);

