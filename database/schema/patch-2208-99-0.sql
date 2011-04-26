-- Copyright 2011 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

-- WHAT ARE WE DOING? -----------------------------------------------------

-- These three errors have been observed, and are corrected here.

-- If StructuralSubscription.product is not NULL, the combination of
-- StructuralSubscription.product and StructuralSubscription.subscriber
-- should be unique.

-- If StructuralSubscription.project is not NULL, the combination of
-- StructuralSubscription.project and StructuralSubscription.subscriber
-- should be unique.

-- If StructuralSubscription.distribution and
-- StructuralSubscription.sourcepackagename are not NULL, the combination of
-- StructuralSubscription.distribution,
-- StructuralSubscription.sourcepackagename, and
-- StructuralSubscription.subscriber should be unique.

-- These have not been observed, but are prevented for safekeeping.

-- If StructuralSubscription.distribution is not NULL but
-- StructuralSubscription.sourcepackagename is NULL, the combination of
-- StructuralSubscription.distribution and
-- StructuralSubscription.subscriber should be unique.

-- If StructuralSubscription.distroseries is not NULL, the combination of
-- StructuralSubscription.distroseries and StructuralSubscription.subscriber
-- should be unique.

-- If StructuralSubscription.milestone is not NULL, the combination of
-- StructuralSubscription.milestone and StructuralSubscription.subscriber
-- should be unique.

-- If StructuralSubscription.productseries is not NULL, the combination of
-- StructuralSubscription.productseries and StructuralSubscription.subscriber
-- should be unique.

-- So, we want to eliminate dupes, and then set up constraints so they do not
-- come back.

-- ELIMINATE DUPES --------------------------------------------------------

-- First, we eliminate dupes.

-- We find duplicates and eliminate the ones that are older (on the basis
-- of the id being a smaller number).

-- This eliminates product dupes.  As an example, this is run on staging.

-- lpmain_staging=> SELECT Subscription.product,
--        Subscription.subscriber,
--        Subscription.id
-- FROM StructuralSubscription AS Subscription
-- WHERE EXISTS (
--    SELECT StructuralSubscription.product, StructuralSubscription.subscriber
--    FROM StructuralSubscription
--    WHERE
--        StructuralSubscription.product = Subscription.product
--        AND StructuralSubscription.subscriber = Subscription.subscriber
--    GROUP BY StructuralSubscription.product, StructuralSubscription.subscriber
--    HAVING Count(*)>1) ORDER BY Subscription.product, Subscription.subscriber, Subscription.id;
--  product | subscriber |  id   
-- ---------+------------+-------
--     2461 |    2212151 |  7570
--     2461 |    2212151 |  7571
--     7533 |    1814750 |  5428
--     7533 |    1814750 |  5492
--     7534 |    1814750 |  5429
--     7534 |    1814750 |  5491
--     8269 |     242763 |  8191
--     8269 |     242763 |  8192
--     9868 |    3388985 | 25131
--     9868 |    3388985 | 25132
--    24395 |    3391740 | 21770
--    24395 |    3391740 | 23900
-- (12 rows)
-- 
-- lpmain_staging=> WITH duped_values AS
--     (SELECT Subscription.product,
--             Subscription.subscriber,
--             Subscription.id
--      FROM StructuralSubscription AS Subscription
--      WHERE EXISTS (                                                        
--         SELECT StructuralSubscription.product, StructuralSubscription.subscriber
--         FROM StructuralSubscription
--         WHERE                                               
--             StructuralSubscription.product = Subscription.product
--             AND StructuralSubscription.subscriber = Subscription.subscriber
--         GROUP BY StructuralSubscription.product, StructuralSubscription.subscriber
--         HAVING Count(*)>1))
--  SELECT duped_values.id
--  FROM duped_values
--  WHERE duped_values.id NOT IN
--     (SELECT MAX(duped_values.id)
--      FROM duped_values
--      GROUP BY duped_values.product, duped_values.subscriber);
--   id   
-- -------
--   5429
--   5428
--   8191
--  25131
--   7570
--  21770
-- (6 rows)

DELETE FROM StructuralSubscription WHERE
    StructuralSubscription.id IN 
        (WITH duped_values AS
            (SELECT Subscription.product,
                    Subscription.subscriber,
                    Subscription.id
             FROM StructuralSubscription AS Subscription
             WHERE EXISTS (
                SELECT StructuralSubscription.product, StructuralSubscription.subscriber
                FROM StructuralSubscription
                WHERE
                    StructuralSubscription.product = Subscription.product
                    AND StructuralSubscription.subscriber = Subscription.subscriber
                GROUP BY StructuralSubscription.product, StructuralSubscription.subscriber
                HAVING Count(*)>1))
         SELECT duped_values.id
         FROM duped_values
         WHERE duped_values.id NOT IN
            (SELECT MAX(duped_values.id)
             FROM duped_values
             GROUP BY duped_values.product, duped_values.subscriber));

-- Now we eliminate project dupes.  This, like most of the variations,
-- is a copy-and-paste job, replacing "product" with "project".

DELETE FROM StructuralSubscription WHERE
    StructuralSubscription.id IN 
        (WITH duped_values AS
            (SELECT Subscription.project,
                    Subscription.subscriber,
                    Subscription.id
             FROM StructuralSubscription AS Subscription
             WHERE EXISTS (
                SELECT StructuralSubscription.project, StructuralSubscription.subscriber
                FROM StructuralSubscription
                WHERE
                    StructuralSubscription.project = Subscription.project
                    AND StructuralSubscription.subscriber = Subscription.subscriber
                GROUP BY StructuralSubscription.project, StructuralSubscription.subscriber
                HAVING Count(*)>1))
         SELECT duped_values.id
         FROM duped_values
         WHERE duped_values.id NOT IN
            (SELECT MAX(duped_values.id)
             FROM duped_values
             GROUP BY duped_values.project, duped_values.subscriber));

-- Now we eliminate distroseries dupes.  They don't exist on staging, but
-- there's nothing keeping them from happening, so this is just to make sure.
-- This is another copy and paste job.

DELETE FROM StructuralSubscription WHERE
    StructuralSubscription.id IN 
        (WITH duped_values AS
            (SELECT Subscription.distroseries,
                    Subscription.subscriber,
                    Subscription.id
             FROM StructuralSubscription AS Subscription
             WHERE EXISTS (
                SELECT StructuralSubscription.distroseries, StructuralSubscription.subscriber
                FROM StructuralSubscription
                WHERE
                    StructuralSubscription.distroseries = Subscription.distroseries
                    AND StructuralSubscription.subscriber = Subscription.subscriber
                GROUP BY StructuralSubscription.distroseries, StructuralSubscription.subscriber
                HAVING Count(*)>1))
         SELECT duped_values.id
         FROM duped_values
         WHERE duped_values.id NOT IN
            (SELECT MAX(duped_values.id)
             FROM duped_values
             GROUP BY duped_values.distroseries, duped_values.subscriber));

-- Now we eliminate milestone dupes.  This again does not have matches on
-- staging, and is again a copy-and-paste job.

DELETE FROM StructuralSubscription WHERE
    StructuralSubscription.id IN 
        (WITH duped_values AS
            (SELECT Subscription.milestone,
                    Subscription.subscriber,
                    Subscription.id
             FROM StructuralSubscription AS Subscription
             WHERE EXISTS (
                SELECT StructuralSubscription.milestone, StructuralSubscription.subscriber
                FROM StructuralSubscription
                WHERE
                    StructuralSubscription.milestone = Subscription.milestone
                    AND StructuralSubscription.subscriber = Subscription.subscriber
                GROUP BY StructuralSubscription.milestone, StructuralSubscription.subscriber
                HAVING Count(*)>1))
         SELECT duped_values.id
         FROM duped_values
         WHERE duped_values.id NOT IN
            (SELECT MAX(duped_values.id)
             FROM duped_values
             GROUP BY duped_values.milestone, duped_values.subscriber));

-- Now we eliminate productseries dupes.  This again does not have matches on
-- staging, and is again a copy-and-paste job.

DELETE FROM StructuralSubscription WHERE
    StructuralSubscription.id IN 
        (WITH duped_values AS
            (SELECT Subscription.productseries,
                    Subscription.subscriber,
                    Subscription.id
             FROM StructuralSubscription AS Subscription
             WHERE EXISTS (
                SELECT StructuralSubscription.productseries, StructuralSubscription.subscriber
                FROM StructuralSubscription
                WHERE
                    StructuralSubscription.productseries = Subscription.productseries
                    AND StructuralSubscription.subscriber = Subscription.subscriber
                GROUP BY StructuralSubscription.productseries, StructuralSubscription.subscriber
                HAVING Count(*)>1))
         SELECT duped_values.id
         FROM duped_values
         WHERE duped_values.id NOT IN
            (SELECT MAX(duped_values.id)
             FROM duped_values
             GROUP BY duped_values.productseries, duped_values.subscriber));

-- Now we need to eliminate distribution and sourcepackagename dupes.  These
-- involve a bit more modification of the pattern, though it is still the
-- same basic idea.

-- This is the distribution.  It has no matches on staging.

DELETE FROM StructuralSubscription WHERE
    StructuralSubscription.id IN 
        (WITH duped_values AS
            (SELECT Subscription.distribution,
                    Subscription.subscriber,
                    Subscription.id
             FROM StructuralSubscription AS Subscription
             WHERE EXISTS (
                SELECT StructuralSubscription.distribution, StructuralSubscription.subscriber
                FROM StructuralSubscription
                WHERE
                    StructuralSubscription.distribution = Subscription.distribution
                    AND StructuralSubscription.subscriber = Subscription.subscriber
-- This is the new line.
                    AND StructuralSubscription.sourcepackagename IS NULL
                GROUP BY StructuralSubscription.distribution, StructuralSubscription.subscriber
                HAVING Count(*)>1))
         SELECT duped_values.id
         FROM duped_values
         WHERE duped_values.id NOT IN
            (SELECT MAX(duped_values.id)
             FROM duped_values
             GROUP BY duped_values.distribution, duped_values.subscriber));

-- This is the sourcepackagename.  It *does* have matches on staging.

DELETE FROM StructuralSubscription WHERE
    StructuralSubscription.id IN 
        (WITH duped_values AS
            (SELECT Subscription.distribution,
                    Subscription.sourcepackagename,
                    Subscription.subscriber,
                    Subscription.id
             FROM StructuralSubscription AS Subscription
             WHERE EXISTS (
                SELECT StructuralSubscription.distribution,
                       StructuralSubscription.sourcepackagename,
                       StructuralSubscription.subscriber
                FROM StructuralSubscription
                WHERE
                    StructuralSubscription.distribution = Subscription.distribution
                    AND StructuralSubscription.sourcepackagename = Subscription.sourcepackagename
                    AND StructuralSubscription.subscriber = Subscription.subscriber
                GROUP BY StructuralSubscription.distribution,
                         StructuralSubscription.sourcepackagename,
                         StructuralSubscription.subscriber
                HAVING Count(*)>1))
         SELECT duped_values.id
         FROM duped_values
         WHERE duped_values.id NOT IN
            (SELECT MAX(duped_values.id)
             FROM duped_values
             GROUP BY duped_values.distribution,
                      duped_values.sourcepackagename,
                      duped_values.subscriber));



-- CREATE CONSTRAINTS ----------------------------------------------------

-- Now we add our constraints.  Note that, per SQL standard, Postgres does not
-- consider two NULLs to be equal.

ALTER TABLE ONLY StructuralSubscription
    ADD CONSTRAINT structuralsubscription__product__subscriber__unique
        UNIQUE (product, subscriber);

ALTER TABLE ONLY StructuralSubscription
    ADD CONSTRAINT structuralsubscription__project__subscriber__unique
        UNIQUE (project, subscriber);

-- We want to do this.
-- ALTER TABLE ONLY StructuralSubscription
--     ADD CONSTRAINT structuralsubscription__distribution__sourcepackagename__subscriber__unique
--        UNIQUE (distribution, sourcepackagename, subscriber);
-- However, we also want to do this, *if* the sourcepackagename is NULL.
-- ALTER TABLE ONLY StructuralSubscription
--     ADD CONSTRAINT structuralsubscription__distribution__subscriber__unique
--         UNIQUE (distribution, subscriber);
-- The second constraint will disallow sourcepackagename flexibility in the
-- first.  Therefore, we use a unique index instead, as seen below.

CREATE UNIQUE INDEX
    structuralsubscription__distribution__sourcepackagename__subscriber__unique
    ON structuralsubscription
    USING btree (distribution,
                 (COALESCE(sourcepackagename, (-1))),
                 subscriber)
    WHERE ((distribution IS NOT NULL) AND (subscriber IS NOT NULL));

ALTER TABLE ONLY StructuralSubscription
    ADD CONSTRAINT structuralsubscription__distroseries__subscriber__unique
        UNIQUE (distroseries, subscriber);

ALTER TABLE ONLY StructuralSubscription
    ADD CONSTRAINT structuralsubscription__milestone__subscriber__unique
        UNIQUE (milestone, subscriber);

ALTER TABLE ONLY StructuralSubscription
    ADD CONSTRAINT structuralsubscription__productseries__subscriber__unique
        UNIQUE (productseries, subscriber);

INSERT INTO LaunchpadDatabaseRevision VALUES (2208, 99, 0);
