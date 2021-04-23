-- Copyright 2021 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE Message
    ADD COLUMN date_deleted timestamp without time zone,
    ADD COLUMN date_last_edit timestamp without time zone;

CREATE TABLE MessageRevision (
    id serial PRIMARY KEY,
    message integer NOT NULL REFERENCES Message,
    content text,
    date_created timestamp without time zone,
    date_deleted timestamp without time zone
);

CREATE UNIQUE INDEX messagerevision__message__date_created__key
    ON MessageRevision(message, date_created);

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 31, 0);
