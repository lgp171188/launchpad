# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Job classes related to ApportJobs are in here."""

__metaclass__ = type
__all__ = [
    'ApportJob',
    'ApportJobDerived',
    ]

import simplejson
from cStringIO import StringIO

from sqlobject import SQLObjectNotFound
from storm.base import Storm
from storm.expr import And
from storm.locals import Int, Reference, Unicode

from zope.component import getUtility
from zope.interface import classProvides, implements

from canonical.database.enumcol import EnumCol
from canonical.launchpad.database.temporaryblobstorage import (
    TemporaryBlobStorage)
from canonical.launchpad.interfaces.librarian import ILibraryFileAliasSet
from canonical.launchpad.interfaces.lpstorm import IStore
from canonical.launchpad.webapp.interfaces import (
    DEFAULT_FLAVOR, IStoreSelector, MAIN_STORE)

from lazr.delegates import delegates

from lp.bugs.interfaces.apportjob import (
    ApportJobType, IApportJob, IApportJobSource, IProcessApportBlobJob,
    IProcessApportBlobJobSource)
from lp.bugs.utilities.filebugdataparser import FileBugDataParser
from lp.services.job.model.job import Job
from lp.services.job.runner import BaseRunnableJob


class ApportJob(Storm):
    """Base class for jobs related to Apport BLOBs."""

    implements(IApportJob)

    __storm_table__ = 'ApportJob'

    id = Int(primary=True)

    job_id = Int(name='job')
    job = Reference(job_id, Job.id)

    blob_id = Int(name='blob')
    blob = Reference(blob_id, TemporaryBlobStorage.id)

    job_type = EnumCol(enum=ApportJobType, notNull=True)

    _json_data = Unicode('json_data')

    # The metadata property because it needs to be modifiable by
    # subclasses of ApportJobDerived. However, since ApportJobDerived
    # only delegates() to ApportJob we can't simply directly access the
    # _json_data property, so we use a getter and setter here instead.
    def _set_metadata(self, metadata):
        self._json_data = unicode(
            simplejson.dumps(metadata, 'utf-8'))

    def _get_metadata(self):
        return simplejson.loads(self._json_data)

    metadata = property(_get_metadata, _set_metadata)

    def __init__(self, blob, job_type, metadata):
        """Constructor.

        :param blob: The ITemporaryBlobStorage object this job relates to.
        :param job_type: The ApportJobType of this job.
        :param metadata: The type-specific variables, as a JSON-compatible
            dict.
        """
        super(ApportJob, self).__init__()
        json_data = simplejson.dumps(metadata)
        self.job = Job()
        self.blob = blob
        self.job_type = job_type
        # XXX AaronBentley 2009-01-29 blob=322819: This should be a bytestring,
        # but the DB representation is unicode.
        self._json_data = json_data.decode('utf-8')

    @classmethod
    def get(cls, key):
        """Return the instance of this class whose key is supplied."""
        store = getUtility(IStoreSelector).get(MAIN_STORE, DEFAULT_FLAVOR)
        instance = store.get(cls, key)
        if instance is None:
            raise SQLObjectNotFound(
                'No occurrence of %s has key %s' % (cls.__name__, key))
        return instance


class ApportJobDerived(BaseRunnableJob):
    """Intermediate class for deriving from ApportJob."""
    delegates(IApportJob)
    classProvides(IApportJobSource)

    def __init__(self, job):
        self.context = job

    @classmethod
    def create(cls, blob):
        """See `IApportJob`."""
        # If there's already a job for the blob, don't create a new one.
        job = ApportJob(blob, cls.class_job_type, {})
        return cls(job)

    @classmethod
    def get(cls, job_id):
        """Get a job by id.

        :return: the ApportJob with the specified id, as the current
                 ApportJobDerived subclass.
        :raises: SQLObjectNotFound if there is no job with the specified id,
                 or its job_type does not match the desired subclass.
        """
        job = ApportJob.get(job_id)
        if job.job_type != cls.class_job_type:
            raise SQLObjectNotFound(
                'No object found with id %d and type %s' % (job_id,
                cls.class_job_type.title))
        return cls(job)

    @classmethod
    def iterReady(cls):
        """Iterate through all ready ApportJobs."""
        store = IStore(ApportJob)
        jobs = store.find(
            ApportJob,
            And(ApportJob.job_type == cls.class_job_type,
                ApportJob.job == Job.id,
                Job.id.is_in(Job.ready_jobs)))
        return (cls(job) for job in jobs)

    def getOopsVars(self):
        """See `IRunnableJob`."""
        vars =  BaseRunnableJob.getOopsVars(self)
        vars.extend([
            ('apport_blob_uuid', self.context.blob.uuid),
            ('apport_blob_librarian_url',
                self.context.blob.file_alias.getURL()),
            ('apport_job_id', self.context.id),
            ('apport_job_type', self.context.job_type.title),
            ])
        return vars


class ProcessApportBlobJob(ApportJobDerived):
    """A Job to process an Apport BLOB."""
    implements(IProcessApportBlobJob)

    class_job_type = ApportJobType.PROCESS_BLOB
    classProvides(IProcessApportBlobJobSource)

    @classmethod
    def create(cls, blob):
        """See `IProcessApportBlobJobSource`."""
        # If there's already a job for the bug, don't create a new one.
        store = getUtility(IStoreSelector).get(MAIN_STORE, DEFAULT_FLAVOR)
        job_for_blob = store.find(
            ApportJob,
            ApportJob.blob == blob,
            ApportJob.job_type == cls.class_job_type,
            ApportJob.job == Job.id,
            Job.id.is_in(Job.ready_jobs)
            ).any()

        if job_for_blob is not None:
            return cls(job_for_blob)
        else:
            return super(ProcessApportBlobJob, cls).create(blob)

    def run(self):
        """See `IRunnableJob`."""
        self.blob.file_alias.open()
        parser = FileBugDataParser(self.blob.file_alias)
        parsed_data = parser.parse()

        # We transform the parsed_data object into a dict, because
        # that's easier to store in JSON.
        parsed_data_dict = parsed_data.asDict()

        # If there are attachments, we loop over them and push them to
        # the Librarian, since it's easier than trying to serialize file
        # data to the ApportJob table.
        if len(parsed_data_dict.get('attachments')) > 0:
            attachments = parsed_data_dict['attachments']
            attachment_file_alias_ids = []

            for attachment in attachments:
                file_content = attachment['content'].read()
                file_alias = getUtility(ILibraryFileAliasSet).create(
                    name=attachment['filename'], size=len(file_content),
                    file=StringIO(file_content),
                    contentType=attachment['content_type'])
                attachment_file_alias_ids.append(file_alias.id)

            # We cheekily overwrite the 'attachments' value in the
            # parsed_data_dict so as to avoid trying to serialize file
            # objects to JSON.
            parsed_data_dict['attachments'] = attachment_file_alias_ids

        metadata = self.metadata
        metadata.update({'processed_data': parsed_data_dict})
        self.metadata = metadata
