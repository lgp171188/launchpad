# -*- coding: utf-8 -*-
# NOTE: The first line above must stay first; do not move the copyright
# notice to the top.  See http://www.python.org/dev/peps/pep-0263/.
#
# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for Close Account Celery Job."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type

from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.registry.interfaces.person import IPersonSet
from lp.registry.model.closeaccount import ICloseAccountJobSource
from lp.services.job.interfaces.job import JobStatus
from lp.testing import TestCaseWithFactory
from lp.services.job.runner import JobRunner

from lp.testing.dbuser import dbuser
from lp.testing.layers import (
    DatabaseFunctionalLayer,
    )
from lp.services.config import config


class TestGitRepositoryRescan(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_close_account_job_nonexistent_username(self):
        # The job completes with the expected exception logged:
        # states that the user does not exist in LP
        job_source = getUtility(ICloseAccountJobSource)
        jobs = list(job_source.iterReady())

        # at this point we have no jobs
        self.assertEqual([], jobs)

        getUtility(ICloseAccountJobSource).create('nonexistent_username')
        jobs = list(job_source.iterReady())
        jobs[0] = removeSecurityProxy(jobs[0])
        with dbuser(config.ICloseAccountJobSource.dbuser):
            JobRunner(jobs).runAll()

        self.assertEqual(JobStatus.COMPLETED, jobs[0].status)
        self.assertEqual(u'User nonexistent_username does not exist',
                         jobs[0].context.exception)

    def test_close_account_job_valid_username(self):
        # The job completes and the username is now anonymized
        user_to_delete = self.factory.makePerson(name='delete-me')
        job_source = getUtility(ICloseAccountJobSource)
        jobs = list(job_source.iterReady())

        # at this point we have no jobs
        self.assertEqual([], jobs)

        getUtility(ICloseAccountJobSource).create(user_to_delete.name)
        jobs = list(job_source.iterReady())
        jobs[0] = removeSecurityProxy(jobs[0])
        with dbuser(config.ICloseAccountJobSource.dbuser):
            JobRunner(jobs).runAll()

        self.assertEqual(JobStatus.COMPLETED, jobs[0].status)
        self.assertIsNone(jobs[0].context.exception)
        person = removeSecurityProxy(
            getUtility(IPersonSet).getByName(user_to_delete.name))
        self.assertEqual(person.name, u'removed%d' % user_to_delete.id)
