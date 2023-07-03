#  Copyright 2022 Canonical Ltd.  This software is licensed under the
#  GNU Affero General Public License version 3 (see the file LICENSE).

from datetime import datetime, timezone
from pathlib import Path
from typing import List

from zope.component import getUtility

from lp.app.enums import InformationType
from lp.app.interfaces.launchpad import ILaunchpadCelebrities
from lp.bugs.enums import VulnerabilityStatus
from lp.bugs.interfaces.bugtask import BugTaskImportance, BugTaskStatus
from lp.bugs.model.bug import Bug
from lp.bugs.model.bugtask import BugTask
from lp.bugs.model.cve import Cve as CveModel
from lp.bugs.scripts.uct import (
    CVE,
    CVSS,
    UCTExporter,
    UCTImporter,
    UCTImportError,
    UCTRecord,
)
from lp.registry.interfaces.series import SeriesStatus
from lp.registry.model.sourcepackage import SourcePackage
from lp.services.propertycache import clear_property_cache
from lp.testing import TestCase, TestCaseWithFactory
from lp.testing.layers import ZopelessDatabaseLayer


class TestUCTRecord(TestCase):
    maxDiff = None

    def test_load_save(self):
        load_from = Path(__file__).parent / "sampledata" / "CVE-2022-23222"
        uct_record = UCTRecord.load(load_from)
        self.assertDictEqual(
            UCTRecord(
                parent_dir="sampledata",
                assigned_to="",
                bugs=[
                    "https://github.com/mm2/Little-CMS/issues/29",
                    "https://github.com/mm2/Little-CMS/issues/30",
                    "https://bugs.debian.org/cgi-bin/bugreport.cgi?bug=745471",
                ],
                cvss=[
                    CVSS(
                        authority="nvd",
                        vector_string=(
                            "CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H "
                            "[7.8 HIGH]"
                        ),
                    ),
                ],
                candidate="CVE-2022-23222",
                crd=None,
                public_date_at_USN=datetime(
                    2022, 1, 14, 8, 15, tzinfo=timezone.utc
                ),
                public_date=datetime(2022, 1, 14, 8, 15, tzinfo=timezone.utc),
                description=(
                    "kernel/bpf/verifier.c in the Linux kernel through "
                    "5.15.14 allows local\nusers to gain privileges because "
                    "of the availability of pointer arithmetic\nvia certain "
                    "*_OR_NULL pointer types."
                ),
                discovered_by="tr3e wang",
                mitigation=(
                    "seth-arnold> set kernel.unprivileged_bpf_disabled to 1"
                ),
                notes=(
                    "sbeattie> Ubuntu 21.10 / 5.13+ kernels disable "
                    "unprivileged BPF by default.\n  kernels 5.8 and "
                    "older are not affected, priority high is "
                    "for\n  5.10 and 5.11 based kernels only"
                ),
                priority=UCTRecord.Priority.CRITICAL,
                references=["https://ubuntu.com/security/notices/USN-5368-1"],
                ubuntu_description=(
                    "It was discovered that the BPF verifier in the Linux "
                    "kernel did not\nproperly restrict pointer types in "
                    "certain situations. A local attacker\ncould use this to "
                    "cause a denial of service (system crash) or possibly\n"
                    "execute arbitrary code."
                ),
                packages=[
                    UCTRecord.Package(
                        name="linux",
                        statuses=[
                            UCTRecord.SeriesPackageStatus(
                                series="upstream",
                                status=UCTRecord.PackageStatus.RELEASED,
                                reason="5.17~rc1",
                                priority=None,
                            ),
                            UCTRecord.SeriesPackageStatus(
                                series="impish",
                                status=UCTRecord.PackageStatus.RELEASED,
                                reason="5.13.0-37.42",
                                priority=UCTRecord.Priority.MEDIUM,
                            ),
                            UCTRecord.SeriesPackageStatus(
                                series="devel",
                                status=UCTRecord.PackageStatus.NOT_AFFECTED,
                                reason="5.15.0-25.25",
                                priority=UCTRecord.Priority.MEDIUM,
                            ),
                        ],
                        priority=None,
                        tags={"not-ue"},
                        patches=[
                            UCTRecord.Patch(
                                patch_type="break-fix",
                                entry=(
                                    "457f44363a8894135c85b7a9afd2bd8196db24ab "
                                    "c25b2ae136039ffa820c26138ed4a5e5f3ab3841|"
                                    "local-CVE-2022-23222-fix"
                                ),
                            ),
                            UCTRecord.Patch(
                                patch_type="upstream",
                                entry=(
                                    "https://github.com/389ds/389-ds-base/commit/58dbf084a63e6dbbd999bf6a70475fad8255f26a (1.4.4)"  # noqa: 501
                                ),
                            ),
                            UCTRecord.Patch(
                                patch_type="upstream",
                                entry=(
                                    "https://github.com/389ds/389-ds-base/commit/2e5b526012612d1d6ccace46398bee679a730271"  # noqa: 501
                                ),
                            ),
                        ],
                    ),
                    UCTRecord.Package(
                        name="linux-hwe",
                        statuses=[
                            UCTRecord.SeriesPackageStatus(
                                series="upstream",
                                status=UCTRecord.PackageStatus.RELEASED,
                                reason="5.17~rc1",
                                priority=None,
                            ),
                            UCTRecord.SeriesPackageStatus(
                                series="impish",
                                status=UCTRecord.PackageStatus.DOES_NOT_EXIST,
                                reason="",
                                priority=None,
                            ),
                            UCTRecord.SeriesPackageStatus(
                                series="devel",
                                status=UCTRecord.PackageStatus.DOES_NOT_EXIST,
                                reason="",
                                priority=None,
                            ),
                        ],
                        priority=UCTRecord.Priority.HIGH,
                        tags=set(),
                        patches=[],
                    ),
                ],
            ).__dict__,
            uct_record.__dict__,
        )

        output_dir = Path(self.makeTemporaryDirectory())
        saved_to_path = uct_record.save(output_dir)
        self.assertEqual(
            output_dir / "sampledata" / "CVE-2022-23222", saved_to_path
        )
        self.assertEqual(load_from.read_text(), saved_to_path.read_text())


class TestCVE(TestCaseWithFactory):
    layer = ZopelessDatabaseLayer
    maxDiff = None

    def setUp(self, *args, **kwargs):
        super().setUp(*args, **kwargs)
        celebrities = getUtility(ILaunchpadCelebrities)
        ubuntu = celebrities.ubuntu
        supported_series = self.factory.makeDistroSeries(
            distribution=ubuntu,
            status=SeriesStatus.SUPPORTED,
            name="focal",
        )
        current_series = self.factory.makeDistroSeries(
            distribution=ubuntu,
            status=SeriesStatus.CURRENT,
            name="jammy",
        )
        devel_series = self.factory.makeDistroSeries(
            distribution=ubuntu,
            status=SeriesStatus.DEVELOPMENT,
            name="kinetic",
        )
        dsp1 = self.factory.makeDistributionSourcePackage(distribution=ubuntu)
        dsp2 = self.factory.makeDistributionSourcePackage(distribution=ubuntu)
        product_1 = self.factory.makePackagingLink(
            sourcepackagename=dsp1.sourcepackagename,
            distroseries=current_series,
        ).productseries.product
        product_2 = self.factory.makePackagingLink(
            sourcepackagename=dsp2.sourcepackagename,
            distroseries=current_series,
        ).productseries.product

        assignee = self.factory.makePerson()

        self.uct_record = UCTRecord(
            parent_dir="active",
            assigned_to=assignee.name,
            bugs=["https://github.com/mm2/Little-CMS/issues/29"],
            cvss=[
                CVSS(
                    authority="nvd",
                    vector_string=(
                        "CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H "
                        "[7.8 HIGH]"
                    ),
                ),
            ],
            candidate="CVE-2022-23222",
            crd=datetime(2020, 1, 14, 8, 15, tzinfo=timezone.utc),
            public_date_at_USN=datetime(
                2021, 1, 14, 8, 15, tzinfo=timezone.utc
            ),
            public_date=datetime(2022, 1, 14, 8, 15, tzinfo=timezone.utc),
            description="description",
            discovered_by="tr3e wang",
            mitigation="mitigation",
            notes="author> text",
            priority=UCTRecord.Priority.CRITICAL,
            references=["https://ubuntu.com/security/notices/USN-5368-1"],
            ubuntu_description="ubuntu-description",
            packages=[
                UCTRecord.Package(
                    name=dsp1.sourcepackagename.name,
                    statuses=[
                        UCTRecord.SeriesPackageStatus(
                            series=supported_series.name,
                            status=UCTRecord.PackageStatus.NOT_AFFECTED,
                            reason="reason 1",
                            priority=UCTRecord.Priority.MEDIUM,
                        ),
                        UCTRecord.SeriesPackageStatus(
                            series=current_series.name,
                            status=UCTRecord.PackageStatus.RELEASED,
                            reason="reason 2",
                            priority=UCTRecord.Priority.MEDIUM,
                        ),
                        UCTRecord.SeriesPackageStatus(
                            series="devel",
                            status=UCTRecord.PackageStatus.RELEASED,
                            reason="reason 3",
                            priority=None,
                        ),
                        UCTRecord.SeriesPackageStatus(
                            series="upstream",
                            status=UCTRecord.PackageStatus.RELEASED,
                            reason="reason 4",
                            priority=None,
                        ),
                    ],
                    priority=None,
                    tags=set(),
                    patches=[
                        UCTRecord.Patch(
                            patch_type="upstream",
                            entry=(
                                "https://github.com/389ds/389-ds-base/"
                                "commit/123 (1.4.4)"
                            ),
                        ),
                        UCTRecord.Patch(
                            patch_type="upstream",
                            entry=(
                                "https://github.com/389ds/389-ds-base/"
                                "commit/456"
                            ),
                        ),
                    ],
                ),
                UCTRecord.Package(
                    name=dsp2.sourcepackagename.name,
                    statuses=[
                        UCTRecord.SeriesPackageStatus(
                            series=supported_series.name,
                            status=UCTRecord.PackageStatus.DOES_NOT_EXIST,
                            reason="",
                            priority=None,
                        ),
                        UCTRecord.SeriesPackageStatus(
                            series=current_series.name,
                            status=UCTRecord.PackageStatus.DOES_NOT_EXIST,
                            reason="",
                            priority=None,
                        ),
                        UCTRecord.SeriesPackageStatus(
                            series="devel",
                            status=UCTRecord.PackageStatus.RELEASED,
                            reason="",
                            priority=None,
                        ),
                        UCTRecord.SeriesPackageStatus(
                            series="upstream",
                            status=UCTRecord.PackageStatus.RELEASED,
                            reason="",
                            priority=None,
                        ),
                    ],
                    priority=UCTRecord.Priority.HIGH,
                    tags=set(),
                    patches=[],
                ),
            ],
        )

        self.cve = CVE(
            sequence="CVE-2022-23222",
            date_made_public=datetime(2022, 1, 14, 8, 15, tzinfo=timezone.utc),
            date_notice_issued=datetime(
                2021, 1, 14, 8, 15, tzinfo=timezone.utc
            ),
            date_coordinated_release=datetime(
                2020, 1, 14, 8, 15, tzinfo=timezone.utc
            ),
            distro_packages=[
                CVE.DistroPackage(
                    target=dsp1,
                    importance=None,
                    package_name=dsp1.sourcepackagename,
                ),
                CVE.DistroPackage(
                    target=dsp2,
                    importance=BugTaskImportance.HIGH,
                    package_name=dsp2.sourcepackagename,
                ),
            ],
            series_packages=[
                CVE.SeriesPackage(
                    target=SourcePackage(
                        sourcepackagename=dsp1.sourcepackagename,
                        distroseries=supported_series,
                    ),
                    package_name=dsp1.sourcepackagename,
                    importance=BugTaskImportance.MEDIUM,
                    status=BugTaskStatus.INVALID,
                    status_explanation="reason 1",
                ),
                CVE.SeriesPackage(
                    target=SourcePackage(
                        sourcepackagename=dsp1.sourcepackagename,
                        distroseries=current_series,
                    ),
                    package_name=dsp1.sourcepackagename,
                    importance=BugTaskImportance.MEDIUM,
                    status=BugTaskStatus.FIXRELEASED,
                    status_explanation="reason 2",
                ),
                CVE.SeriesPackage(
                    target=SourcePackage(
                        sourcepackagename=dsp1.sourcepackagename,
                        distroseries=devel_series,
                    ),
                    package_name=dsp1.sourcepackagename,
                    importance=None,
                    status=BugTaskStatus.FIXRELEASED,
                    status_explanation="reason 3",
                ),
                CVE.SeriesPackage(
                    target=SourcePackage(
                        sourcepackagename=dsp2.sourcepackagename,
                        distroseries=supported_series,
                    ),
                    package_name=dsp2.sourcepackagename,
                    importance=None,
                    status=BugTaskStatus.DOESNOTEXIST,
                    status_explanation="",
                ),
                CVE.SeriesPackage(
                    target=SourcePackage(
                        sourcepackagename=dsp2.sourcepackagename,
                        distroseries=current_series,
                    ),
                    package_name=dsp2.sourcepackagename,
                    importance=None,
                    status=BugTaskStatus.DOESNOTEXIST,
                    status_explanation="",
                ),
                CVE.SeriesPackage(
                    target=SourcePackage(
                        sourcepackagename=dsp2.sourcepackagename,
                        distroseries=devel_series,
                    ),
                    package_name=dsp2.sourcepackagename,
                    importance=None,
                    status=BugTaskStatus.FIXRELEASED,
                    status_explanation="",
                ),
            ],
            upstream_packages=[
                CVE.UpstreamPackage(
                    target=product_1,
                    package_name=dsp1.sourcepackagename,
                    importance=None,
                    status=BugTaskStatus.FIXRELEASED,
                    status_explanation="reason 4",
                ),
                CVE.UpstreamPackage(
                    target=product_2,
                    package_name=dsp2.sourcepackagename,
                    importance=None,
                    status=BugTaskStatus.FIXRELEASED,
                    status_explanation="",
                ),
            ],
            importance=BugTaskImportance.CRITICAL,
            status=VulnerabilityStatus.ACTIVE,
            assignee=assignee,
            discovered_by="tr3e wang",
            description="description",
            ubuntu_description="ubuntu-description",
            bug_urls=["https://github.com/mm2/Little-CMS/issues/29"],
            references=["https://ubuntu.com/security/notices/USN-5368-1"],
            notes="author> text",
            mitigation="mitigation",
            cvss=[
                CVSS(
                    authority="nvd",
                    vector_string=(
                        "CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H "
                        "[7.8 HIGH]"
                    ),
                ),
            ],
            patch_urls=[
                CVE.PatchURL(
                    package_name=dsp1.sourcepackagename,
                    type="upstream",
                    url="https://github.com/389ds/389-ds-base/" "commit/123",
                    notes="1.4.4",
                ),
                CVE.PatchURL(
                    package_name=dsp1.sourcepackagename,
                    type="upstream",
                    url="https://github.com/389ds/389-ds-base/" "commit/456",
                    notes=None,
                ),
            ],
        )

    def test_make_from_uct_record(self):
        cve = CVE.make_from_uct_record(self.uct_record)
        self.assertDictEqual(self.cve.__dict__, cve.__dict__)

    def test_to_uct_record(self):
        uct_record = self.cve.to_uct_record()
        self.assertListEqual(self.uct_record.packages, uct_record.packages)
        self.assertDictEqual(self.uct_record.__dict__, uct_record.__dict__)

    def test_get_distro_series_esm_patterns(self):
        ubuntu_esm = self.factory.makeDistribution(name="ubuntu-esm")
        xenial = self.factory.makeDistroSeries(
            distribution=ubuntu_esm, name="xenial"
        )
        precise = self.factory.makeDistroSeries(
            distribution=ubuntu_esm, name="precise"
        )
        self.assertEqual(xenial, CVE.get_distro_series("esm-infra/xenial"))
        self.assertEqual(precise, CVE.get_distro_series("precise/esm"))

    def test_get_patches(self):
        spn = self.factory.makeSourcePackageName()
        self.assertListEqual(
            [
                CVE.PatchURL(
                    package_name=spn,
                    url="https://github.com/repo/1",
                    type="upstream",
                    notes=None,
                ),
                CVE.PatchURL(
                    package_name=spn,
                    url="https://github.com/repo/2",
                    type="upstream",
                    notes="1.2.3",
                ),
            ],
            list(
                CVE.get_patch_urls(
                    spn,
                    [
                        UCTRecord.Patch("break-fix", "- -"),
                        UCTRecord.Patch(
                            "upstream", "https://github.com/repo/1"
                        ),
                        UCTRecord.Patch(
                            "upstream", "https://github.com/repo/2 (1.2.3)"
                        ),
                        UCTRecord.Patch("other", "foo"),
                    ],
                )
            ),
        )


class TestUCTImporterExporter(TestCaseWithFactory):
    maxDiff = None
    layer = ZopelessDatabaseLayer

    def setUp(self, *args, **kwargs):
        super().setUp(*args, **kwargs)
        celebrities = getUtility(ILaunchpadCelebrities)
        self.ubuntu = celebrities.ubuntu
        self.esm = self.factory.makeDistribution("ubuntu-esm")
        self.bug_importer = celebrities.bug_importer
        self.ubuntu_supported_series = self.factory.makeDistroSeries(
            distribution=self.ubuntu,
            status=SeriesStatus.SUPPORTED,
            name="focal",
        )
        self.ubuntu_current_series = self.factory.makeDistroSeries(
            distribution=self.ubuntu, status=SeriesStatus.CURRENT, name="jammy"
        )
        self.ubuntu_devel_series = self.factory.makeDistroSeries(
            distribution=self.ubuntu,
            status=SeriesStatus.DEVELOPMENT,
            name="kinetic",
        )
        self.esm_supported_series = self.factory.makeDistroSeries(
            distribution=self.esm,
            status=SeriesStatus.SUPPORTED,
            name="precise",
        )
        self.esm_current_series = self.factory.makeDistroSeries(
            distribution=self.esm,
            status=SeriesStatus.CURRENT,
            name="trusty",
        )
        self.ubuntu_package = self.factory.makeDistributionSourcePackage(
            distribution=self.ubuntu
        )
        self.esm_package = self.factory.makeDistributionSourcePackage(
            distribution=self.esm
        )
        self.product_1 = self.factory.makePackagingLink(
            sourcepackagename=self.ubuntu_package.sourcepackagename,
            distroseries=self.ubuntu_current_series,
        ).productseries.product
        self.product_2 = self.factory.makePackagingLink(
            sourcepackagename=self.esm_package.sourcepackagename,
            distroseries=self.esm_current_series,
        ).productseries.product

        for series in (
            self.ubuntu_supported_series,
            self.ubuntu_current_series,
        ):
            self.factory.makeSourcePackagePublishingHistory(
                distroseries=series,
                sourcepackagerelease=self.factory.makeSourcePackageRelease(
                    distroseries=series,
                    sourcepackagename=self.ubuntu_package.sourcepackagename,
                ),
            )
        # Note: The ubuntu-esm distribution does not have any source packages
        # published.

        self.lp_cve = self.factory.makeCVE("2022-23222")
        self.cve = CVE(
            sequence="CVE-2022-23222",
            date_made_public=datetime(2022, 1, 14, 8, 15, tzinfo=timezone.utc),
            date_notice_issued=datetime(
                2021, 1, 14, 8, 15, tzinfo=timezone.utc
            ),
            date_coordinated_release=datetime(
                2020, 1, 14, 8, 15, tzinfo=timezone.utc
            ),
            distro_packages=[
                CVE.DistroPackage(
                    target=self.ubuntu_package,
                    importance=BugTaskImportance.LOW,
                    package_name=self.ubuntu_package.sourcepackagename,
                ),
                CVE.DistroPackage(
                    target=self.esm_package,
                    importance=None,
                    package_name=self.esm_package.sourcepackagename,
                ),
            ],
            series_packages=[
                CVE.SeriesPackage(
                    target=SourcePackage(
                        sourcepackagename=self.ubuntu_package.sourcepackagename,  # noqa: E501
                        distroseries=self.ubuntu_supported_series,
                    ),
                    package_name=self.ubuntu_package.sourcepackagename,
                    importance=BugTaskImportance.HIGH,
                    status=BugTaskStatus.FIXRELEASED,
                    status_explanation="released",
                ),
                CVE.SeriesPackage(
                    target=SourcePackage(
                        sourcepackagename=self.ubuntu_package.sourcepackagename,  # noqa: E501
                        distroseries=self.ubuntu_current_series,
                    ),
                    package_name=self.ubuntu_package.sourcepackagename,
                    importance=None,
                    status=BugTaskStatus.DOESNOTEXIST,
                    status_explanation="does not exist",
                ),
                CVE.SeriesPackage(
                    target=SourcePackage(
                        sourcepackagename=self.ubuntu_package.sourcepackagename,  # noqa: E501
                        distroseries=self.ubuntu_devel_series,
                    ),
                    package_name=self.ubuntu_package.sourcepackagename,
                    importance=None,
                    status=BugTaskStatus.INVALID,
                    status_explanation="not affected",
                ),
                CVE.SeriesPackage(
                    target=SourcePackage(
                        sourcepackagename=self.esm_package.sourcepackagename,
                        distroseries=self.esm_supported_series,
                    ),
                    package_name=self.esm_package.sourcepackagename,
                    importance=None,
                    status=BugTaskStatus.WONTFIX,
                    status_explanation="ignored",
                ),
                CVE.SeriesPackage(
                    target=SourcePackage(
                        sourcepackagename=self.esm_package.sourcepackagename,
                        distroseries=self.esm_current_series,
                    ),
                    package_name=self.esm_package.sourcepackagename,
                    importance=None,
                    status=BugTaskStatus.UNKNOWN,
                    status_explanation="needs triage",
                ),
            ],
            upstream_packages=[
                CVE.UpstreamPackage(
                    target=self.product_1,
                    package_name=self.ubuntu_package.sourcepackagename,
                    importance=BugTaskImportance.HIGH,
                    status=BugTaskStatus.FIXRELEASED,
                    status_explanation="fix released",
                ),
                CVE.UpstreamPackage(
                    target=self.product_2,
                    package_name=self.esm_package.sourcepackagename,
                    importance=BugTaskImportance.LOW,
                    status=BugTaskStatus.WONTFIX,
                    status_explanation="ignored",
                ),
            ],
            importance=BugTaskImportance.MEDIUM,
            status=VulnerabilityStatus.ACTIVE,
            assignee=self.factory.makePerson(),
            discovered_by="tr3e wang",
            description="description",
            ubuntu_description="ubuntu-description",
            bug_urls=["https://github.com/mm2/Little-CMS/issues/29"],
            references=["https://ubuntu.com/security/notices/USN-5368-1"],
            notes="author> text",
            mitigation="mitigation",
            cvss=[
                CVSS(
                    authority="nvd",
                    vector_string=(
                        "CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H "
                        "[7.8 HIGH]"
                    ),
                ),
            ],
            patch_urls=[
                CVE.PatchURL(
                    package_name=self.ubuntu_package.sourcepackagename,
                    type="upstream",
                    url="https://github.com/389ds/389-ds-base/" "commit/123",
                    notes="1.4.4",
                ),
                CVE.PatchURL(
                    package_name=self.ubuntu_package.sourcepackagename,
                    type="upstream",
                    url="https://github.com/389ds/389-ds-base/" "commit/456",
                    notes=None,
                ),
            ],
        )
        self.importer = UCTImporter()
        self.exporter = UCTExporter()

    def checkBug(self, bug: Bug, cve: CVE):
        self.assertEqual(cve.sequence, bug.title)
        self.assertEqual(self.bug_importer, bug.owner)
        self.assertEqual(InformationType.PUBLICSECURITY, bug.information_type)

        expected_description = cve.description
        if cve.references:
            expected_description = "{}\n\nReferences:\n{}".format(
                expected_description, "\n".join(cve.references)
            )
        self.assertEqual(expected_description, bug.description)

        watches = list(bug.watches)
        self.assertEqual(len(cve.bug_urls), len(watches))
        self.assertEqual(sorted(cve.bug_urls), sorted(w.url for w in watches))

        self.checkBugAttachments(bug, cve)

    def checkBugTasks(self, bug: Bug, cve: CVE):
        bug_tasks = bug.bugtasks  # type: List[BugTask]

        self.assertEqual(
            len(cve.distro_packages)
            + len(cve.series_packages)
            + len(cve.upstream_packages),
            len(bug_tasks),
        )
        bug_tasks_by_target = {t.target: t for t in bug_tasks}

        package_importances = {}

        for distro_package in cve.distro_packages:
            self.assertIn(distro_package.target, bug_tasks_by_target)
            t = bug_tasks_by_target[distro_package.target]
            package_importance = distro_package.importance or cve.importance
            package_importances[
                distro_package.target.sourcepackagename.name
            ] = package_importance
            conjoined_primary = t.conjoined_primary
            if conjoined_primary:
                expected_importance = conjoined_primary.importance
                expected_status = conjoined_primary.status
            else:
                expected_importance = package_importance
                expected_status = BugTaskStatus.NEW
            self.assertEqual(expected_importance, t.importance)
            self.assertEqual(expected_status, t.status)
            self.assertIsNone(t.status_explanation)

        for series_package in cve.series_packages:
            self.assertIn(series_package.target, bug_tasks_by_target)
            t = bug_tasks_by_target[series_package.target]
            package_importance = package_importances[
                series_package.target.sourcepackagename.name
            ]
            sp_importance = series_package.importance or package_importance
            self.assertEqual(sp_importance, t.importance)
            self.assertEqual(series_package.status, t.status)
            self.assertEqual(
                series_package.status_explanation, t.status_explanation
            )

        for upstream_package in cve.upstream_packages:
            self.assertIn(upstream_package.target, bug_tasks_by_target)
            t = bug_tasks_by_target[upstream_package.target]
            package_importance = package_importances[
                upstream_package.package_name.name
            ]
            sp_importance = upstream_package.importance or package_importance
            self.assertEqual(sp_importance, t.importance)
            self.assertEqual(upstream_package.status, t.status)
            self.assertEqual(
                upstream_package.status_explanation, t.status_explanation
            )

        for t in bug_tasks:
            self.assertEqual(cve.assignee, t.assignee)

    def checkBugAttachments(self, bug: Bug, cve: CVE):
        attachments_by_url = {a.url: a for a in bug.attachments if a.url}
        for patch_url in cve.patch_urls:
            self.assertIn(patch_url.url, attachments_by_url)
            attachment = attachments_by_url[patch_url.url]
            expected_title = "{}/{}".format(
                patch_url.package_name.name, patch_url.type
            )
            if patch_url.notes:
                expected_title = "{}/{}".format(
                    expected_title, patch_url.notes
                )
            self.assertEqual(expected_title, attachment.title)

    def checkVulnerabilities(self, bug: Bug, cve: CVE):
        vulnerabilities = bug.vulnerabilities

        self.assertEqual(len(cve.affected_distributions), len(vulnerabilities))

        vulnerabilities_by_distro = {
            v.distribution: v for v in vulnerabilities
        }
        for distro in cve.affected_distributions:
            self.assertIn(distro, vulnerabilities_by_distro)
            vulnerability = vulnerabilities_by_distro[distro]

            self.assertEqual(self.bug_importer, vulnerability.creator)
            self.assertEqual(self.lp_cve, vulnerability.cve)
            self.assertEqual(cve.status, vulnerability.status)
            self.assertEqual(cve.ubuntu_description, vulnerability.description)
            self.assertEqual(cve.notes, vulnerability.notes)
            self.assertEqual(cve.mitigation, vulnerability.mitigation)
            self.assertEqual(cve.importance, vulnerability.importance)
            self.assertEqual(
                InformationType.PUBLICSECURITY, vulnerability.information_type
            )
            self.assertEqual(
                cve.date_made_public, vulnerability.date_made_public
            )
            self.assertEqual(
                cve.date_notice_issued, vulnerability.date_notice_issued
            )
            self.assertEqual(
                cve.date_coordinated_release,
                vulnerability.date_coordinated_release,
            )
            self.assertEqual([bug], vulnerability.bugs)

    def checkLaunchpadCve(self, lp_cve: CveModel, cve: CVE):
        self.assertDictEqual(
            {cvss.authority: cvss.vector_string for cvss in cve.cvss},
            lp_cve.cvss,
        )
        self.assertEqual(cve.discovered_by, lp_cve.discovered_by)

    def checkCVE(self, expected: CVE, actual: CVE):
        self.assertEqual(expected.sequence, actual.sequence)
        self.assertEqual(expected.date_made_public, actual.date_made_public)
        self.assertEqual(
            expected.date_notice_issued, actual.date_notice_issued
        )
        self.assertEqual(
            expected.date_coordinated_release, actual.date_coordinated_release
        )
        self.assertListEqual(expected.distro_packages, actual.distro_packages)
        self.assertListEqual(expected.series_packages, actual.series_packages)
        self.assertListEqual(
            expected.upstream_packages, actual.upstream_packages
        )
        self.assertEqual(expected.importance, actual.importance)
        self.assertEqual(expected.status, actual.status)
        self.assertEqual(expected.assignee, actual.assignee)
        self.assertEqual(expected.discovered_by, actual.discovered_by)
        self.assertEqual(expected.description, actual.description)
        self.assertEqual(
            expected.ubuntu_description, actual.ubuntu_description
        )
        self.assertListEqual(expected.bug_urls, actual.bug_urls)
        self.assertListEqual(expected.references, actual.references)
        self.assertEqual(expected.notes, actual.notes)
        self.assertEqual(expected.mitigation, actual.mitigation)
        self.assertListEqual(expected.cvss, actual.cvss)
        self.assertListEqual(expected.patch_urls, actual.patch_urls)

    def test_create_bug(self):
        bug = self.importer.create_bug(self.cve, self.lp_cve)

        self.checkBug(bug, self.cve)
        self.checkBugTasks(bug, self.cve)
        self.checkVulnerabilities(bug, self.cve)

        self.assertEqual([self.lp_cve], bug.cves)

        activities = list(bug.activity)
        self.assertEqual(6, len(activities))
        import_bug_activity = activities[-1]
        self.assertEqual(self.bug_importer, import_bug_activity.person)
        self.assertEqual("bug", import_bug_activity.whatchanged)
        self.assertEqual(
            "UCT CVE entry CVE-2022-23222", import_bug_activity.message
        )

    def test_create_bug_distribution_has_published_sources_false(self):
        distribution = self.factory.makeDistribution(
            name="no-published-sources"
        )
        self.assertFalse(distribution.has_published_sources)
        supported_series = self.factory.makeDistroSeries(
            distribution=distribution,
            status=SeriesStatus.SUPPORTED,
            name="supported-series",
        )
        current_series = self.factory.makeDistroSeries(
            distribution=distribution,
            status=SeriesStatus.CURRENT,
            name="current-series",
        )
        affected_package = self.factory.makeDistributionSourcePackage(
            distribution=distribution
        )
        cve = CVE(
            sequence="CVE-2022-1234",
            date_made_public=datetime(2022, 1, 1, 8, 15, tzinfo=timezone.utc),
            date_notice_issued=datetime(
                2021, 1, 1, 8, 15, tzinfo=timezone.utc
            ),
            date_coordinated_release=datetime(
                2020, 1, 1, 8, 15, tzinfo=timezone.utc
            ),
            distro_packages=[
                CVE.DistroPackage(
                    target=affected_package,
                    importance=BugTaskImportance.LOW,
                    package_name=affected_package.sourcepackagename,
                ),
            ],
            series_packages=[
                CVE.SeriesPackage(
                    target=SourcePackage(
                        sourcepackagename=affected_package.sourcepackagename,
                        distroseries=supported_series,
                    ),
                    package_name=affected_package.sourcepackagename,
                    importance=BugTaskImportance.HIGH,
                    status=BugTaskStatus.FIXRELEASED,
                    status_explanation="released",
                ),
                CVE.SeriesPackage(
                    target=SourcePackage(
                        sourcepackagename=affected_package.sourcepackagename,
                        distroseries=current_series,
                    ),
                    package_name=affected_package.sourcepackagename,
                    importance=None,
                    status=BugTaskStatus.DOESNOTEXIST,
                    status_explanation="does not exist",
                ),
            ],
            upstream_packages=[],
            importance=BugTaskImportance.MEDIUM,
            status=VulnerabilityStatus.ACTIVE,
            assignee=self.factory.makePerson(),
            discovered_by="tr3e wang",
            description="description",
            ubuntu_description="ubuntu-description",
            bug_urls=["https://github.com/mm2/Little-CMS/issues/29"],
            references=["https://ubuntu.com/security/notices/USN-5368-1"],
            notes="author> text",
            mitigation="mitigation",
            cvss=[
                CVSS(
                    authority="nvd",
                    vector_string=(
                        "CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H "
                        "[7.8 HIGH]"
                    ),
                ),
            ],
            patch_urls=[],
        )
        lp_cve = self.factory.makeCVE(sequence="2022-1234")
        bug = self.importer.create_bug(cve, lp_cve)
        self.checkBug(bug, cve)
        self.checkBugTasks(bug, cve)
        self.assertEqual([lp_cve], bug.cves)

    def test_find_existing_bug(self):
        self.assertIsNone(
            self.importer._find_existing_bug(self.cve, self.lp_cve)
        )
        bug = self.importer.create_bug(self.cve, self.lp_cve)
        self.assertEqual(
            self.importer._find_existing_bug(self.cve, self.lp_cve), bug
        )

    def test_find_existing_bug_multiple_bugs(self):
        bug = self.importer.create_bug(self.cve, self.lp_cve)
        another_bug = self.factory.makeBug(bug.bugtasks[0].target)
        self.assertGreater(len(bug.vulnerabilities), 1)
        vulnerability = bug.vulnerabilities[0]
        vulnerability.unlinkBug(bug)
        vulnerability.linkBug(another_bug)
        self.assertRaises(
            UCTImportError,
            self.importer._find_existing_bug,
            self.cve,
            self.lp_cve,
        )

    def test_update_bug_new_package(self):
        package = self.factory.makeDistributionSourcePackage(
            distribution=self.ubuntu
        )
        self.factory.makeSourcePackagePublishingHistory(
            distroseries=self.ubuntu_current_series,
            sourcepackagerelease=self.factory.makeSourcePackageRelease(
                distroseries=self.ubuntu_current_series,
                sourcepackagename=package.sourcepackagename,
            ),
        )

        cve = self.cve
        bug = self.importer.create_bug(cve, self.lp_cve)

        cve.distro_packages.append(
            CVE.DistroPackage(
                target=package,
                package_name=package.sourcepackagename,
                importance=BugTaskImportance.HIGH,
            )
        )
        cve.series_packages.append(
            CVE.SeriesPackage(
                target=SourcePackage(
                    sourcepackagename=package.sourcepackagename,
                    distroseries=self.ubuntu_current_series,
                ),
                package_name=package.sourcepackagename,
                importance=BugTaskImportance.CRITICAL,
                status=BugTaskStatus.FIXRELEASED,
                status_explanation="fix released",
            )
        )
        self.importer.update_bug(bug, cve, self.lp_cve)
        self.checkBugTasks(bug, cve)

    def test_update_bug_new_series(self):
        new_series = self.factory.makeDistroSeries(
            distribution=self.ubuntu, status=SeriesStatus.SUPPORTED
        )
        for package in (self.ubuntu_package, self.esm_package):
            self.factory.makeSourcePackagePublishingHistory(
                distroseries=new_series,
                sourcepackagerelease=self.factory.makeSourcePackageRelease(
                    distroseries=new_series,
                    sourcepackagename=package.sourcepackagename,
                ),
            )

        cve = self.cve
        bug = self.importer.create_bug(cve, self.lp_cve)

        cve.series_packages.append(
            CVE.SeriesPackage(
                target=SourcePackage(
                    sourcepackagename=self.ubuntu_package.sourcepackagename,
                    distroseries=new_series,
                ),
                package_name=self.ubuntu_package.sourcepackagename,
                importance=BugTaskImportance.CRITICAL,
                status=BugTaskStatus.FIXRELEASED,
                status_explanation="fix released",
            )
        )
        self.importer.update_bug(bug, cve, self.lp_cve)
        self.checkBugTasks(bug, cve)

    def test_update_bug_new_distro(self):
        new_distro = self.factory.makeDistribution(name="new-distro")
        new_series = self.factory.makeDistroSeries(
            distribution=new_distro, status=SeriesStatus.SUPPORTED
        )
        new_dsp = self.factory.makeDistributionSourcePackage(
            self.ubuntu_package.sourcepackagename, distribution=new_distro
        )
        self.factory.makeSourcePackagePublishingHistory(
            distroseries=new_series,
            sourcepackagerelease=self.factory.makeSourcePackageRelease(
                distroseries=new_series,
                sourcepackagename=new_dsp.sourcepackagename,
            ),
        )

        cve = self.cve
        bug = self.importer.create_bug(cve, self.lp_cve)

        cve.distro_packages.append(
            CVE.DistroPackage(
                target=new_dsp,
                package_name=new_dsp.sourcepackagename,
                importance=BugTaskImportance.HIGH,
            )
        )
        cve.series_packages.append(
            CVE.SeriesPackage(
                target=SourcePackage(
                    sourcepackagename=new_dsp.sourcepackagename,
                    distroseries=new_series,
                ),
                package_name=new_dsp.sourcepackagename,
                importance=BugTaskImportance.CRITICAL,
                status=BugTaskStatus.FIXRELEASED,
                status_explanation="fix released",
            )
        )
        clear_property_cache(cve)

        self.importer.update_bug(bug, cve, self.lp_cve)
        self.checkBugTasks(bug, cve)
        self.checkVulnerabilities(bug, cve)

    def test_update_bug_assignee_changed(self):
        bug = self.importer.create_bug(self.cve, self.lp_cve)
        cve = self.cve
        cve.assignee = self.factory.makePerson()
        self.importer.update_bug(bug, cve, self.lp_cve)
        self.checkBugTasks(bug, cve)

    def test_update_bug_cve_importance_changed(self):
        bug = self.importer.create_bug(self.cve, self.lp_cve)
        cve = self.cve
        self.assertNotEqual(cve.importance, BugTaskImportance.CRITICAL)
        cve.importance = BugTaskImportance.CRITICAL
        self.importer.update_bug(bug, cve, self.lp_cve)
        self.checkVulnerabilities(bug, cve)

    def test_update_bug_cve_status_changed(self):
        bug = self.importer.create_bug(self.cve, self.lp_cve)
        cve = self.cve
        self.assertNotEqual(cve.status, VulnerabilityStatus.IGNORED)
        cve.status = VulnerabilityStatus.IGNORED
        self.importer.update_bug(bug, cve, self.lp_cve)
        self.checkVulnerabilities(bug, cve)

    def test_update_bug_package_importance_changed(self):
        bug = self.importer.create_bug(self.cve, self.lp_cve)
        cve = self.cve
        self.assertNotEqual(
            cve.distro_packages[0].importance, BugTaskImportance.CRITICAL
        )
        self.assertNotEqual(
            cve.series_packages[0].importance, BugTaskImportance.CRITICAL
        )
        cve.distro_packages[0] = cve.distro_packages[0]._replace(
            importance=BugTaskImportance.CRITICAL,
        )
        cve.series_packages[0] = cve.series_packages[0]._replace(
            importance=BugTaskImportance.CRITICAL,
        )
        self.importer.update_bug(bug, cve, self.lp_cve)
        self.checkBugTasks(bug, cve)

    def test_update_bug_package_status_changed(self):
        bug = self.importer.create_bug(self.cve, self.lp_cve)
        cve = self.cve
        self.assertNotEqual(
            cve.series_packages[0].status, BugTaskStatus.DOESNOTEXIST
        )
        self.assertNotEqual(
            cve.series_packages[0].status_explanation, "does not exist"
        )
        cve.series_packages[0] = cve.series_packages[0]._replace(
            status=BugTaskStatus.DOESNOTEXIST,
            status_explanation="does not exist",
        )
        self.importer.update_bug(bug, cve, self.lp_cve)
        self.checkBugTasks(bug, cve)

    def test_update_bug_external_bugs_changed(self):
        bug = self.importer.create_bug(self.cve, self.lp_cve)
        cve = self.cve

        # Add new URL
        cve.bug_urls.append("https://github.com/mm2/Little-CMS/issues/29123")
        self.importer.update_bug(bug, cve, self.lp_cve)
        self.checkBug(bug, cve)

        # Remove URL
        cve.bug_urls.pop(0)
        self.importer.update_bug(bug, cve, self.lp_cve)
        self.checkBug(bug, cve)

    def test_update_bug_ubuntu_description_changed(self):
        bug = self.importer.create_bug(self.cve, self.lp_cve)
        cve = self.cve

        cve.ubuntu_description += "new"
        self.importer.update_bug(bug, cve, self.lp_cve)
        self.checkBug(bug, cve)

    def test_update_bug_references(self):
        bug = self.importer.create_bug(self.cve, self.lp_cve)
        cve = self.cve

        # Add new URL
        cve.references.append("https://github.com/mm2/Little-CMS/issues/29123")
        self.importer.update_bug(bug, cve, self.lp_cve)
        self.checkBug(bug, cve)

        # Remove URL
        cve.references.pop(0)
        self.importer.update_bug(bug, cve, self.lp_cve)
        self.checkBug(bug, cve)

    def test_update_patch_urls(self):
        bug = self.importer.create_bug(self.cve, self.lp_cve)
        cve = self.cve

        # Add new patch URL
        cve.patch_urls.append(
            CVE.PatchURL(
                package_name=cve.distro_packages[0].package_name,
                type="upstream",
                url="https://github.com/123",
                notes=None,
            )
        )
        self.importer.update_bug(bug, cve, self.lp_cve)
        self.checkBug(bug, cve)

    def test_import_cve(self):
        self.importer.import_cve(self.cve)
        self.assertIsNotNone(
            self.importer._find_existing_bug(self.cve, self.lp_cve)
        )
        self.checkLaunchpadCve(self.lp_cve, self.cve)

    def test_import_cve_dry_run(self):
        importer = UCTImporter(dry_run=True)
        importer.import_cve(self.cve)
        self.assertIsNone(importer._find_existing_bug(self.cve, self.lp_cve))

    def test_naive_dates(self):
        cve = self.cve
        cve.date_made_public = cve.date_made_public.replace(tzinfo=None)
        cve.date_notice_issued = cve.date_notice_issued.replace(tzinfo=None)
        cve.date_coordinated_release = cve.date_coordinated_release.replace(
            tzinfo=None
        )
        bug = self.importer.create_bug(cve, self.lp_cve)
        for date in (
            bug.vulnerabilities[0].date_made_public,
            bug.vulnerabilities[0].date_notice_issued,
            bug.vulnerabilities[0].date_coordinated_release,
        ):
            self.assertEqual(timezone.utc, date.tzinfo)
        self.importer.update_bug(bug, cve, self.lp_cve)
        for date in (
            bug.vulnerabilities[0].date_made_public,
            bug.vulnerabilities[0].date_notice_issued,
            bug.vulnerabilities[0].date_coordinated_release,
        ):
            self.assertEqual(timezone.utc, date.tzinfo)

    def test_make_cve_from_bug(self):
        self.importer.import_cve(self.cve)
        bug = self.importer._find_existing_bug(self.cve, self.lp_cve)
        cve = self.exporter._make_cve_from_bug(bug)
        self.checkCVE(self.cve, cve)

    def test_export_bug_to_uct_file(self):
        self.importer.import_cve(self.cve)
        bug = self.importer._find_existing_bug(self.cve, self.lp_cve)
        output_dir = Path(self.makeTemporaryDirectory())
        cve_path = self.exporter.export_bug_to_uct_file(bug.id, output_dir)
        uct_record = UCTRecord.load(cve_path)
        cve = CVE.make_from_uct_record(uct_record)
        self.checkCVE(self.cve, cve)
