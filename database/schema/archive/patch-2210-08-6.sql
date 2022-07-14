-- Copyright 2019 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

CREATE TABLE OCIRegistryCredentials (
    id serial PRIMARY KEY,
    owner integer NOT NULL REFERENCES Person,
    url text NOT NULL,
    credentials jsonb NOT NULL
);

CREATE INDEX ociregistrycredentials__owner__idx
    ON OCIRegistryCredentials (owner);

COMMENT ON TABLE OCIRegistryCredentials IS 'Credentials for pushing to an OCI registry.';
COMMENT ON COLUMN OCIRegistryCredentials.owner IS 'The owner of these credentials.  Only the owner is entitled to create push rules using them.';
COMMENT ON COLUMN OCIRegistryCredentials.url IS 'The registry URL.';
COMMENT ON COLUMN OCIRegistryCredentials.credentials IS 'Encrypted credentials for pushing to the registry.';

CREATE TABLE OCIPushRule (
    id serial PRIMARY KEY,
    recipe integer NOT NULL REFERENCES OCIRecipe,
    registry_credentials integer NOT NULL REFERENCES OCIRegistryCredentials,
    image_name text NOT NULL
);

CREATE UNIQUE INDEX ocipushrule__recipe__registry_credentials__image_name__key
    ON OCIPushRule (recipe, registry_credentials, image_name);
CREATE INDEX ocipushrule__registry_credentials__idx
    ON OCIPushRule (registry_credentials);

COMMENT ON TABLE OCIPushRule IS 'A rule for pushing builds of an OCI recipe to a registry.';
COMMENT ON COLUMN OCIPushRule.recipe IS 'The recipe for which the rule is defined.';
COMMENT ON COLUMN OCIPushRule.registry_credentials IS 'The registry credentials to use.';
COMMENT ON COLUMN OCIPushRule.image_name IS 'The intended name of the image on the registry.';

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 08, 6);
