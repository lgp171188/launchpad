-- Copyright 2022 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

-- We have a number of triggers called on UPDATEs of relatively wide rows
-- that only need to trigger on changes to a small number of columns.  Make
-- those triggers column-specific.

DROP TRIGGER mv_branch_distribution_update_t ON distribution;
CREATE TRIGGER mv_branch_distribution_update_t
    AFTER UPDATE OF name ON distribution
    FOR EACH ROW EXECUTE PROCEDURE mv_branch_distribution_update();

DROP TRIGGER mv_branch_distroseries_update_t ON distroseries;
CREATE TRIGGER mv_branch_distroseries_update_t
    AFTER UPDATE OF name ON distroseries
    FOR EACH ROW EXECUTE PROCEDURE mv_branch_distroseries_update();

DROP TRIGGER mv_branch_person_update_t ON person;
CREATE TRIGGER mv_branch_person_update_t
    AFTER UPDATE OF name ON person
    FOR EACH ROW EXECUTE PROCEDURE mv_branch_person_update();

DROP TRIGGER mv_branch_product_update_t ON product;
CREATE TRIGGER mv_branch_product_update_t
    AFTER UPDATE OF name ON product
    FOR EACH ROW EXECUTE PROCEDURE mv_branch_product_update();

DROP TRIGGER mv_pillarname_distribution_t ON distribution;
CREATE TRIGGER mv_pillarname_distribution_t
    AFTER INSERT OR UPDATE OF name ON distribution
    FOR EACH ROW EXECUTE PROCEDURE mv_pillarname_distribution();

DROP TRIGGER mv_pillarname_product_t ON product;
CREATE TRIGGER mv_pillarname_product_t
    AFTER INSERT OR UPDATE OF name, active ON product
    FOR EACH ROW EXECUTE PROCEDURE mv_pillarname_product();

DROP TRIGGER mv_pillarname_project_t ON project;
CREATE TRIGGER mv_pillarname_project_t
    AFTER INSERT OR UPDATE OF name, active ON project
    FOR EACH ROW EXECUTE PROCEDURE mv_pillarname_project();

DROP TRIGGER set_bug_number_of_duplicates_t ON bug;
CREATE TRIGGER set_bug_number_of_duplicates_t
    AFTER INSERT OR DELETE OR UPDATE OF duplicateof ON bug
    FOR EACH ROW EXECUTE PROCEDURE set_bug_number_of_duplicates();

DROP TRIGGER set_bugtask_date_milestone_set_t ON bugtask;
CREATE TRIGGER set_bugtask_date_milestone_set_t
    AFTER INSERT OR UPDATE OF milestone ON bugtask
    FOR EACH ROW EXECUTE PROCEDURE set_bugtask_date_milestone_set();

DROP TRIGGER set_date_status_set_t ON account;
CREATE TRIGGER set_date_status_set_t
    BEFORE UPDATE OF status ON account
    FOR EACH ROW EXECUTE PROCEDURE set_date_status_set();

DROP TRIGGER tsvectorupdate ON binarypackagerelease;
CREATE TRIGGER tsvectorupdate
    BEFORE INSERT OR UPDATE OF summary, description, fti ON binarypackagerelease
    FOR EACH ROW EXECUTE PROCEDURE ftiupdate('summary', 'b', 'description', 'c');

DROP TRIGGER tsvectorupdate ON cve;
CREATE TRIGGER tsvectorupdate
    BEFORE INSERT OR UPDATE OF sequence, description, fti ON cve
    FOR EACH ROW EXECUTE PROCEDURE ftiupdate('sequence', 'a', 'description', 'b');

DROP TRIGGER tsvectorupdate ON distroseriespackagecache;
CREATE TRIGGER tsvectorupdate
    BEFORE INSERT OR UPDATE OF name, summaries, descriptions, fti ON distroseriespackagecache
    FOR EACH ROW EXECUTE PROCEDURE ftiupdate('name', 'a', 'summaries', 'b', 'descriptions', 'c');

DROP TRIGGER tsvectorupdate ON message;
CREATE TRIGGER tsvectorupdate
    BEFORE INSERT OR UPDATE OF subject, fti ON message
    FOR EACH ROW EXECUTE PROCEDURE ftiupdate('subject', 'b');

DROP TRIGGER tsvectorupdate ON messagechunk;
CREATE TRIGGER tsvectorupdate
    BEFORE INSERT OR UPDATE OF content, fti ON messagechunk
    FOR EACH ROW EXECUTE PROCEDURE ftiupdate('content', 'c');

DROP TRIGGER tsvectorupdate ON product;
CREATE TRIGGER tsvectorupdate
    BEFORE INSERT OR UPDATE OF name, displayname, title, summary, description, fti ON product
    FOR EACH ROW EXECUTE PROCEDURE ftiupdate('name', 'a', 'displayname', 'a', 'title', 'b', 'summary', 'c', 'description', 'd');

DROP TRIGGER tsvectorupdate ON project;
CREATE TRIGGER tsvectorupdate
    BEFORE INSERT OR UPDATE OF name, displayname, title, summary, description, fti ON project
    FOR EACH ROW EXECUTE PROCEDURE ftiupdate('name', 'a', 'displayname', 'a', 'title', 'b', 'summary', 'c', 'description', 'd');

DROP TRIGGER tsvectorupdate ON question;
CREATE TRIGGER tsvectorupdate
    BEFORE INSERT OR UPDATE OF title, description, whiteboard, fti ON question
    FOR EACH ROW EXECUTE PROCEDURE ftiupdate('title', 'a', 'description', 'b', 'whiteboard', 'b');

DROP TRIGGER tsvectorupdate ON bug;
CREATE TRIGGER tsvectorupdate
    BEFORE INSERT OR UPDATE OF name, title, description, fti ON bug
    FOR EACH ROW EXECUTE PROCEDURE ftiupdate('name', 'a', 'title', 'b', 'description', 'd');

DROP TRIGGER tsvectorupdate ON person;
CREATE TRIGGER tsvectorupdate
    BEFORE INSERT OR UPDATE OF name, displayname, fti ON person
    FOR EACH ROW EXECUTE PROCEDURE ftiupdate('name', 'a', 'displayname', 'a');

DROP TRIGGER tsvectorupdate ON specification;
CREATE TRIGGER tsvectorupdate
    BEFORE INSERT OR UPDATE OF name, title, summary, whiteboard, fti ON specification
    FOR EACH ROW EXECUTE PROCEDURE ftiupdate('name', 'a', 'title', 'a', 'summary', 'b', 'whiteboard', 'd');

DROP TRIGGER tsvectorupdate ON distribution;
CREATE TRIGGER tsvectorupdate
    BEFORE INSERT OR UPDATE OF name, displayname, title, summary, description, fti ON distribution
    FOR EACH ROW EXECUTE PROCEDURE ftiupdate('name', 'a', 'displayname', 'a', 'title', 'b', 'summary', 'c', 'description', 'd');

DROP TRIGGER tsvectorupdate ON productreleasefile;
CREATE TRIGGER tsvectorupdate
    BEFORE INSERT OR UPDATE OF description, fti ON productreleasefile
    FOR EACH ROW EXECUTE PROCEDURE ftiupdate('description', 'd');

DROP TRIGGER tsvectorupdate ON faq;
CREATE TRIGGER tsvectorupdate
    BEFORE INSERT OR UPDATE OF title, tags, content, fti ON faq
    FOR EACH ROW EXECUTE PROCEDURE ftiupdate('title', 'a', 'tags', 'b', 'content', 'd');

DROP TRIGGER tsvectorupdate ON archive;
CREATE TRIGGER tsvectorupdate
    BEFORE INSERT OR UPDATE OF description, package_description_cache, fti ON archive
    FOR EACH ROW EXECUTE PROCEDURE ftiupdate('description', 'a', 'package_description_cache', 'b');

DROP TRIGGER tsvectorupdate ON distributionsourcepackagecache;
CREATE TRIGGER tsvectorupdate
    BEFORE INSERT OR UPDATE OF name, binpkgnames, binpkgsummaries, binpkgdescriptions, fti ON distributionsourcepackagecache
    FOR EACH ROW EXECUTE PROCEDURE ftiupdate('name', 'a', 'binpkgnames', 'b', 'binpkgsummaries', 'c', 'binpkgdescriptions', 'd');

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 6, 1);
