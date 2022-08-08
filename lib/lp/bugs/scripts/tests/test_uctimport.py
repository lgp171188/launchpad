#  Copyright 2022 Canonical Ltd.  This software is licensed under the
#  GNU Affero General Public License version 3 (see the file LICENSE).
import datetime
from pathlib import Path
from typing import List

from pytz import UTC
from zope.component import getUtility

from lp.app.enums import InformationType
from lp.app.interfaces.launchpad import ILaunchpadCelebrities
from lp.bugs.enums import VulnerabilityStatus
from lp.bugs.interfaces.bugtask import BugTaskImportance, BugTaskStatus
from lp.bugs.model.bug import Bug
from lp.bugs.model.bugtask import BugTask
from lp.bugs.model.cve import Cve as CveModel
from lp.bugs.scripts.uctimport import (
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
                public_date_at_USN=datetime.datetime(
                    2022, 1, 14, 8, 15, tzinfo=datetime.timezone.utc
                ),
                public_date=datetime.datetime(
                    2022, 1, 14, 8, 15, tzinfo=datetime.timezone.utc
                ),
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
                            UCTRecord.DistroSeriesPackageStatus(
                                distroseries="upstream",
                                status=UCTRecord.PackageStatus.RELEASED,
                                reason="5.17~rc1",
                                priority=None,
                            ),
                            UCTRecord.DistroSeriesPackageStatus(
                                distroseries="impish",
                                status=UCTRecord.PackageStatus.RELEASED,
                                reason="5.13.0-37.42",
                                priority=UCTRecord.Priority.MEDIUM,
                            ),
                            UCTRecord.DistroSeriesPackageStatus(
                                distroseries="devel",
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
                            )
                        ],
                    ),
                    UCTRecord.Package(
                        name="linux-hwe",
                        statuses=[
                            UCTRecord.DistroSeriesPackageStatus(
                                distroseries="upstream",
                                status=UCTRecord.PackageStatus.RELEASED,
                                reason="5.17~rc1",
                                priority=None,
                            ),
                            UCTRecord.DistroSeriesPackageStatus(
                                distroseries="impish",
                                status=UCTRecord.PackageStatus.DOES_NOT_EXIST,
                                reason="",
                                priority=None,
                            ),
                            UCTRecord.DistroSeriesPackageStatus(
                                distroseries="devel",
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


class TextCVE(TestCaseWithFactory):

    layer = ZopelessDatabaseLayer
    maxDiff = None

    def setUp(self, *args, **kwargs):
        super().setUp(*args, **kwargs)
        celebrities = getUtility(ILaunchpadCelebrities)
        ubuntu = celebrities.ubuntu
        supported_series = self.factory.makeDistroSeries(
            distribution=ubuntu, status=SeriesStatus.SUPPORTED
        )
        current_series = self.factory.makeDistroSeries(
            distribution=ubuntu, status=SeriesStatus.CURRENT
        )
        devel_series = self.factory.makeDistroSeries(
            distribution=ubuntu, status=SeriesStatus.DEVELOPMENT
        )
        dsp1 = self.factory.makeDistributionSourcePackage(distribution=ubuntu)
        dsp2 = self.factory.makeDistributionSourcePackage(distribution=ubuntu)
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
            crd=datetime.datetime(
                2020, 1, 14, 8, 15, tzinfo=datetime.timezone.utc
            ),
            public_date_at_USN=datetime.datetime(
                2021, 1, 14, 8, 15, tzinfo=datetime.timezone.utc
            ),
            public_date=datetime.datetime(
                2022, 1, 14, 8, 15, tzinfo=datetime.timezone.utc
            ),
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
                        UCTRecord.DistroSeriesPackageStatus(
                            distroseries=supported_series.name,
                            status=UCTRecord.PackageStatus.NOT_AFFECTED,
                            reason="reason 1",
                            priority=UCTRecord.Priority.MEDIUM,
                        ),
                        UCTRecord.DistroSeriesPackageStatus(
                            distroseries=current_series.name,
                            status=UCTRecord.PackageStatus.RELEASED,
                            reason="reason 2",
                            priority=UCTRecord.Priority.MEDIUM,
                        ),
                        UCTRecord.DistroSeriesPackageStatus(
                            distroseries="devel",
                            status=UCTRecord.PackageStatus.RELEASED,
                            reason="reason 3",
                            priority=None,
                        ),
                    ],
                    priority=None,
                    tags=set(),
                    patches=[],
                ),
                UCTRecord.Package(
                    name=dsp2.sourcepackagename.name,
                    statuses=[
                        UCTRecord.DistroSeriesPackageStatus(
                            distroseries=supported_series.name,
                            status=UCTRecord.PackageStatus.DOES_NOT_EXIST,
                            reason="",
                            priority=None,
                        ),
                        UCTRecord.DistroSeriesPackageStatus(
                            distroseries=current_series.name,
                            status=UCTRecord.PackageStatus.DOES_NOT_EXIST,
                            reason="",
                            priority=None,
                        ),
                        UCTRecord.DistroSeriesPackageStatus(
                            distroseries="devel",
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
            crd=datetime.datetime(
                2020, 1, 14, 8, 15, tzinfo=datetime.timezone.utc
            ),
            public_date_at_USN=datetime.datetime(
                2021, 1, 14, 8, 15, tzinfo=datetime.timezone.utc
            ),
            public_date=datetime.datetime(
                2022, 1, 14, 8, 15, tzinfo=datetime.timezone.utc
            ),
            distro_packages=[
                CVE.DistroPackage(
                    package=dsp1,
                    importance=None,
                ),
                CVE.DistroPackage(
                    package=dsp2,
                    importance=BugTaskImportance.HIGH,
                ),
            ],
            series_packages=[
                CVE.SeriesPackage(
                    package=SourcePackage(
                        sourcepackagename=dsp1.sourcepackagename,
                        distroseries=supported_series,
                    ),
                    importance=BugTaskImportance.MEDIUM,
                    status=BugTaskStatus.INVALID,
                    status_explanation="reason 1",
                ),
                CVE.SeriesPackage(
                    package=SourcePackage(
                        sourcepackagename=dsp1.sourcepackagename,
                        distroseries=current_series,
                    ),
                    importance=BugTaskImportance.MEDIUM,
                    status=BugTaskStatus.FIXRELEASED,
                    status_explanation="reason 2",
                ),
                CVE.SeriesPackage(
                    package=SourcePackage(
                        sourcepackagename=dsp1.sourcepackagename,
                        distroseries=devel_series,
                    ),
                    importance=None,
                    status=BugTaskStatus.FIXRELEASED,
                    status_explanation="reason 3",
                ),
                CVE.SeriesPackage(
                    package=SourcePackage(
                        sourcepackagename=dsp2.sourcepackagename,
                        distroseries=supported_series,
                    ),
                    importance=None,
                    status=BugTaskStatus.DOESNOTEXIST,
                    status_explanation="",
                ),
                CVE.SeriesPackage(
                    package=SourcePackage(
                        sourcepackagename=dsp2.sourcepackagename,
                        distroseries=current_series,
                    ),
                    importance=None,
                    status=BugTaskStatus.DOESNOTEXIST,
                    status_explanation="",
                ),
                CVE.SeriesPackage(
                    package=SourcePackage(
                        sourcepackagename=dsp2.sourcepackagename,
                        distroseries=devel_series,
                    ),
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
        )

    def test_make_from_uct_record(self):
        cve = CVE.make_from_uct_record(self.uct_record)
        self.assertDictEqual(self.cve.__dict__, cve.__dict__)

    def test_to_uct_record(self):
        uct_record = self.cve.to_uct_record()
        self.assertListEqual(self.uct_record.packages, uct_record.packages)
        self.assertDictEqual(self.uct_record.__dict__, uct_record.__dict__)


class TestUCTImporter(TestCaseWithFactory):

    maxDiff = None
    layer = ZopelessDatabaseLayer

    def setUp(self, *args, **kwargs):
        super().setUp(*args, **kwargs)
        celebrities = getUtility(ILaunchpadCelebrities)
        self.ubuntu = celebrities.ubuntu
        self.esm = self.factory.makeDistribution("esm")
        self.bug_importer = celebrities.bug_importer
        self.ubuntu_supported_series = self.factory.makeDistroSeries(
            distribution=self.ubuntu, status=SeriesStatus.SUPPORTED
        )
        self.ubuntu_current_series = self.factory.makeDistroSeries(
            distribution=self.ubuntu, status=SeriesStatus.CURRENT
        )
        self.ubuntu_devel_series = self.factory.makeDistroSeries(
            distribution=self.ubuntu, status=SeriesStatus.DEVELOPMENT
        )
        self.esm_supported_series = self.factory.makeDistroSeries(
            distribution=self.esm, status=SeriesStatus.SUPPORTED
        )
        self.esm_current_series = self.factory.makeDistroSeries(
            distribution=self.esm, status=SeriesStatus.CURRENT
        )
        self.ubuntu_package = self.factory.makeDistributionSourcePackage(
            distribution=self.ubuntu
        )
        self.esm_package = self.factory.makeDistributionSourcePackage(
            distribution=self.esm
        )
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

        for series in (self.esm_current_series, self.esm_supported_series):
            self.factory.makeSourcePackagePublishingHistory(
                distroseries=series,
                sourcepackagerelease=self.factory.makeSourcePackageRelease(
                    distroseries=series,
                    sourcepackagename=self.esm_package.sourcepackagename,
                ),
            )

        self.lp_cve = self.factory.makeCVE("2022-23222")
        self.now = datetime.datetime.now(datetime.timezone.utc)
        self.cve = CVE(
            sequence="CVE-2022-23222",
            crd=None,
            public_date=self.now,
            public_date_at_USN=None,
            distro_packages=[
                CVE.DistroPackage(
                    package=self.ubuntu_package,
                    importance=BugTaskImportance.LOW,
                ),
                CVE.DistroPackage(
                    package=self.esm_package,
                    importance=None,
                ),
            ],
            series_packages=[
                CVE.SeriesPackage(
                    package=SourcePackage(
                        sourcepackagename=self.ubuntu_package.sourcepackagename,  # noqa: E501
                        distroseries=self.ubuntu_supported_series,
                    ),
                    importance=BugTaskImportance.HIGH,
                    status=BugTaskStatus.FIXRELEASED,
                    status_explanation="released",
                ),
                CVE.SeriesPackage(
                    package=SourcePackage(
                        sourcepackagename=self.ubuntu_package.sourcepackagename,  # noqa: E501
                        distroseries=self.ubuntu_current_series,
                    ),
                    importance=None,
                    status=BugTaskStatus.DOESNOTEXIST,
                    status_explanation="does not exist",
                ),
                CVE.SeriesPackage(
                    package=SourcePackage(
                        sourcepackagename=self.ubuntu_package.sourcepackagename,  # noqa: E501
                        distroseries=self.ubuntu_devel_series,
                    ),
                    importance=None,
                    status=BugTaskStatus.INVALID,
                    status_explanation="not affected",
                ),
                CVE.SeriesPackage(
                    package=SourcePackage(
                        sourcepackagename=self.esm_package.sourcepackagename,
                        distroseries=self.esm_supported_series,
                    ),
                    importance=None,
                    status=BugTaskStatus.WONTFIX,
                    status_explanation="ignored",
                ),
                CVE.SeriesPackage(
                    package=SourcePackage(
                        sourcepackagename=self.esm_package.sourcepackagename,
                        distroseries=self.esm_current_series,
                    ),
                    importance=None,
                    status=BugTaskStatus.UNKNOWN,
                    status_explanation="needs triage",
                ),
            ],
            importance=BugTaskImportance.MEDIUM,
            status=VulnerabilityStatus.ACTIVE,
            assignee=self.factory.makePerson(),
            discovered_by="",
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
        )
        self.importer = UCTImporter()

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

    def checkBugTasks(self, bug: Bug, cve: CVE):
        bug_tasks = bug.bugtasks  # type: List[BugTask]

        self.assertEqual(
            len(cve.distro_packages) + len(cve.series_packages), len(bug_tasks)
        )
        bug_tasks_by_target = {t.target: t for t in bug_tasks}

        package_importances = {}

        for distro_package in cve.distro_packages:
            self.assertIn(distro_package.package, bug_tasks_by_target)
            t = bug_tasks_by_target[distro_package.package]
            package_importance = distro_package.importance or cve.importance
            package_importances[
                distro_package.package.sourcepackagename
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
            self.assertIn(series_package.package, bug_tasks_by_target)
            t = bug_tasks_by_target[series_package.package]
            package_importance = package_importances[
                series_package.package.sourcepackagename
            ]
            sp_importance = series_package.importance or package_importance
            self.assertEqual(sp_importance, t.importance)
            self.assertEqual(series_package.status, t.status)
            self.assertEqual(
                series_package.status_explanation, t.status_explanation
            )

        for t in bug_tasks:
            self.assertEqual(cve.assignee, t.assignee)

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
            self.assertEqual([bug], vulnerability.bugs)

    def checkLaunchpadCve(self, lp_cve: CveModel, cve: CVE):
        self.assertDictEqual(
            {cvss.authority: cvss.vector_string for cvss in cve.cvss},
            lp_cve.cvss,
        )

    def test_create_bug(self):
        bug = self.importer.create_bug(self.cve, self.lp_cve)

        self.checkBug(bug, self.cve)
        self.checkBugTasks(bug, self.cve)
        self.checkVulnerabilities(bug, self.cve)

        self.assertEqual([self.lp_cve], bug.cves)

        activities = list(bug.activity)
        self.assertEqual(4, len(activities))
        import_bug_activity = activities[-1]
        self.assertEqual(self.bug_importer, import_bug_activity.person)
        self.assertEqual("bug", import_bug_activity.whatchanged)
        self.assertEqual(
            "UCT CVE entry CVE-2022-23222", import_bug_activity.message
        )

    def test_find_existing_bug(self):
        self.assertIsNone(
            self.importer.find_existing_bug(self.cve, self.lp_cve)
        )
        bug = self.importer.create_bug(self.cve, self.lp_cve)
        self.assertEqual(
            self.importer.find_existing_bug(self.cve, self.lp_cve), bug
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
            self.importer.find_existing_bug,
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
                package=package,
                importance=BugTaskImportance.HIGH,
            )
        )
        cve.series_packages.append(
            CVE.SeriesPackage(
                package=SourcePackage(
                    sourcepackagename=package.sourcepackagename,
                    distroseries=self.ubuntu_current_series,
                ),
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
                package=SourcePackage(
                    sourcepackagename=self.ubuntu_package.sourcepackagename,
                    distroseries=new_series,
                ),
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
                package=new_dsp,
                importance=BugTaskImportance.HIGH,
            )
        )
        cve.series_packages.append(
            CVE.SeriesPackage(
                package=SourcePackage(
                    sourcepackagename=new_dsp.sourcepackagename,
                    distroseries=new_series,
                ),
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

    def test_import_cve(self):
        self.importer.import_cve(self.cve)
        self.assertIsNotNone(
            self.importer.find_existing_bug(self.cve, self.lp_cve)
        )
        self.checkLaunchpadCve(self.lp_cve, self.cve)

    def test_import_cve_dry_run(self):
        importer = UCTImporter(dry_run=True)
        importer.import_cve(self.cve)
        self.assertIsNone(importer.find_existing_bug(self.cve, self.lp_cve))

    def test_naive_date_made_public(self):
        cve = self.cve
        cve.public_date = cve.public_date.replace(tzinfo=None)
        bug = self.importer.create_bug(cve, self.lp_cve)
        self.assertEqual(
            UTC,
            bug.vulnerabilities[0].date_made_public.tzinfo,
        )

    def test_make_cve_from_bug(self):
        exporter = UCTExporter()
        self.importer.import_cve(self.cve)
        bug = self.importer.find_existing_bug(self.cve, self.lp_cve)
        cve = exporter.make_cve_from_bug(bug)
        self.assertEqual(self.cve.sequence, cve.sequence)
        self.assertEqual(self.cve.crd, cve.crd)
        self.assertEqual(self.cve.public_date, cve.public_date)
        self.assertEqual(self.cve.public_date_at_USN, cve.public_date_at_USN)
        self.assertListEqual(self.cve.distro_packages, cve.distro_packages)
        self.assertListEqual(self.cve.series_packages, cve.series_packages)
        self.assertEqual(self.cve.importance, cve.importance)
        self.assertEqual(self.cve.status, cve.status)
        self.assertEqual(self.cve.assignee, cve.assignee)
        self.assertEqual(self.cve.discovered_by, cve.discovered_by)
        self.assertEqual(self.cve.description, cve.description)
        self.assertEqual(self.cve.ubuntu_description, cve.ubuntu_description)
        self.assertListEqual(self.cve.bug_urls, cve.bug_urls)
        self.assertListEqual(self.cve.references, cve.references)
        self.assertEqual(self.cve.notes, cve.notes)
        self.assertEqual(self.cve.mitigation, cve.mitigation)
        self.assertListEqual(self.cve.cvss, cve.cvss)
