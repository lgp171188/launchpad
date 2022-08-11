-- Copyright 2021 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

CREATE INDEX binarypackagepublishinghistory__copied_from_archive__idx
    ON BinaryPackagePublishingHistory(copied_from_archive)
    WHERE copied_from_archive IS NOT NULL;

CREATE INDEX packagecopyjob__source_archive__idx
    ON PackageCopyJob(source_archive);

CREATE INDEX packagecopyrequest__source_archive__idx
    ON PackageCopyRequest(source_archive);

CREATE INDEX snap__auto_build_archive__idx
    ON Snap(auto_build_archive)
    WHERE auto_build_archive IS NOT NULL;

CREATE INDEX sourcepackagepublishinghistory__copied_from_archive__idx
    ON SourcePackagePublishingHistory(copied_from_archive)
    WHERE copied_from_archive IS NOT NULL;

CREATE INDEX sourcepackagerecipebuild__archive__idx
    ON SourcePackageRecipeBuild(archive);

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 11, 3);
