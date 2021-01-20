from zope.app.wsgi import getWSGIApplication
from zope.app.wsgi import interfaces
import zope.processlifetime
from zope.app.publication.requestpublicationregistry import (
    factoryRegistry as publisher_factory_registry,
    )
from zope.interface import implementer
from zope.event import notify

from lp.services.config import config


@implementer(interfaces.IWSGIApplication)
class RegistryLookupFactory(object):

    def __init__(self, db):
        self._db = db
        self._publication_cache = {}
        return

    def __call__(self, input_stream, env):
        factory = publisher_factory_registry.lookup('*', '*', env)
        request_class, publication_class = factory()
        publication = self._publication_cache.get(publication_class)
        if publication is None:
            publication = publication_class(self._db)
            self._publication_cache[publication_class] = publication

        request = request_class(input_stream, env)
        request.setPublication(publication)
        return request


application = getWSGIApplication(
    config.zope_config_file,
    requestFactory=RegistryLookupFactory
)

notify(zope.processlifetime.ProcessStarting())
