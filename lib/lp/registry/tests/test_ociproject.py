# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `OCIProject` and `OCIProjectSet`."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type

from testtools.testcase import ExpectedException
from zope.component import getUtility
from zope.security.interfaces import Unauthorized

from lp.registry.interfaces.ociproject import (
    IOCIProject,
    IOCIProjectSet,
    )
from lp.registry.interfaces.ociprojectseries import IOCIProjectSeries
from lp.testing import (
    admin_logged_in,
    person_logged_in,
    TestCaseWithFactory,
    )
from lp.testing.layers import DatabaseFunctionalLayer


class TestOCIProject(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_implements_interface(self):
        oci_project = self.factory.makeOCIProject()
        with admin_logged_in():
            self.assertProvides(oci_project, IOCIProject)

    def test_newSeries(self):
        driver = self.factory.makePerson()
        distribution = self.factory.makeDistribution(driver=driver)
        registrant = self.factory.makePerson()
        oci_project = self.factory.makeOCIProject(pillar=distribution)
        with person_logged_in(driver):
            series = oci_project.newSeries(
                'test-series',
                'test-summary',
                registrant)
            self.assertProvides(series, IOCIProjectSeries)

    def test_newSeries_bad_permissions(self):
        distribution = self.factory.makeDistribution()
        registrant = self.factory.makePerson()
        oci_project = self.factory.makeOCIProject(pillar=distribution)
        with ExpectedException(Unauthorized):
            oci_project.newSeries(
                'test-series',
                'test-summary',
                registrant)

    def test_series(self):
        driver = self.factory.makePerson()
        distribution = self.factory.makeDistribution(driver=driver)
        first_oci_project = self.factory.makeOCIProject(pillar=distribution)
        second_oci_project = self.factory.makeOCIProject(pillar=distribution)
        with person_logged_in(driver):
            first_series = self.factory.makeOCIProjectSeries(
                oci_project=first_oci_project)
            self.factory.makeOCIProjectSeries(
                oci_project=second_oci_project)
            self.assertContentEqual([first_series], first_oci_project.series)

    def test_name(self):
        oci_project_name = self.factory.makeOCIProjectName(name='test-name')
        oci_project = self.factory.makeOCIProject(
            ociprojectname=oci_project_name)
        self.assertEqual('test-name', oci_project.name)

    def test_display_name(self):
        oci_project_name = self.factory.makeOCIProjectName(name='test-name')
        oci_project = self.factory.makeOCIProject(
            ociprojectname=oci_project_name)
        self.assertEqual(
            'OCI project test-name for %s' % oci_project.pillar.display_name,
            oci_project.display_name)


class TestOCIProjectSet(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_implements_interface(self):
        target_set = getUtility(IOCIProjectSet)
        with admin_logged_in():
            self.assertProvides(target_set, IOCIProjectSet)

    def test_new_oci_project(self):
        registrant = self.factory.makePerson()
        distribution = self.factory.makeDistribution(owner=registrant)
        oci_project_name = self.factory.makeOCIProjectName()
        target = getUtility(IOCIProjectSet).new(
            registrant,
            distribution,
            oci_project_name)
        with person_logged_in(registrant):
            self.assertEqual(target.registrant, registrant)
            self.assertEqual(target.distribution, distribution)
            self.assertEqual(target.pillar, distribution)
            self.assertEqual(target.ociprojectname, oci_project_name)

    def test_getByDistributionAndName(self):
        registrant = self.factory.makePerson()
        distribution = self.factory.makeDistribution(owner=registrant)
        oci_project = self.factory.makeOCIProject(
            registrant=registrant, pillar=distribution)

        # Make sure there's more than one to get the result from
        self.factory.makeOCIProject(
            pillar=self.factory.makeDistribution())

        with person_logged_in(registrant):
            fetched_result = getUtility(
                IOCIProjectSet).getByDistributionAndName(
                    distribution, oci_project.ociprojectname.name)
            self.assertEqual(oci_project, fetched_result)
