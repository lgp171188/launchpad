# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""A recipe for building Open Container Initiative images."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    'OCIRecipe',
    'OCIRecipeSet',
    ]


from lazr.lifecycle.event import ObjectCreatedEvent
import pytz
from storm.locals import (
    Bool,
    DateTime,
    Int,
    Reference,
    Storm,
    Unicode,
    )
from zope.component import getUtility
from zope.event import notify
from zope.interface import implementer

from lp.buildmaster.enums import BuildStatus
from lp.oci.interfaces.ocirecipe import (
    IOCIRecipe,
    IOCIRecipeSet,
    OCIRecipeBuildAlreadyPending,
    OCIRecipeNotOwner,
    )
from lp.oci.interfaces.ocirecipebuild import IOCIRecipeBuildSet
from lp.oci.model.ocirecipebuild import OCIRecipeBuild
from lp.services.database.interfaces import (
    IMasterStore,
    IStore,
    )


@implementer(IOCIRecipe)
class OCIRecipe(Storm):

    __storm_table__ = 'OCIRecipe'

    id = Int(primary=True)
    date_created = DateTime(
        name="date_created", tzinfo=pytz.UTC, allow_none=False)
    date_last_modified = DateTime(
        name="date_last_modified", tzinfo=pytz.UTC, allow_none=False)

    registrant_id = Int(name='registrant', allow_none=False)
    registrant = Reference(registrant_id, "Person.id")

    owner_id = Int(name='owner', allow_none=False)
    owner = Reference(owner_id, 'Person.id')

    ociproject_id = Int(name='ociproject', allow_none=False)
    ociproject = Reference(ociproject_id, "OCIProject.id")

    ociproject_default = Bool(name="ociproject_default", default=False)

    description = Unicode(name="description")

    require_virtualized = Bool(name="require_virtualized", default=True)

    def __init__(self, registrant, owner, ociproject, ociproject_default=False,
                 require_virtualized=True):
        super(OCIRecipe, self).__init__()
        self.registrant = registrant
        self.owner = owner
        self.ociproject = ociproject
        self.ociproject_default = ociproject_default
        self.require_virtualized = require_virtualized

    def destroySelf(self):
        """See `IOCIRecipe`."""
        # XXX twom 2019-11-26 This needs to expand as more build artifacts
        # are added
        store = IStore(OCIRecipe)
        store.remove(self)

    def _checkRequestBuild(self, requester):
        if not requester.inTeam(self.owner):
            raise OCIRecipeNotOwner(
                "%s cannot create OCI image builds owned by %s." %
                (requester.displayname, self.owner.displayname))

    def requestBuild(self, requester, channel, architecture):
        self._checkRequestBuild(requester)

        pending = IStore(self).find(
            OCIRecipeBuild,
            OCIRecipeBuild.recipe == self.id,
            OCIRecipeBuild.channel_name == channel.name,
            OCIRecipeBuild.processor == architecture.processor,
            OCIRecipeBuild.status == BuildStatus.NEEDSBUILD)
        if pending.any() is not None:
            raise OCIRecipeBuildAlreadyPending

        build = getUtility(IOCIRecipeBuildSet).new(
            requester, self, channel.name, architecture.processor,
            self.require_virtualized)
        build.queueBuild()
        notify(ObjectCreatedEvent(build, user=requester))
        return build

    @property
    def completed_builds(self):
        """See `IOCIRecipe`."""
        pass

    @property
    def pending_builds(self):
        """See `IOCIRecipe`."""
        pass

    @property
    def channels(self):
        """See `IOCIRecipe`."""

    def addChannel(self, name):
        """See `IOCIRecipe`."""
        pass

    def removeChannel(self, name):
        """See `IOCIRecipe`."""
        pass


class OCIRecipeArch(Storm):
    """Link table back to `OCIRecipe.processors`."""

    __storm_table__ = "OCIRecipeArch"
    __storm_primary__ = ("recipe_id", "processor_id")

    recipe_id = Int(name="recipe", allow_none=False)
    recipe = Reference(recipe_id, "OCIRecipe.id")

    processor_id = Int(name="processor", allow_none=False)
    processor = Reference(processor_id, "Processor.id")

    def __init__(self, recipe, processor):
        self.recipe = recipe
        self.processor = processor


@implementer(IOCIRecipeSet)
class OCIRecipeSet:

    def new(self, registrant, owner, ociproject, ociproject_default,
            require_virtualized):
        """See `IOCIRecipeSet`."""
        if not registrant.inTeam(owner):
            if owner.is_team:
                raise OCIRecipeNotOwner(
                    "%s is not a member of %s." %
                    (registrant.displayname, owner.displayname))
            else:
                raise OCIRecipeNotOwner(
                    "%s cannot create OCI images owned by %s." %
                    (registrant.displayname, owner.displayname))

        store = IMasterStore(OCIRecipe)
        oci_recipe = OCIRecipe(
            registrant, owner, ociproject, ociproject_default,
            require_virtualized)
        store.add(oci_recipe)

        return oci_recipe
