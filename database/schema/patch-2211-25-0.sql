-- Copyright 2023 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

CREATE TABLE SocialAccounts (
    id serial PRIMARY KEY,
    person integer REFERENCES Person NOT NULL,
    platform integer NOT NULL,
    identifier jsonb NOT NULL
);

COMMENT ON COLUMN SocialAccounts.person IS 'Person the social media account belongs to.';
COMMENT ON COLUMN SocialAccounts.platform IS 'Social media platform.';
COMMENT ON COLUMN SocialAccounts.identifier IS 'Identifier for the social media account (JSON format specific per social media platform).';

INSERT INTO LaunchpadDatabaseRevision VALUES (2211, 25, 0);
