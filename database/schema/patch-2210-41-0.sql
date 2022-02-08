-- Copyright 2022 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE Distribution
    ADD COLUMN branch_sharing_policy integer DEFAULT 1 NOT NULL,
    ADD COLUMN bug_sharing_policy integer DEFAULT 1 NOT NULL,
    ADD COLUMN specification_sharing_policy integer DEFAULT 1 NOT NULL,
    ADD COLUMN information_type integer DEFAULT 1 NOT NULL,
    ADD COLUMN access_policies integer[],
    ADD CONSTRAINT distribution__valid_information_type CHECK (
        information_type = ANY(ARRAY[1, 5, 6]));

COMMENT ON COLUMN Distribution.branch_sharing_policy IS 'Sharing policy for this distribution''s branches.';
COMMENT ON COLUMN Distribution.bug_sharing_policy IS 'Sharing policy for this distribution''s bugs.';
COMMENT ON COLUMN Distribution.specification_sharing_policy IS 'Sharing policy for this distribution''s specifications.';
COMMENT ON COLUMN Distribution.information_type IS 'Enum describing what type of information is stored, such as type of private or security related data, and used to determine how to apply an access policy.';
COMMENT ON COLUMN Distribution.access_policies IS 'Cache of AccessPolicy.ids that convey launchpad.LimitedView.';

ALTER TABLE CommercialSubscription
    ADD COLUMN distribution integer REFERENCES distribution,
    ALTER COLUMN product DROP NOT NULL,
    ADD CONSTRAINT one_pillar CHECK (null_count(ARRAY[product, distribution]) = 1);

DROP INDEX commercialsubscription__product__idx;
CREATE UNIQUE INDEX commercialsubscription__product__idx
    ON CommercialSubscription (product) WHERE product IS NOT NULL;
CREATE UNIQUE INDEX commercialsubscription__distribution__idx
    ON CommercialSubscription (distribution) WHERE distribution IS NOT NULL;

COMMENT ON COLUMN CommercialSubscription.distribution IS 'The distribution this subscription enables.';

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 41, 0);
