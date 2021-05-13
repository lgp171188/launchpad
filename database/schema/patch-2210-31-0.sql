-- Copyright 2021 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE Message
    ADD COLUMN date_deleted timestamp without time zone,
    ADD COLUMN date_last_edited timestamp without time zone;

CREATE TABLE MessageRevision (
    id serial PRIMARY KEY,
    message integer NOT NULL REFERENCES Message,
    subject text,
    revision integer NOT NULL,
    date_created timestamp without time zone NOT NULL,
    date_deleted timestamp without time zone
) WITH (fillfactor='100');

CREATE UNIQUE INDEX messagerevision__message__revision__key
    ON MessageRevision(message, revision);

COMMENT ON TABLE MessageRevision IS 'Old versions of an edited Message';
COMMENT ON COLUMN MessageRevision.message
    IS 'The current message of this revision';
COMMENT ON COLUMN MessageRevision.revision
    IS 'The revision monotonic increasing number';
COMMENT ON COLUMN MessageRevision.date_created
    IS 'When the original message was edited and created this revision';
COMMENT ON COLUMN MessageRevision.date_deleted
    IS 'If this revision was deleted, when did that happen';


CREATE TABLE MessageRevisionChunk (
    id serial PRIMARY KEY,
    messagerevision integer NOT NULL REFERENCES MessageRevision,
    sequence integer NOT NULL,
    content text NOT NULL
) WITH (fillfactor='100');

COMMENT ON TABLE MessageRevisionChunk
    IS 'Old chunks of a message when a revision was created for it';
COMMENT ON COLUMN MessageRevisionChunk.sequence
    IS 'Order of this particular chunk';
COMMENT ON COLUMN MessageRevisionChunk.content
    IS 'Text content for this chunk of the message.';

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 31, 0);
