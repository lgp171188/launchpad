-- Copyright 2020 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

-- This patch can be applied "cold", in a "fast-downtime" way. It basically
-- adds the new OCI database columns, and rename current indexes so they can be
-- removed and replaced with new ones that includes the new columns.

ALTER TABLE BugTask
    ADD COLUMN ociproject integer REFERENCES ociproject,
    ADD COLUMN ociprojectseries integer REFERENCES ociprojectseries,
    DROP CONSTRAINT bugtask_assignment_checks,
    ADD CONSTRAINT bugtask_assignment_checks CHECK (
        CASE
            WHEN product IS NOT NULL THEN productseries IS NULL AND distribution IS NULL AND distroseries IS NULL AND sourcepackagename IS NULL AND ociproject IS NULL AND ociprojectseries IS NULL
            WHEN productseries IS NOT NULL THEN distribution IS NULL AND distroseries IS NULL AND sourcepackagename IS NULL AND ociproject IS NULL AND ociprojectseries IS NULL
            WHEN distribution IS NOT NULL THEN distroseries IS NULL AND ociproject IS NULL AND ociprojectseries IS NULL
            WHEN distroseries IS NOT NULL THEN ociproject IS NULL AND ociprojectseries IS NULL
            WHEN ociproject IS NOT NULL THEN ociprojectseries IS NULL
            WHEN ociprojectseries IS NOT NULL THEN true
            ELSE false
        END);

ALTER INDEX bugtask_distinct_sourcepackage_assignment
    RENAME TO old__bugtask_distinct_sourcepackage_assignment;

ALTER TABLE BugTaskFlat
    ADD COLUMN ociproject integer,
    ADD COLUMN ociprojectseries integer;

ALTER TABLE BugSummary
    ADD COLUMN ociproject integer REFERENCES ociproject,
    ADD COLUMN ociprojectseries integer REFERENCES ociprojectseries;

ALTER INDEX bugsummary__unique
    RENAME TO old__bugsummary__unique;

ALTER TABLE BugSummaryJournal
    ADD COLUMN ociproject integer,
    ADD COLUMN ociprojectseries integer;

-- Functions

CREATE OR REPLACE FUNCTION bugtask_maintain_bugtaskflat_trig()
    RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        PERFORM bugtask_flatten(NEW.id, FALSE);
    ELSIF TG_OP = 'UPDATE' THEN
        IF NEW.bug != OLD.bug THEN
            RAISE EXCEPTION 'cannot move bugtask to a different bug';
        ELSIF (NEW.product IS DISTINCT FROM OLD.product
            OR NEW.productseries IS DISTINCT FROM OLD.productseries) THEN
            -- product.active may differ. Do a full update.
            PERFORM bugtask_flatten(NEW.id, FALSE);
        ELSIF (
            NEW.datecreated IS DISTINCT FROM OLD.datecreated
            OR NEW.product IS DISTINCT FROM OLD.product
            OR NEW.productseries IS DISTINCT FROM OLD.productseries
            OR NEW.distribution IS DISTINCT FROM OLD.distribution
            OR NEW.distroseries IS DISTINCT FROM OLD.distroseries
            OR NEW.sourcepackagename IS DISTINCT FROM OLD.sourcepackagename
            OR NEW.ociproject IS DISTINCT FROM OLD.ociproject
            OR NEW.ociprojectseries IS DISTINCT FROM OLD.ociprojectseries
            OR NEW.status IS DISTINCT FROM OLD.status
            OR NEW.importance IS DISTINCT FROM OLD.importance
            OR NEW.assignee IS DISTINCT FROM OLD.assignee
            OR NEW.milestone IS DISTINCT FROM OLD.milestone
            OR NEW.owner IS DISTINCT FROM OLD.owner
            OR NEW.date_closed IS DISTINCT FROM OLD.date_closed) THEN
            -- Otherwise just update the columns from bugtask.
            -- Access policies and grants may have changed due to target
            -- transitions, but an earlier trigger will already have
            -- mirrored them to all relevant flat tasks.
            UPDATE BugTaskFlat SET
                datecreated = NEW.datecreated,
                product = NEW.product,
                productseries = NEW.productseries,
                distribution = NEW.distribution,
                distroseries = NEW.distroseries,
                sourcepackagename = NEW.sourcepackagename,
                ociproject = NEW.ociproject,
                ociprojectseries = NEW.ociprojectseries,
                status = NEW.status,
                importance = NEW.importance,
                assignee = NEW.assignee,
                milestone = NEW.milestone,
                owner = NEW.owner,
                date_closed = NEW.date_closed
                WHERE bugtask = NEW.id;
        END IF;
    ELSIF TG_OP = 'DELETE' THEN
        PERFORM bugtask_flatten(OLD.id, FALSE);
    END IF;
    RETURN NULL;
END;
$$;

DROP FUNCTION bugsummary_targets;
CREATE OR REPLACE FUNCTION bugsummary_targets(btf_row public.bugtaskflat)
    RETURNS TABLE(
        product integer,
        productseries integer,
        distribution integer,
        distroseries integer,
        sourcepackagename integer,
        ociproject integer,
        ociprojectseries integer
    )
    LANGUAGE sql IMMUTABLE
    AS $_$
    -- Include a sourcepackagename-free task if this one has a
    -- sourcepackagename, so package tasks are also counted in their
    -- distro/series.
    -- XXX what about pillar for ociprojects?
    SELECT
        $1.product, $1.productseries, $1.distribution,
        $1.distroseries, $1.sourcepackagename,
        $1.ociproject, $1.ociprojectseries
    UNION -- Implicit DISTINCT
    SELECT
        $1.product, $1.productseries, $1.distribution,
        $1.distroseries, NULL,
        $1.ociproject, $1.ociprojectseries;
$_$;

CREATE OR REPLACE FUNCTION bugsummary_locations(
        btf_row bugtaskflat, tags text[])
    RETURNS SETOF bugsummaryjournal
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF btf_row.duplicateof IS NOT NULL THEN
        RETURN;
    END IF;
    RETURN QUERY
        SELECT
            CAST(NULL AS integer) AS id,
            CAST(1 AS integer) AS count,
            bug_targets.product, bug_targets.productseries,
            bug_targets.distribution, bug_targets.distroseries,
            bug_targets.sourcepackagename,
            bug_viewers.viewed_by, bug_tags.tag, btf_row.status,
            btf_row.milestone, btf_row.importance,
            btf_row.latest_patch_uploaded IS NOT NULL AS has_patch,
            bug_viewers.access_policy,
            bug_targets.ociproject, bug_targets.ociprojectseries
        FROM
            bugsummary_targets(btf_row) AS bug_targets,
            unnest(tags) AS bug_tags (tag),
            bugsummary_viewers(btf_row) AS bug_viewers;
END;
$$;

CREATE OR REPLACE FUNCTION bugsummary_insert_journals(
        journals bugsummaryjournal[])
    RETURNS void
    LANGUAGE sql
    AS $$
    -- We sum the rows here to minimise the number of inserts into the
    -- journal, as in the case of UPDATE statement we may have -1s and +1s
    -- cancelling each other out.
    INSERT INTO BugSummaryJournal(
            count, product, productseries, distribution,
            distroseries, sourcepackagename, ociproject, ociprojectseries,
            viewed_by, tag, status, milestone, importance, has_patch,
            access_policy)
        SELECT
            SUM(count), product, productseries, distribution,
            distroseries, sourcepackagename, ociproject, ociprojectseries,
            viewed_by, tag, status, milestone, importance, has_patch,
            access_policy
        FROM unnest(journals)
        GROUP BY
            product, productseries, distribution,
            distroseries, sourcepackagename, ociproject, ociprojectseries,
            viewed_by, tag, status, milestone, importance, has_patch,
            access_policy
        HAVING SUM(count) != 0;
$$;

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 22, 0);
