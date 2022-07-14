-- Copyright 2019-2020 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE DistributionMirror
    ADD COLUMN https_base_url text,
    ADD CONSTRAINT distributionmirror_https_base_url_key UNIQUE (https_base_url),
    ADD CONSTRAINT valid_https_base_url CHECK (valid_absolute_url(https_base_url)),
    DROP CONSTRAINT one_or_more_urls,
    ADD CONSTRAINT one_or_more_urls CHECK (http_base_url IS NOT NULL OR https_base_url IS NOT NULL OR ftp_base_url IS NOT NULL OR rsync_base_url IS NOT NULL);

COMMENT ON COLUMN DistributionMirror.https_base_url IS 'The HTTPS URL used to access the mirror.';

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 3, 0);
