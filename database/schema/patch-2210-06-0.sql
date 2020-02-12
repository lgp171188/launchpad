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

-- Modify the existing bugsummary_locations to accept an array of tags
-- rather than looking them up for itself, and return journal rows rather than
-- bugsummary ones, since we haven't directly written to bugsummary in the
-- better part of a decade.
DROP FUNCTION bugsummary_locations;
CREATE FUNCTION bugsummary_locations(btf_row bugtaskflat, tags text[])
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
            bug_viewers.access_policy
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
            distroseries, sourcepackagename, viewed_by, tag,
            status, milestone, importance, has_patch, access_policy)
        SELECT
            SUM(count), product, productseries, distribution,
            distroseries, sourcepackagename, viewed_by, tag,
            status, milestone, importance, has_patch, access_policy
        FROM unnest(journals)
        GROUP BY
            product, productseries, distribution,
            distroseries, sourcepackagename, viewed_by, tag,
            status, milestone, importance, has_patch, access_policy
        HAVING SUM(count) != 0;
$$;

-- Rewrite the existing bugtaskflat_maintain_bug_summary as a
-- statement-level trigger.
CREATE TYPE bugsummary_temp_btf_internal AS (
   btf bugtaskflat,
   count integer
);

CREATE OR REPLACE FUNCTION bugtaskflat_maintain_bug_summary()
    RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
DECLARE
    all_rows bugsummary_temp_btf_internal[];
    temp_rows bugsummary_temp_btf_internal[];
    journals bugsummaryjournal[];
    temp_rec record;
    temp_journal bugsummaryjournal;
BEGIN
    -- Work out the subqueries we need to compute the set of
    -- BugSummaryJournal rows that should be inserted.
    IF TG_OP = 'DELETE' OR TG_OP = 'UPDATE' THEN
        SELECT array_agg(row(old_bugtaskflat, -1))
            INTO STRICT temp_rows FROM old_bugtaskflat;
        all_rows := array_cat(all_rows, temp_rows);
    END IF;
    IF TG_OP = 'INSERT' OR TG_OP = 'UPDATE' THEN
        SELECT array_agg(row(new_bugtaskflat, 1))
            INTO STRICT temp_rows FROM new_bugtaskflat;
        all_rows := array_cat(all_rows, temp_rows);
    END IF;

    -- XXX wgrant 2020-02-07: "The target is a record variable, row
    -- variable, or comma-separated list of scalar variables." but a list
    -- doesn't seem to work.
    FOR temp_rec IN
        SELECT journal, row.count
        FROM
            unnest(all_rows) AS row,
            LATERAL bugsummary_locations(
                row((row.btf).*),
                (SELECT array_append(array_agg(tag), NULL::text)
                 FROM bugtag WHERE bug = (row.btf).bug)) AS journal
    LOOP
        temp_journal := temp_rec.journal;
        temp_journal.count := temp_rec.count;
        journals := array_append(journals, temp_journal);
    END LOOP;

    PERFORM bugsummary_insert_journals(journals);
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

-- Rewrite the existing bugtag_maintain_bug_summary as a statement-level
-- trigger.
CREATE TYPE bugsummary_temp_bug_internal AS (
   bug integer,
   tags text[],
   count integer
);

CREATE OR REPLACE FUNCTION bugtag_maintain_bug_summary()
    RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
DECLARE
    all_rows bugsummary_temp_bug_internal[];
    temp_rows bugsummary_temp_bug_internal[];
    journals bugsummaryjournal[];
    temp_rec record;
    temp_journal bugsummaryjournal;
BEGIN
    -- Work out the subqueries we need to compute the set of
    -- BugSummaryJournal rows that should be inserted.
    IF TG_OP = 'DELETE' OR TG_OP = 'UPDATE' THEN
        SELECT array_agg(
            (SELECT row(bug, array_agg(tag), -1) FROM old_bugtag GROUP BY bug))
            INTO STRICT temp_rows;
        all_rows := array_cat(all_rows, temp_rows);
    END IF;
    IF TG_OP = 'INSERT' OR TG_OP = 'UPDATE' THEN
        SELECT array_agg(
            (SELECT row(bug, array_agg(tag), 1) FROM new_bugtag GROUP BY bug))
            INTO STRICT temp_rows;
        all_rows := array_cat(all_rows, temp_rows);
    END IF;

    -- XXX wgrant 2020-02-07: "The target is a record variable, row
    -- variable, or comma-separated list of scalar variables." but a list
    -- doesn't seem to work.
    FOR temp_rec IN
        SELECT journal, row.count
        FROM
            unnest(all_rows) as row,
            LATERAL (
                SELECT journal.*
                FROM
                    bugtaskflat btf,
                    bugsummary_locations(btf, row.tags) AS journal
                WHERE btf.bug = row.bug
            ) AS journal
    LOOP
        temp_journal := temp_rec.journal;
        temp_journal.count := temp_rec.count;
        journals := array_append(journals, temp_journal);
    END LOOP;

    PERFORM bugsummary_insert_journals(journals);
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

DROP FUNCTION bugsummary_tags;
DROP FUNCTION bugsummary_journal_bug;
DROP FUNCTION bugsummary_journal_bugtaskflat;
DROP FUNCTION bug_row;
DROP FUNCTION bug_summary_flush_temp_journal;
DROP FUNCTION ensure_bugsummary_temp_journal;
DROP FUNCTION summarise_bug;
DROP FUNCTION unsummarise_bug;

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 06, 0);
