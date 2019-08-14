-- Copyright 2019 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

-- Rewrite the BugSummaryJournal maintenance triggers to make use of the new
-- transition tables provided to AFTER ... FOR EACH STATEMENT triggers as of
-- PostgreSQL 10.  Instead of using row-level triggers which accumulate
-- changes in a temporary table and flush it into the journal, we now write
-- directly to the journal at the end of each statement.

DROP TRIGGER bugtaskflat_maintain_bug_summary ON bugtaskflat;
DROP TRIGGER bugtag_maintain_bug_summary_before_trigger ON bugtag;
DROP TRIGGER bugtag_maintain_bug_summary_after_trigger ON bugtag;

-- Similar to the previous bugsummary_tags, but returns an array of tags on
-- the given bug plus NULL; this can be passed to other functions, and is
-- suitable for constructing a set of rows to insert into BugSummaryJournal
-- when handling changes to BugTaskFlat.
CREATE OR REPLACE FUNCTION bugsummary_tag_names(bug integer)
    RETURNS text[]
    LANGUAGE sql STABLE
    AS $_$
    SELECT array_agg(tag)
    FROM (
        SELECT BugTag.tag FROM BugTag WHERE BugTag.bug = $1
        UNION ALL
        SELECT NULL::text
    ) AS tag;
$_$;

COMMENT ON FUNCTION bugsummary_tag_names IS
    'Return an array of the tag names on the given bug, plus NULL; this is suitable for constructing BugSummaryJournal rows when handling changes to BugTaskFlat.';

-- Modify the existing bugsummary_locations to accept an array of tags
-- rather than looking them up for itself.
DROP FUNCTION bugsummary_locations;
CREATE FUNCTION bugsummary_locations(btf_row bugtaskflat, tags text[])
    RETURNS SETOF bugsummary
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
            bug_viewers.access_policy
        FROM
            bugsummary_targets(btf_row) AS bug_targets,
            unnest(tags) AS bug_tags (tag),
            bugsummary_viewers(btf_row) AS bug_viewers;
END;
$$;

-- Modify the existing bugsummary_journal_bugtaskflat to accept an array of
-- tags, and to return a set of rows to the caller rather than inserting
-- them into a temporary table.  This can now be just SQL rather than
-- PL/pgSQL.
DROP FUNCTION bugsummary_journal_bugtaskflat;
CREATE FUNCTION bugsummary_journal_bugtaskflat(btf_row bugtaskflat, tags text[], _count integer)
    RETURNS SETOF bugsummaryjournal
    LANGUAGE sql
    AS $$
    SELECT
        CAST(NULL AS integer) as id,
        _count, product, productseries, distribution,
        distroseries, sourcepackagename, viewed_by, tag,
        status, milestone, importance, has_patch, access_policy
        FROM bugsummary_locations(btf_row, tags);
$$;

-- Rewrite the existing bugtaskflat_maintain_bug_summary as a
-- statement-level trigger.
CREATE OR REPLACE FUNCTION bugtaskflat_maintain_bug_summary()
    RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
DECLARE
    summary_queries text[] DEFAULT '{}';
BEGIN
    -- Work out the subqueries we need to compute the set of
    -- BugSummaryJournal rows that should be inserted.  (We have to use
    -- dynamic commands for this, because the transition tables are not
    -- visible in functions called by this trigger function.)
    IF TG_OP = 'DELETE' OR TG_OP = 'UPDATE' THEN
        summary_queries := array_append(summary_queries, $_$
            SELECT summary.*
            FROM
                old_bugtaskflat btf_row,
                LATERAL bugsummary_journal_bugtaskflat(
                    btf_row, bugsummary_tag_names(btf_row.bug), -1
                ) AS summary
        $_$);
    END IF;
    IF TG_OP = 'INSERT' OR TG_OP = 'UPDATE' THEN
        summary_queries := array_append(summary_queries, $_$
            SELECT summary.*
            FROM
                new_bugtaskflat btf_row,
                LATERAL bugsummary_journal_bugtaskflat(
                    btf_row, bugsummary_tag_names(btf_row.bug), 1
                ) AS summary
        $_$);
    END IF;
    -- We sum the rows here to minimise the number of inserts into the
    -- journal, as in the case of UPDATE statement we may have -1s and +1s
    -- cancelling each other out.
    EXECUTE ($_$
        INSERT INTO BugSummaryJournal(
            count, product, productseries, distribution,
            distroseries, sourcepackagename, viewed_by, tag,
            status, milestone, importance, has_patch, access_policy)
        SELECT
            SUM(count), product, productseries, distribution,
            distroseries, sourcepackagename, viewed_by, tag,
            status, milestone, importance, has_patch, access_policy
        FROM (
    $_$ || array_to_string(summary_queries, 'UNION ALL') || $_$
        ) AS summary
        GROUP BY
            product, productseries, distribution,
            distroseries, sourcepackagename, viewed_by, tag,
            status, milestone, importance, has_patch, access_policy
        HAVING SUM(count) != 0;
    $_$);
    RETURN NULL;
END;
$$;

CREATE TRIGGER bugtaskflat_maintain_bug_summary_insert
    AFTER INSERT ON bugtaskflat
    REFERENCING NEW TABLE AS new_bugtaskflat
    FOR EACH STATEMENT EXECUTE PROCEDURE bugtaskflat_maintain_bug_summary();

CREATE TRIGGER bugtaskflat_maintain_bug_summary_update
    AFTER UPDATE ON bugtaskflat
    REFERENCING OLD TABLE AS old_bugtaskflat NEW TABLE AS new_bugtaskflat
    FOR EACH STATEMENT EXECUTE PROCEDURE bugtaskflat_maintain_bug_summary();

CREATE TRIGGER bugtaskflat_maintain_bug_summary_delete
    AFTER DELETE ON bugtaskflat
    REFERENCING OLD TABLE AS old_bugtaskflat
    FOR EACH STATEMENT EXECUTE PROCEDURE bugtaskflat_maintain_bug_summary();

-- Modify the existing bugsummary_journal_bug to accept an array of tags,
-- and to return a set of rows to the caller rather than inserting them into
-- a temporary table.  Rephrasing the loop using LATERAL allows this to be
-- just SQL rather than PL/pgSQL.
DROP FUNCTION bugsummary_journal_bug;
CREATE FUNCTION bugsummary_journal_bug(bug_row bug, tags text[], _count integer)
    RETURNS SETOF bugsummaryjournal
    LANGUAGE sql
    AS $$
    SELECT summary.*
    FROM
        bugtaskflat btf_row,
        LATERAL bugsummary_journal_bugtaskflat(
            btf_row, tags, _count
        ) AS summary
    WHERE bug = bug_row.id;
$$;

-- Rewrite the existing bugtag_maintain_bug_summary as a statement-level
-- trigger.
CREATE OR REPLACE FUNCTION bugtag_maintain_bug_summary()
    RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
DECLARE
    summary_queries text[] DEFAULT '{}';
BEGIN
    -- Work out the subqueries we need to compute the set of
    -- BugSummaryJournal rows that should be inserted.  (We have to use
    -- dynamic commands for this, because the transition tables are not
    -- visible in functions called by this trigger function.)
    IF TG_OP = 'DELETE' OR TG_OP = 'UPDATE' THEN
        summary_queries := array_append(summary_queries, $_$
            SELECT summary.*
            FROM
                (SELECT bug, array_agg(tag) AS tags
                 FROM old_bugtag
                 GROUP BY bug) AS grouped_bugtags,
                LATERAL bugsummary_journal_bug(
                    bug_row(grouped_bugtags.bug), grouped_bugtags.tags, -1
                ) AS summary
        $_$);
    END IF;
    IF TG_OP = 'INSERT' OR TG_OP = 'UPDATE' THEN
        summary_queries := array_append(summary_queries, $_$
            SELECT summary.*
            FROM
                (SELECT bug, array_agg(tag) AS tags
                 FROM new_bugtag
                 GROUP BY bug) AS grouped_bugtags,
                LATERAL bugsummary_journal_bug(
                    bug_row(grouped_bugtags.bug), grouped_bugtags.tags, 1
                ) AS summary
        $_$);
    END IF;
    -- We sum the rows here to minimise the number of inserts into the
    -- journal, as in the case of UPDATE statement we may have -1s and +1s
    -- cancelling each other out.
    EXECUTE ($_$
        INSERT INTO BugSummaryJournal(
            count, product, productseries, distribution,
            distroseries, sourcepackagename, viewed_by, tag,
            status, milestone, importance, has_patch, access_policy)
        SELECT
            SUM(count), product, productseries, distribution,
            distroseries, sourcepackagename, viewed_by, tag,
            status, milestone, importance, has_patch, access_policy
        FROM (
    $_$ || array_to_string(summary_queries, 'UNION ALL') || $_$
        ) AS summary
        GROUP BY
            product, productseries, distribution,
            distroseries, sourcepackagename, viewed_by, tag,
            status, milestone, importance, has_patch, access_policy
        HAVING SUM(count) != 0;
    $_$);
    RETURN NULL;
END;
$$;

CREATE TRIGGER bugtag_maintain_bug_summary_insert
    AFTER INSERT ON bugtag
    REFERENCING NEW TABLE AS new_bugtag
    FOR EACH STATEMENT EXECUTE PROCEDURE bugtag_maintain_bug_summary();

CREATE TRIGGER bugtag_maintain_bug_summary_update
    AFTER UPDATE ON bugtag
    REFERENCING OLD TABLE AS old_bugtag NEW TABLE AS new_bugtag
    FOR EACH STATEMENT EXECUTE PROCEDURE bugtag_maintain_bug_summary();

CREATE TRIGGER bugtag_maintain_bug_summary_delete
    AFTER DELETE ON bugtag
    REFERENCING OLD TABLE AS old_bugtag
    FOR EACH STATEMENT EXECUTE PROCEDURE bugtag_maintain_bug_summary();

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 06, 0);
