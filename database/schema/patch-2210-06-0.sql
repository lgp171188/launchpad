-- Copyright 2019 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

CREATE TABLE OCIRecipeName (
    id serial PRIMARY KEY,
    name text NOT NULL,
    CONSTRAINT valid_name CHECK (valid_name(name))
);

CREATE INDEX ocirecipename__name__trgm ON OCIRecipeName
    USING gin (name trgm.gin_trgm_ops);

CREATE TABLE OCIRecipeTarget (
    id serial PRIMARY KEY,
    date_created timestamp without time zone DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC') NOT NULL,
    date_last_modified timestamp without time zone DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC') NOT NULL,
    registrant integer NOT NULL REFERENCES person,
    project integer REFERENCES product,
    distribution integer REFERENCES distribution,
    ocirecipename integer NOT NULL REFERENCES ocirecipename,
    description text,
    bug_supervisor integer REFERENCES person,
    bug_reporting_guidelines text,
    bug_reported_acknowledgement text,
    enable_bugfiling_duplicate_search boolean DEFAULT true NOT NULL,
    CONSTRAINT one_container CHECK ((project IS NULL) != (distribution IS NULL))
);

CREATE UNIQUE INDEX ocirecipetarget__project__ocirecipename__key
    ON OCIRecipeTarget (project, ocirecipename)
    WHERE project IS NOT NULL;
CREATE UNIQUE INDEX ocirecipetarget__distribution__ocirecipename__key
    ON OCIRecipeTarget (distribution, ocirecipename)
    WHERE distribution IS NOT NULL;

CREATE TABLE OCIRecipeTargetSeries (
    id serial PRIMARY KEY,
    ocirecipetarget integer NOT NULL REFERENCES ocirecipetarget,
    name text NOT NULL,
    CONSTRAINT valid_name CHECK (valid_name(name))
);

CREATE UNIQUE INDEX ocirecipetargetseries__ocirecipetarget__name__key
    ON OCIRecipeTargetSeries (ocirecipetarget, name);

ALTER TABLE BugTask
    ADD COLUMN ocirecipetarget integer REFERENCES ocirecipetarget,
    ADD COLUMN ocirecipetargetseries integer REFERENCES ocirecipetargetseries;
-- XXX fix bugtask_assignment_checks constraint
-- XXX fix bugtask_distinct_sourcepackage_assignment constraint
-- XXX look at bugtask_maintain_bugtaskflat_trig

CREATE INDEX bugtask__distribution__ocirt__ocirts__idx
    ON BugTask (distribution, ocirecipetarget, ocirecipetargetseries);
CREATE INDEX bugtask__product__ocirt__ocirts__idx
    ON BugTask (product, ocirecipetarget, ocirecipetargetseries);

ALTER TABLE BugTaskFlat
    ADD COLUMN ocirecipetarget integer,
    ADD COLUMN ocirecipetargetseries integer;

-- XXX alter bugtaskflat SPN indexes to check sourcepackagename not null
CREATE INDEX bugtaskflat__distribution__ocirt__bug__idx
    ON BugTaskFlat (distribution, ocirecipetarget, bug)
    WHERE
        distribution IS NOT NULL
        AND ocirecipetarget IS NOT NULL
        AND ocirecipetargetseries IS NULL;
CREATE INDEX bugtaskflat__distribution__ocirt__ocirts__bug__idx
    ON BugTaskFlat (distribution, ocirecipetarget, ocirecipetargetseries, bug)
    WHERE
        distribution IS NOT NULL
        AND ocirecipetarget IS NOT NULL
        AND ocirecipetargetseries IS NOT NULL;
CREATE INDEX bugtaskflat__product__ocirt__bug__idx
    ON BugTaskFlat (product, ocirecipetarget, bug)
    WHERE
        product IS NOT NULL
        AND ocirecipetarget IS NOT NULL
        AND ocirecipetargetseries IS NULL;
CREATE INDEX bugtaskflat__product__ocirt__ocirts__bug__idx
    ON BugTaskFlat (product, ocirecipetarget, ocirecipetargetseries, bug)
    WHERE
        product IS NOT NULL
        AND ocirecipetarget IS NOT NULL
        AND ocirecipetargetseries IS NOT NULL;

ALTER TABLE BugSummary
    ADD COLUMN ocirecipetarget integer REFERENCES ocirecipetarget,
    ADD COLUMN ocirecipetargetseries integer REFERENCES ocirecipetargetseries;

-- XXX check whether these indexes are right; do they need to contain other
-- denormalised columns?
CREATE INDEX bugsummary__ocirecipetarget__idx
    ON BugSummary (ocirecipetarget)
    WHERE ocirecipetarget IS NOT NULL;
CREATE INDEX bugsummary__ocirecipetargetseries__idx
    ON BugSummary (ocirecipetargetseries)
    WHERE ocirecipetargetseries IS NOT NULL;

-- XXX fix bugsummary_unique index
-- XXX alter bugsummary triggers

ALTER TABLE GitRepository
    ADD COLUMN ocirecipename integer REFERENCES ocirecipename,
    DROP CONSTRAINT one_container,
    ADD CONSTRAINT one_container CHECK (
        (project IS NULL OR distribution IS NULL)
        AND ((distribution IS NULL) =
             (sourcepackagename IS NULL or ocirecipename IS NULL))
        AND ((sourcepackagename IS NULL) != (ocirecipename IS NULL)));

-- XXX fix all the GitRepository indexes that need extra
-- sourcepackagename/ocirecipename checks
CREATE UNIQUE INDEX gitrepository__owner__distribution__ocirn__name__key
    ON GitRepository (owner, distribution, ocirecipename, name)
    WHERE distribution IS NOT NULL AND ocirecipename IS NOT NULL;
CREATE UNIQUE INDEX gitrepository__owner__project__ocirn__name__key
    ON GitRepository (owner, project, ocirecipename, name)
    WHERE project IS NOT NULL AND ocirecipename IS NOT NULL;
CREATE UNIQUE INDEX gitrepository__distribution__ocirn__target_default__key
    ON GitRepository (distribution, ocirecipename)
    WHERE
        distribution IS NOT NULL AND ocirecipename IS NOT NULL
        AND target_default;
CREATE UNIQUE INDEX gitrepository__project__ocirn__target_default__key
    ON GitRepository (project, ocirecipename)
    WHERE
        project IS NOT NULL AND ocirecipename IS NOT NULL
        AND target_default;
CREATE UNIQUE INDEX gitrepository__owner__distribution__ocirn__owner_default__key
    ON GitRepository (owner, distribution, ocirecipename)
    WHERE
        distribution IS NOT NULL AND ocirecipename IS NOT NULL
        AND owner_default;
CREATE UNIQUE INDEX gitrepository__owner__project__ocirn__owner_default__key
    ON GitRepository (owner, project, ocirecipename)
    WHERE
        project IS NOT NULL AND ocirecipename IS NOT NULL
        AND owner_default;
CREATE INDEX gitrepository__distribution__ocirn__date_last_modified__idx
    ON GitRepository (distribution, ocirecipename, date_last_modified)
    WHERE distribution IS NOT NULL AND ocirecipename IS NOT NULL;
CREATE INDEX gitrepository__project__ocirn__date_last_modified__idx
    ON GitRepository (project, ocirecipename, date_last_modified)
    WHERE project IS NOT NULL AND ocirecipename IS NOT NULL;
CREATE INDEX gitrepository__distribution__ocirn__id__idx
    ON GitRepository (distribution, ocirecipename, id)
    WHERE distribution IS NOT NULL AND ocirecipename IS NOT NULL;
CREATE INDEX gitrepository__project__ocirn__id__idx
    ON GitRepository (project, ocirecipename, id)
    WHERE project IS NOT NULL AND ocirecipename IS NOT NULL;

ALTER TABLE Karma
    ADD COLUMN ocirecipename integer REFERENCES ocirecipename;

ALTER TABLE KarmaCache
    ADD COLUMN ocirecipename integer REFERENCES ocirecipename,
    ADD CONSTRAINT ocirecipename_requires_distribution_or_product CHECK (
        ocirecipename IS NULL
        OR distribution IS NOT NULL OR product IS NOT NULL),
    ADD CONSTRAINT one_distribution_element CHECK (
        sourcepackagename IS NULL OR ocirecipename IS NULL);

-- XXX fix karmacache indexes

-- XXX oauthaccesstoken
-- XXX oauthrequesttoken

ALTER TABLE StructuralSubscription
    ADD COLUMN ocirecipename integer REFERENCES ocirecipename,
    ADD CONSTRAINT ocirecipename_requires_distribution_or_product CHECK (
        ocirecipename IS NULL
        OR distribution IS NOT NULL OR product IS NOT NULL),
    ADD CONSTRAINT one_distribution_element CHECK (
        sourcepackagename IS NULL OR ocirecipename IS NULL);

CREATE UNIQUE INDEX
    structuralsubscription__distribution__ocirecipename__subscriber__key
    ON StructuralSubscription (distribution, ocirecipename, subscriber)
    WHERE distribution IS NOT NULL AND sourcepackagename IS NOT NULL;

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 06, 0);
