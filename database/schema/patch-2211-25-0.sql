-- Copyright 2023 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

CREATE TABLE SocialAccount (
    id serial PRIMARY KEY,
    person integer REFERENCES Person NOT NULL,
    platform integer NOT NULL,
    identifier jsonb NOT NULL
);

COMMENT ON COLUMN SocialAccount.person IS 'Person the social media account belongs to.';
COMMENT ON COLUMN SocialAccount.platform IS 'Social media platform.';
COMMENT ON COLUMN SocialAccount.identifier IS 'Identifier for the social media account (JSON format specific per social media platform).';

CREATE INDEX socialaccount__person__idx ON SocialAccount (person);
CREATE INDEX socialaccount__platform__idx ON SocialAccount (platform);

INSERT INTO LaunchpadDatabaseRevision VALUES (2211, 25, 0);
