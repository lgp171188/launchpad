-- Copyright 2023 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE AccessToken
    ADD COLUMN project integer REFERENCES product;

COMMENT ON COLUMN AccessToken.project IS 'The project for which the token was issued.';

CREATE INDEX accesstoken__project__idx ON AccessToken (project);

-- There can only be either a git_repository or a project as target
ALTER TABLE AccessToken
    ALTER COLUMN git_repository DROP NOT NULL,
    ADD CONSTRAINT one_target CHECK (
        (public.null_count(ARRAY[git_repository, project]) = 1)
    );

INSERT INTO LaunchpadDatabaseRevision VALUES (2211, 22, 0);
