#  Copyright 2022 Canonical Ltd.  This software is licensed under the
#  GNU Affero General Public License version 3 (see the file LICENSE).
import datetime
from pathlib import Path

from zope.component import getUtility

from lp.app.enums import InformationType
from lp.app.interfaces.launchpad import ILaunchpadCelebrities
from lp.bugs.enums import VulnerabilityStatus
from lp.bugs.interfaces.bugtask import BugTaskImportance, BugTaskStatus
from lp.bugs.scripts.uctimport import CVE, UCTImporter, UCTRecord
from lp.registry.interfaces.series import SeriesStatus
from lp.registry.model.sourcepackage import SourcePackage
from lp.testing import TestCase, TestCaseWithFactory
from lp.testing.layers import ZopelessDatabaseLayer


class TestUCTRecord(TestCase):
    def test_load(self):
        cve_path = Path(__file__).parent / "sampledata" / "CVE-2022-23222"
        uct_record = UCTRecord.load(cve_path)
        self.assertEqual(
            uct_record,
            UCTRecord(
                path=cve_path,
                assigned_to="",
                bugs=[
                    "https://github.com/mm2/Little-CMS/issues/29",
                    "https://github.com/mm2/Little-CMS/issues/30",
                    "https://bugs.debian.org/cgi-bin/bugreport.cgi?bug=745471",
                ],
                cvss=[
                    {
                        "source": "nvd",
                        "vector": (
                            "CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H"
                        ),
                        "baseScore": "7.8",
                        "baseSeverity": "HIGH",
                    }
                ],
                candidate="CVE-2022-23222",
                date_made_public=datetime.datetime(
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
                notes=[
                    UCTRecord.Note(
                        author="sbeattie",
                        text=(
                            "Ubuntu 21.10 / 5.13+ kernels disable "
                            "unprivileged BPF by default.\nkernels 5.8 and "
                            "older are not affected, priority high is "
                            "for\n5.10 and 5.11 based kernels only"
                        ),
                    ),
                ],
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
                                distroseries="devel",
                                status=UCTRecord.PackageStatus.NOT_AFFECTED,
                                reason="5.15.0-25.25",
                                priority=UCTRecord.Priority.MEDIUM,
                            ),
                            UCTRecord.DistroSeriesPackageStatus(
                                distroseries="impish",
                                status=UCTRecord.PackageStatus.RELEASED,
                                reason="5.13.0-37.42",
                                priority=UCTRecord.Priority.MEDIUM,
                            ),
                            UCTRecord.DistroSeriesPackageStatus(
                                distroseries="upstream",
                                status=UCTRecord.PackageStatus.RELEASED,
                                reason="5.17~rc1",
                                priority=None,
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
                                distroseries="devel",
                                status=UCTRecord.PackageStatus.DOES_NOT_EXIST,
                                reason="",
                                priority=None,
                            ),
                            UCTRecord.DistroSeriesPackageStatus(
                                distroseries="impish",
                                status=UCTRecord.PackageStatus.DOES_NOT_EXIST,
                                reason="",
                                priority=None,
                            ),
                            UCTRecord.DistroSeriesPackageStatus(
                                distroseries="upstream",
                                status=UCTRecord.PackageStatus.RELEASED,
                                reason="5.17~rc1",
                                priority=None,
                            ),
                        ],
                        priority=UCTRecord.Priority.HIGH,
                        tags=set(),
                        patches=[],
                    ),
                ],
            ),
        )


class TextCVE(TestCaseWithFactory):

    layer = ZopelessDatabaseLayer

    def test_make_from_uct_record(self):
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

        uct_record = UCTRecord(
            path=Path("./active/CVE-2022-23222"),
            assigned_to="assignee",
            bugs=["https://github.com/mm2/Little-CMS/issues/29"],
            cvss=[],
            candidate="CVE-2022-23222",
            date_made_public=datetime.datetime(
                2022, 1, 14, 8, 15, tzinfo=datetime.timezone.utc
            ),
            description="description",
            discovered_by="tr3e wang",
            mitigation="mitigation",
            notes=[
                UCTRecord.Note(
                    author="author",
                    text="text",
                ),
            ],
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
        cve = CVE.make_from_uct_record(uct_record)
        self.assertEqual(cve.sequence, "CVE-2022-23222")
        self.assertEqual(
            cve.date_made_public,
            datetime.datetime(
                2022, 1, 14, 8, 15, tzinfo=datetime.timezone.utc
            ),
        )
        self.assertEqual(
            cve.distro_packages,
            [
                CVE.DistroPackage(
                    package=dsp1,
                    importance=BugTaskImportance.CRITICAL,
                ),
                CVE.DistroPackage(
                    package=dsp2,
                    importance=BugTaskImportance.HIGH,
                ),
            ],
        )
        self.assertEqual(
            cve.series_packages,
            [
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
                    importance=BugTaskImportance.CRITICAL,
                    status=BugTaskStatus.FIXRELEASED,
                    status_explanation="reason 3",
                ),
                CVE.SeriesPackage(
                    package=SourcePackage(
                        sourcepackagename=dsp2.sourcepackagename,
                        distroseries=supported_series,
                    ),
                    importance=BugTaskImportance.HIGH,
                    status=BugTaskStatus.DOESNOTEXIST,
                    status_explanation="",
                ),
                CVE.SeriesPackage(
                    package=SourcePackage(
                        sourcepackagename=dsp2.sourcepackagename,
                        distroseries=current_series,
                    ),
                    importance=BugTaskImportance.HIGH,
                    status=BugTaskStatus.DOESNOTEXIST,
                    status_explanation="",
                ),
                CVE.SeriesPackage(
                    package=SourcePackage(
                        sourcepackagename=dsp2.sourcepackagename,
                        distroseries=devel_series,
                    ),
                    importance=BugTaskImportance.HIGH,
                    status=BugTaskStatus.FIXRELEASED,
                    status_explanation="",
                ),
            ],
        )
        self.assertEqual(cve.importance, BugTaskImportance.CRITICAL)
        self.assertEqual(cve.status, VulnerabilityStatus.ACTIVE)
        self.assertEqual(cve.assigned_to, "assignee")
        self.assertEqual(cve.description, "description")
        self.assertEqual(cve.ubuntu_description, "ubuntu-description")
        self.assertEqual(
            cve.bug_urls, ["https://github.com/mm2/Little-CMS/issues/29"]
        )
        self.assertEqual(
            cve.references, ["https://ubuntu.com/security/notices/USN-5368-1"]
        )
        self.assertEqual(cve.notes, "author> text")
        self.assertEqual(cve.mitigation, "mitigation")


class TestUCTImporter(TestCaseWithFactory):

    layer = ZopelessDatabaseLayer

    def setUp(self, *args, **kwargs):
        super().setUp(*args, **kwargs)
        self.importer = UCTImporter()

    def test_create_bug(self):
        celebrities = getUtility(ILaunchpadCelebrities)
        ubuntu = celebrities.ubuntu
        owner = celebrities.bug_importer
        assignee = self.factory.makePerson()
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
        lp_cve = self.factory.makeCVE("2022-23222")

        for package in (dsp1, dsp2):
            for series in (supported_series, current_series):
                self.factory.makeSourcePackagePublishingHistory(
                    distroseries=series,
                    sourcepackagerelease=self.factory.makeSourcePackageRelease(
                        distroseries=series,
                        sourcepackagename=package.sourcepackagename,
                    ),
                )

        now = datetime.datetime.now(datetime.timezone.utc)
        cve = CVE(
            sequence="CVE-2022-23222",
            date_made_public=now,
            distro_packages=[
                CVE.DistroPackage(
                    package=dsp1,
                    importance=BugTaskImportance.LOW,
                ),
                CVE.DistroPackage(
                    package=dsp2,
                    importance=BugTaskImportance.MEDIUM,
                ),
            ],
            series_packages=[
                CVE.SeriesPackage(
                    package=SourcePackage(
                        sourcepackagename=dsp1.sourcepackagename,
                        distroseries=supported_series,
                    ),
                    importance=BugTaskImportance.HIGH,
                    status=BugTaskStatus.FIXRELEASED,
                    status_explanation="released",
                ),
                CVE.SeriesPackage(
                    package=SourcePackage(
                        sourcepackagename=dsp1.sourcepackagename,
                        distroseries=current_series,
                    ),
                    importance=BugTaskImportance.LOW,
                    status=BugTaskStatus.DOESNOTEXIST,
                    status_explanation="does not exist",
                ),
                CVE.SeriesPackage(
                    package=SourcePackage(
                        sourcepackagename=dsp2.sourcepackagename,
                        distroseries=supported_series,
                    ),
                    importance=BugTaskImportance.LOW,
                    status=BugTaskStatus.INVALID,
                    status_explanation="not affected",
                ),
                CVE.SeriesPackage(
                    package=SourcePackage(
                        sourcepackagename=dsp2.sourcepackagename,
                        distroseries=current_series,
                    ),
                    importance=BugTaskImportance.MEDIUM,
                    status=BugTaskStatus.WONTFIX,
                    status_explanation="ignored",
                ),
                CVE.SeriesPackage(
                    package=SourcePackage(
                        sourcepackagename=dsp2.sourcepackagename,
                        distroseries=devel_series,
                    ),
                    importance=BugTaskImportance.MEDIUM,
                    status=BugTaskStatus.UNKNOWN,
                    status_explanation="needs triage",
                ),
            ],
            importance=BugTaskImportance.MEDIUM,
            status=VulnerabilityStatus.ACTIVE,
            assigned_to=assignee.name,
            description="description",
            ubuntu_description="ubuntu-description",
            bug_urls=["https://github.com/mm2/Little-CMS/issues/29"],
            references=["https://ubuntu.com/security/notices/USN-5368-1"],
            notes="author> text",
            mitigation="mitigation",
        )

        bug, vulnerabilities = self.importer.create_bug(cve, lp_cve)

        self.assertEqual(bug.title, "CVE-2022-23222")
        self.assertEqual(bug.description, "ubuntu-description")
        self.assertEqual(bug.owner, owner)
        self.assertEqual(bug.information_type, InformationType.PUBLICSECURITY)

        messages = list(bug.messages)
        self.assertEqual(len(messages), 3)

        message = messages.pop(0)
        self.assertEqual(message.owner, owner)
        self.assertEqual(message.text_contents, "description")

        for external_bug_url in cve.bug_urls:
            message = messages.pop(0)
            self.assertEqual(message.text_contents, external_bug_url)

        for reference in cve.references:
            message = messages.pop(0)
            self.assertEqual(message.text_contents, reference)

        bug_tasks = bug.bugtasks
        # 7 bug tasks are supposed to be created:
        #   2 for distro packages
        #   5 for combinations of distroseries/package:
        #     2 for the first package (2 distro series)
        #     3 for the second package (3 distro series)
        self.assertEqual(len(bug_tasks), 7)

        for bug_task in bug_tasks:
            self.assertEqual(bug_task.assignee, assignee)

        bug_tasks_by_target = {
            (t.distribution, t.distroseries, t.sourcepackagename): t
            for t in bug_tasks
        }
        t = bug_tasks_by_target.pop((ubuntu, None, dsp1.sourcepackagename))
        self.assertEqual(t.importance, BugTaskImportance.LOW)
        self.assertEqual(t.status, BugTaskStatus.NEW)
        self.assertEqual(t.status_explanation, None)

        t = bug_tasks_by_target.pop((ubuntu, None, dsp2.sourcepackagename))
        self.assertEqual(t.importance, BugTaskImportance.MEDIUM)
        self.assertEqual(t.status, BugTaskStatus.UNKNOWN)
        self.assertEqual(t.status_explanation, None)

        t = bug_tasks_by_target.pop(
            (None, supported_series, dsp1.sourcepackagename)
        )
        self.assertEqual(t.importance, BugTaskImportance.HIGH)
        self.assertEqual(t.status, BugTaskStatus.FIXRELEASED)
        self.assertEqual(t.status_explanation, "released")

        t = bug_tasks_by_target.pop(
            (None, current_series, dsp1.sourcepackagename)
        )
        self.assertEqual(t.importance, BugTaskImportance.LOW)
        self.assertEqual(t.status, BugTaskStatus.DOESNOTEXIST)
        self.assertEqual(t.status_explanation, "does not exist")

        t = bug_tasks_by_target.pop(
            (None, supported_series, dsp2.sourcepackagename)
        )
        self.assertEqual(t.importance, BugTaskImportance.LOW)
        self.assertEqual(t.status, BugTaskStatus.INVALID)
        self.assertEqual(t.status_explanation, "not affected")

        t = bug_tasks_by_target.pop(
            (None, current_series, dsp2.sourcepackagename)
        )
        self.assertEqual(t.importance, BugTaskImportance.MEDIUM)
        self.assertEqual(t.status, BugTaskStatus.WONTFIX)
        self.assertEqual(t.status_explanation, "ignored")

        t = bug_tasks_by_target.pop(
            (None, devel_series, dsp2.sourcepackagename)
        )
        self.assertEqual(t.importance, BugTaskImportance.MEDIUM)
        self.assertEqual(t.status, BugTaskStatus.UNKNOWN)
        self.assertEqual(t.status_explanation, "needs triage")

        self.assertEqual(bug.cves, [lp_cve])

        activities = list(bug.activity)
        self.assertEqual(len(activities), 14)
        import_bug_activity = activities[-1]
        self.assertEqual(import_bug_activity.person, owner)
        self.assertEqual(import_bug_activity.whatchanged, "bug")
        self.assertEqual(
            import_bug_activity.message, "UCT CVE entry CVE-2022-23222"
        )

        self.assertEqual(len(vulnerabilities), 1)

        vulnerability = vulnerabilities[0]
        self.assertEqual(vulnerability.distribution, ubuntu)
        self.assertEqual(vulnerability.creator, owner)
        self.assertEqual(vulnerability.cve, lp_cve)
        self.assertEqual(vulnerability.status, VulnerabilityStatus.ACTIVE)
        self.assertEqual(vulnerability.description, "description")
        self.assertEqual(vulnerability.notes, "author> text")
        self.assertEqual(vulnerability.mitigation, "mitigation")
        self.assertEqual(vulnerability.importance, BugTaskImportance.MEDIUM)
        self.assertEqual(
            vulnerability.information_type, InformationType.PUBLICSECURITY
        )
        self.assertEqual(vulnerability.date_made_public, now)
        self.assertEqual(vulnerability.bugs, [bug])
