-- Copyright 2022 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

-- STEP 1, COLD

ALTER TABLE Archive
    ADD COLUMN publishing_method integer,
    ADD COLUMN repository_format integer;

ALTER TABLE SourcePackageRelease
    ADD COLUMN ci_build integer REFERENCES CIBuild,
    ADD CONSTRAINT at_most_one_build
        CHECK (null_count(ARRAY[sourcepackage_recipe_build, ci_build]) >= 1)
        NOT VALID,
    ALTER COLUMN component DROP NOT NULL,
    ALTER COLUMN section DROP NOT NULL,
    ALTER COLUMN urgency DROP NOT NULL,
    ALTER COLUMN dsc_format DROP NOT NULL,
    ADD CONSTRAINT debian_columns
        CHECK (
            -- 1 == DPKG
            format != 1
            OR (component IS NOT NULL
                AND section IS NOT NULL
                AND urgency IS NOT NULL
                AND dsc_format IS NOT NULL))
        NOT VALID,
    -- This is always non-NULL for Debian-format source packages, but it's
    -- not particularly important to constrain this at the DB level.
    ALTER COLUMN maintainer DROP NOT NULL;

ALTER TABLE SourcePackagePublishingHistory
    ADD COLUMN format integer,
    ALTER COLUMN component DROP NOT NULL,
    ALTER COLUMN section DROP NOT NULL,
    ADD CONSTRAINT debian_columns CHECK (
        -- 1 == DPKG
        COALESCE(format, 1) != 1
        OR (component IS NOT NULL
            AND section IS NOT NULL)) NOT VALID,
    ADD COLUMN channel jsonb,
    ADD CONSTRAINT no_debian_channel CHECK (
        -- 1 == DPKG
        COALESCE(format, 1) != 1
        OR channel IS NULL) NOT VALID;

ALTER TABLE BinaryPackageRelease
    ADD COLUMN ci_build integer REFERENCES CIBuild,
    ALTER COLUMN build DROP NOT NULL,
    ADD CONSTRAINT one_build
        CHECK (null_count(ARRAY[build, ci_build]) = 1)
        NOT VALID,
    ALTER COLUMN component DROP NOT NULL,
    ALTER COLUMN section DROP NOT NULL,
    ALTER COLUMN priority DROP NOT NULL,
    ADD CONSTRAINT debian_columns
        CHECK (
            -- 1 == DEB, 2 == UDEB, 5 == DDEB
            binpackageformat NOT IN (1, 2, 5)
            OR (component IS NOT NULL
                AND section IS NOT NULL
                AND priority IS NOT NULL))
        NOT VALID;

ALTER TABLE BinaryPackagePublishingHistory
    ADD COLUMN binarypackageformat integer,
    ALTER COLUMN component DROP NOT NULL,
    ALTER COLUMN section DROP NOT NULL,
    ALTER COLUMN priority DROP NOT NULL,
    ADD CONSTRAINT debian_columns
        CHECK (
            (binarypackageformat IS NOT NULL
                -- 1 == DEB, 2 == UDEB, 5 == DDEB
                AND binarypackageformat NOT IN (1, 2, 5))
            OR (component IS NOT NULL
                AND section IS NOT NULL
                AND priority IS NOT NULL))
        NOT VALID,
    ADD COLUMN channel jsonb,
    ADD CONSTRAINT no_debian_channel CHECK (
        (binarypackageformat IS NOT NULL
            -- 1 == DEB, 2 == UDEB, 5 == DDEB
            AND binarypackageformat NOT IN (1, 2, 5))
        OR channel IS NULL) NOT VALID;


-- Subsequent statements, to be executed live and in subsequent patches.

/*
-- STEP 2, HOT

CREATE INDEX sourcepackagerelease__ci_build__idx
    ON SourcePackageRelease (ci_build);

ALTER TABLE SourcePackageRelease
    VALIDATE CONSTRAINT at_most_one_build,
    VALIDATE CONSTRAINT debian_columns;

CREATE INDEX sourcepackagepublishinghistory__channel__idx
    ON SourcePackagePublishingHistory (channel);

ALTER TABLE SourcePackagePublishingHistory
    VALIDATE CONSTRAINT debian_columns,
    VALIDATE CONSTRAINT no_debian_channel;

CREATE UNIQUE INDEX binarypackagerelease__bpn__build__version__key
    ON BinaryPackageRelease (
        binarypackagename, COALESCE(build, ci_build), version);
CREATE UNIQUE INDEX binarypackagerelease__build__bpn__key
    ON BinaryPackageRelease (COALESCE(build, ci_build), binarypackagename);
CREATE INDEX binarypackagerelease__ci_build__idx
    ON BinaryPackageRelease (ci_build);

ALTER TABLE BinaryPackageRelease
    VALIDATE CONSTRAINT one_build,
    VALIDATE CONSTRAINT debian_columns;

CREATE INDEX binarypackagepublishinghistory__channel__idx
    ON BinaryPackagePublishingHistory (channel);

ALTER TABLE BinaryPackagePublishingHistory
    VALIDATE CONSTRAINT debian_columns,
    VALIDATE CONSTRAINT no_debian_channel;


-- STEP 3, COLD

-- Replaced by binarypackagerelease__bpn__build__version__key and
-- binarypackagerelease__build__bpn__key respectively.
ALTER TABLE BinaryPackageRelease
    DROP CONSTRAINT binarypackagerelease_binarypackagename_key,
    DROP CONSTRAINT binarypackagerelease_build_name_uniq;
*/

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 44, 0);
