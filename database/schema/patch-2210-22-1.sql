-- Copyright 2020 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

-- Validate check constraint.
ALTER TABLE BugTask VALIDATE CONSTRAINT bugtask_assignment_checks;

ALTER TABLE BugSummary VALIDATE CONSTRAINT bugtask_assignment_checks;

-- BugTask indexes.
CREATE UNIQUE INDEX bugtask__ociproject__bug__key
    ON BugTask (ociproject, bug)
    WHERE ociproject IS NOT NULL;
CREATE UNIQUE INDEX bugtask__ociprojectseries__bug__key
    ON BugTask (ociprojectseries, bug)
    WHERE ociprojectseries IS NOT NULL;

-- BugTaskFlat indexes.
CREATE INDEX bugtaskflat__ociproject__bug__idx
    ON BugTaskFlat (ociproject, bug)
    WHERE ociproject IS NOT NULL;
CREATE INDEX bugtaskflat__ociproject__date_closed__bug__idx
    ON BugTaskFlat (ociproject, date_closed, bug DESC)
    WHERE ociproject IS NOT NULL;
CREATE INDEX bugtaskflat__ociproject__date_last_updated__idx
    ON BugTaskFlat (ociproject, date_last_updated)
    WHERE ociproject IS NOT NULL;
CREATE INDEX bugtaskflat__ociproject__datecreated__idx
    ON BugTaskFlat (ociproject, datecreated)
    WHERE ociproject IS NOT NULL;
CREATE INDEX bugtaskflat__ociproject__heat__bug__idx
    ON BugTaskFlat (ociproject, heat, bug DESC)
    WHERE ociproject IS NOT NULL;
CREATE INDEX bugtaskflat__ociproject__importance__bug__idx
    ON BugTaskFlat (ociproject, importance, bug DESC)
    WHERE ociproject IS NOT NULL;
CREATE INDEX bugtaskflat__ociproject__latest_patch_uploaded__bug__idx
    ON BugTaskFlat (ociproject, latest_patch_uploaded, bug DESC)
    WHERE ociproject IS NOT NULL;
CREATE INDEX bugtaskflat__ociproject__status__bug__idx
    ON BugTaskFlat (ociproject, status, bug DESC)
    WHERE ociproject IS NOT NULL;

CREATE INDEX bugtaskflat__ociprojectseries__bug__idx
    ON BugTaskFlat (ociprojectseries, bug)
    WHERE ociprojectseries IS NOT NULL;
CREATE INDEX bugtaskflat__ociprojectseries__date_closed__bug__idx
    ON BugTaskFlat (ociprojectseries, date_closed, bug DESC)
    WHERE ociprojectseries IS NOT NULL;
CREATE INDEX bugtaskflat__ociprojectseries__date_last_updated__idx
    ON BugTaskFlat (ociprojectseries, date_last_updated)
    WHERE ociprojectseries IS NOT NULL;
CREATE INDEX bugtaskflat__ociprojectseries__datecreated__idx
    ON BugTaskFlat (ociprojectseries, datecreated)
    WHERE ociprojectseries IS NOT NULL;
CREATE INDEX bugtaskflat__ociprojectseries__heat__bug__idx
    ON BugTaskFlat (ociprojectseries, heat, bug DESC)
    WHERE ociprojectseries IS NOT NULL;
CREATE INDEX bugtaskflat__ociprojectseries__importance__bug__idx
    ON BugTaskFlat (ociprojectseries, importance, bug DESC)
    WHERE ociprojectseries IS NOT NULL;
CREATE INDEX bugtaskflat__ociprojectseries__latest_patch_uploaded__bug__idx
    ON BugTaskFlat (ociprojectseries, latest_patch_uploaded, bug DESC)
    WHERE ociprojectseries IS NOT NULL;
CREATE INDEX bugtaskflat__ociprojectseries__status__bug__idx
    ON BugTaskFlat (ociprojectseries, status, bug DESC)
    WHERE ociprojectseries IS NOT NULL;


-- BugSummary indexes.
CREATE INDEX bugsummary__ociproject__idx
    ON BugSummary (ociproject)
    WHERE ociproject IS NOT NULL;
CREATE INDEX bugsummary__ociprojectseries__idx
    ON BugSummary (ociprojectseries)
    WHERE ociprojectseries IS NOT NULL;


-- Replacing previously renamed indexes.
CREATE UNIQUE INDEX bugtask_distinct_sourcepackage_assignment
    ON BugTask (
        bug,
        COALESCE(sourcepackagename, -1),
        COALESCE(distroseries, -1),
        COALESCE(distribution, -1)
    )
    WHERE
        product IS NULL
        AND productseries IS NULL
        AND ociproject IS NULL
        AND ociprojectseries IS NULL;
DROP INDEX old__bugtask_distinct_sourcepackage_assignment;


CREATE UNIQUE INDEX bugtask__product__bug__key
    ON BugTask (product, bug)
    WHERE
        product IS NOT NULL
        AND ociproject IS NULL
        AND ociprojectseries IS NULL;
DROP INDEX old__bugtask__product__bug__key;


CREATE UNIQUE INDEX bugsummary__unique
    ON BugSummary (
        COALESCE(product, -1),
        COALESCE(productseries, -1),
        COALESCE(distribution, -1),
        COALESCE(distroseries, -1),
        COALESCE(sourcepackagename, -1),
        COALESCE(ociproject, -1),
        COALESCE(ociprojectseries, -1),
        status,
        importance,
        has_patch,
        COALESCE(tag, ''::text),
        COALESCE(milestone, -1),
        COALESCE(viewed_by, -1),
        COALESCE(access_policy, -1)
    );
DROP INDEX old__bugsummary__unique;


CREATE INDEX bugsummaryjournal__full__idx
    ON BugSummaryJournal (
        status, product, productseries, distribution, distroseries,
        sourcepackagename, ociproject, ociprojectseries, viewed_by, milestone,
        tag
    );

DROP INDEX old__bugsummaryjournal__full__idx;


INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 22, 1);
