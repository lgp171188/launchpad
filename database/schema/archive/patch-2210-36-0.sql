-- Copyright 2021 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

CREATE TABLE AccessToken (
    id serial PRIMARY KEY,
    date_created timestamp without time zone DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC') NOT NULL,
    token_sha256 text NOT NULL,
    owner integer NOT NULL REFERENCES person,
    description text NOT NULL,
    git_repository integer REFERENCES gitrepository NOT NULL,
    scopes jsonb NOT NULL,
    date_last_used timestamp without time zone,
    date_expires timestamp without time zone,
    revoked_by integer REFERENCES person
);

COMMENT ON TABLE AccessToken IS 'A personal access token for the webservice API.';
COMMENT ON COLUMN AccessToken.date_created IS 'When the token was created.';
COMMENT ON COLUMN AccessToken.token_sha256 IS 'SHA-256 hash of the secret token.';
COMMENT ON COLUMN AccessToken.owner IS 'The person who created the token.';
COMMENT ON COLUMN AccessToken.description IS 'A short description of the token''s purpose.';
COMMENT ON COLUMN AccessToken.git_repository IS 'The Git repository for which the token was issued.';
COMMENT ON COLUMN AccessToken.scopes IS 'A list of scopes granted by the token.';
COMMENT ON COLUMN AccessToken.date_last_used IS 'When the token was last used.';
COMMENT ON COLUMN AccessToken.date_expires IS 'When the token should expire or was revoked.';
COMMENT ON COLUMN AccessToken.revoked_by IS 'The person who revoked the token, if any.';

CREATE UNIQUE INDEX accesstoken__token_sha256__key
    ON AccessToken (token_sha256);
CREATE INDEX accesstoken__owner__idx
    ON AccessToken (owner);
CREATE INDEX accesstoken__git_repository__idx
    ON AccessToken (git_repository);
CREATE INDEX accesstoken__date_expires__idx
    ON AccessToken (date_expires)
    WHERE date_expires IS NOT NULL;
CREATE INDEX accesstoken__revoked_by__idx
    ON AccessToken (revoked_by);

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 36, 0);
