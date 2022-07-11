# Copyright 2009-2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Security policies for using content objects."""

__all__ = [
    'AdminByAdminsTeam',
    'AdminByBuilddAdmin',
    'AdminByCommercialTeamOrAdmins',
    'BugTargetOwnerOrBugSupervisorOrAdmins',
    'EditByOwnersOrAdmins',
    'EditByRegistryExpertsOrAdmins',
    'EditPackageBuild',
    'is_commercial_case',
    'ModerateByRegistryExpertsOrAdmins',
    'OnlyBazaarExpertsAndAdmins',
    'OnlyRosettaExpertsAndAdmins',
    'OnlyVcsImportsAndAdmins',
    ]

from datetime import (
    datetime,
    timedelta,
    )

import pytz
from zope.interface import Interface

from lp.app.security import (
    AnonymousAuthorization,
    AuthorizationBase,
    DelegatedAuthorization,
    )
from lp.archivepublisher.interfaces.publisherconfig import IPublisherConfig
from lp.bugs.interfaces.bugtarget import IOfficialBugTagTargetRestricted
from lp.bugs.interfaces.structuralsubscription import IStructuralSubscription
from lp.buildmaster.interfaces.builder import (
    IBuilder,
    IBuilderSet,
    )
from lp.buildmaster.interfaces.buildfarmjob import IBuildFarmJob
from lp.buildmaster.interfaces.packagebuild import IPackageBuild
from lp.oci.interfaces.ocipushrule import IOCIPushRule
from lp.oci.interfaces.ocirecipe import (
    IOCIRecipe,
    IOCIRecipeBuildRequest,
    )
from lp.oci.interfaces.ocirecipebuild import IOCIRecipeBuild
from lp.oci.interfaces.ocirecipesubscription import IOCIRecipeSubscription
from lp.oci.interfaces.ociregistrycredentials import IOCIRegistryCredentials
from lp.registry.interfaces.role import IHasOwner
from lp.services.config import config
from lp.services.webapp.interfaces import ILaunchpadRoot
from lp.snappy.interfaces.snap import (
    ISnap,
    ISnapBuildRequest,
    )
from lp.snappy.interfaces.snapbase import (
    ISnapBase,
    ISnapBaseSet,
    )
from lp.snappy.interfaces.snapbuild import ISnapBuild
from lp.snappy.interfaces.snappyseries import (
    ISnappySeries,
    ISnappySeriesSet,
    )
from lp.snappy.interfaces.snapsubscription import ISnapSubscription


def is_commercial_case(obj, user):
    """Is this a commercial project and the user is a commercial admin?"""
    return obj.has_current_commercial_subscription and user.in_commercial_admin


class ViewByLoggedInUser(AuthorizationBase):
    """The default ruleset for the launchpad.View permission.

    By default, any logged-in user can see anything. More restrictive
    rulesets are defined in other IAuthorization implementations.
    """
    permission = 'launchpad.View'
    usedfor = Interface

    def checkAuthenticated(self, user):
        """Any authenticated user can see this object."""
        return True


class AnyAllowedPersonDeferredToView(AuthorizationBase):
    """The default ruleset for the launchpad.AnyAllowedPerson permission.

    An authenticated user is delegated to the View security adapter. Since
    anonymous users are not logged in, they are denied.
    """
    permission = 'launchpad.AnyAllowedPerson'
    usedfor = Interface

    def checkUnauthenticated(self):
        return False

    def checkAuthenticated(self, user):
        yield self.obj, 'launchpad.View'


class AnyLegitimatePerson(AuthorizationBase):
    """The default ruleset for the launchpad.AnyLegitimatePerson permission.

    Some operations are open to Launchpad users in general, but we still don't
    want drive-by vandalism.
    """
    permission = 'launchpad.AnyLegitimatePerson'
    usedfor = Interface

    def checkUnauthenticated(self):
        return False

    def _hasEnoughKarma(self, user):
        return user.person.karma >= config.launchpad.min_legitimate_karma

    def _isOldEnough(self, user):
        return (
            datetime.now(pytz.UTC) - user.person.account.date_created >=
            timedelta(days=config.launchpad.min_legitimate_account_age))

    def checkAuthenticated(self, user):
        if not self._hasEnoughKarma(user) and not self._isOldEnough(user):
            return False
        return self.forwardCheckAuthenticated(
            user, self.obj, 'launchpad.AnyAllowedPerson')


class LimitedViewDeferredToView(AuthorizationBase):
    """The default ruleset for the launchpad.LimitedView permission.

    Few objects define LimitedView permission because it is only needed
    in cases where a user may know something about a private object. The
    default behaviour is to check if the user has launchpad.View permission;
    private objects must define their own launchpad.LimitedView checker to
    truly check the permission.
    """
    permission = 'launchpad.LimitedView'
    usedfor = Interface

    def checkUnauthenticated(self):
        yield self.obj, 'launchpad.View'

    def checkAuthenticated(self, user):
        yield self.obj, 'launchpad.View'


class AdminByAdminsTeam(AuthorizationBase):
    permission = 'launchpad.Admin'
    usedfor = Interface

    def checkAuthenticated(self, user):
        return user.in_admin


class AdminByCommercialTeamOrAdmins(AuthorizationBase):
    permission = 'launchpad.Commercial'
    usedfor = Interface

    def checkAuthenticated(self, user):
        return user.in_commercial_admin or user.in_admin


class EditByRegistryExpertsOrAdmins(AuthorizationBase):
    permission = 'launchpad.Edit'
    usedfor = ILaunchpadRoot

    def checkAuthenticated(self, user):
        return user.in_admin or user.in_registry_experts


class ModerateByRegistryExpertsOrAdmins(AuthorizationBase):
    permission = 'launchpad.Moderate'
    usedfor = None

    def checkAuthenticated(self, user):
        return user.in_admin or user.in_registry_experts


class EditByOwnersOrAdmins(AuthorizationBase):
    permission = 'launchpad.Edit'
    usedfor = IHasOwner

    def checkAuthenticated(self, user):
        return user.isOwner(self.obj) or user.in_admin


class OnlyRosettaExpertsAndAdmins(AuthorizationBase):
    """Base class that allow access to Rosetta experts and Launchpad admins.
    """

    def checkAuthenticated(self, user):
        """Allow Launchpad's admins and Rosetta experts edit all fields."""
        return user.in_admin or user.in_rosetta_experts


class BugTargetOwnerOrBugSupervisorOrAdmins(AuthorizationBase):
    """Product's owner and bug supervisor can set official bug tags."""

    permission = 'launchpad.BugSupervisor'
    usedfor = IOfficialBugTagTargetRestricted

    def checkAuthenticated(self, user):
        return (user.inTeam(self.obj.bug_supervisor) or
                user.inTeam(self.obj.owner) or
                user.in_admin)


class EditStructuralSubscription(AuthorizationBase):
    permission = 'launchpad.Edit'
    usedfor = IStructuralSubscription

    def checkAuthenticated(self, user):
        """Who can edit StructuralSubscriptions."""

        assert self.obj.target

        # Removal of a target cascades removals to StructuralSubscriptions,
        # so we need to allow editing to those who can edit the target itself.
        can_edit_target = self.forwardCheckAuthenticated(
            user, self.obj.target)

        # Who is actually allowed to edit a subscription is determined by
        # a helper method on the model.
        can_edit_subscription = self.obj.target.userCanAlterSubscription(
            self.obj.subscriber, user.person)

        return (can_edit_target or can_edit_subscription)


class OnlyBazaarExpertsAndAdmins(AuthorizationBase):
    """Base class that allows only the Launchpad admins and Bazaar
    experts."""

    def checkAuthenticated(self, user):
        return user.in_admin


class OnlyVcsImportsAndAdmins(AuthorizationBase):
    """Base class that allows only the Launchpad admins and VCS Imports
    experts."""

    def checkAuthenticated(self, user):
        return user.in_admin or user.in_vcs_imports


class AdminByBuilddAdmin(AuthorizationBase):
    permission = 'launchpad.Admin'

    def checkAuthenticated(self, user):
        """Allow admins and buildd_admins."""
        return user.in_buildd_admin or user.in_admin


class AdminBuilderSet(AdminByBuilddAdmin):
    usedfor = IBuilderSet


class AdminBuilder(AdminByBuilddAdmin):
    usedfor = IBuilder


class EditBuilder(AdminByBuilddAdmin):
    permission = 'launchpad.Edit'
    usedfor = IBuilder


class ModerateBuilder(EditBuilder):
    permission = 'launchpad.Moderate'
    usedfor = IBuilder

    def checkAuthenticated(self, user):
        return (user.in_registry_experts or
                super().checkAuthenticated(user))


class AdminBuildRecord(AdminByBuilddAdmin):
    usedfor = IBuildFarmJob


class EditBuildFarmJob(AdminByBuilddAdmin):
    permission = 'launchpad.Edit'
    usedfor = IBuildFarmJob


class EditPackageBuild(EditBuildFarmJob):
    usedfor = IPackageBuild

    def checkAuthenticated(self, user):
        """Check if the user has access to edit the archive."""
        if EditBuildFarmJob.checkAuthenticated(self, user):
            return True

        # If the user is in the owning team for the archive,
        # then they have access to edit the builds.
        # If it's a PPA or a copy archive only allow its owner.
        return (self.obj.archive.owner and
                user.inTeam(self.obj.archive.owner))


class ViewPublisherConfig(AdminByAdminsTeam):
    usedfor = IPublisherConfig


class ViewSnap(AuthorizationBase):
    """Private snaps are only visible to their owners and admins."""
    permission = 'launchpad.View'
    usedfor = ISnap

    def checkAuthenticated(self, user):
        return self.obj.visibleByUser(user.person)

    def checkUnauthenticated(self):
        return self.obj.visibleByUser(None)


class EditSnap(AuthorizationBase):
    permission = 'launchpad.Edit'
    usedfor = ISnap

    def checkAuthenticated(self, user):
        return (
            user.isOwner(self.obj) or
            user.in_commercial_admin or user.in_admin)


class AdminSnap(AuthorizationBase):
    """Restrict changing build settings on snap packages.

    The security of the non-virtualised build farm depends on these
    settings, so they can only be changed by "PPA"/commercial admins, or by
    "PPA" self admins on snap packages that they can already edit.
    """
    permission = 'launchpad.Admin'
    usedfor = ISnap

    def checkAuthenticated(self, user):
        if user.in_ppa_admin or user.in_commercial_admin or user.in_admin:
            return True
        return (
            user.in_ppa_self_admins
            and EditSnap(self.obj).checkAuthenticated(user))


class SnapSubscriptionEdit(AuthorizationBase):
    permission = 'launchpad.Edit'
    usedfor = ISnapSubscription

    def checkAuthenticated(self, user):
        """Is the user able to edit a Snap recipe subscription?

        Any team member can edit a Snap recipe subscription for their
        team.
        Launchpad Admins can also edit any Snap recipe subscription.
        The owner of the subscribed Snap can edit the subscription. If
        the Snap owner is a team, then members of the team can edit
        the subscription.
        """
        return (user.inTeam(self.obj.snap.owner) or
                user.inTeam(self.obj.person) or
                user.inTeam(self.obj.subscribed_by) or
                user.in_admin)


class SnapSubscriptionView(AuthorizationBase):
    permission = 'launchpad.View'
    usedfor = ISnapSubscription

    def checkUnauthenticated(self):
        return self.obj.snap.visibleByUser(None)

    def checkAuthenticated(self, user):
        return self.obj.snap.visibleByUser(user.person)


class ViewSnapBuildRequest(DelegatedAuthorization):
    permission = 'launchpad.View'
    usedfor = ISnapBuildRequest

    def __init__(self, obj):
        super().__init__(obj, obj.snap, 'launchpad.View')


class ViewSnapBuild(DelegatedAuthorization):
    permission = 'launchpad.View'
    usedfor = ISnapBuild

    def iter_objects(self):
        yield self.obj.snap
        yield self.obj.archive


class EditSnapBuild(AdminByBuilddAdmin):
    permission = 'launchpad.Edit'
    usedfor = ISnapBuild

    def checkAuthenticated(self, user):
        """Check edit access for snap package builds.

        Allow admins, buildd admins, and the owner of the snap package.
        (Note that the requester of the build is required to be in the team
        that owns the snap package.)
        """
        auth_snap = EditSnap(self.obj.snap)
        if auth_snap.checkAuthenticated(user):
            return True
        return super().checkAuthenticated(user)


class AdminSnapBuild(AdminByBuilddAdmin):
    usedfor = ISnapBuild


class ViewSnappySeries(AnonymousAuthorization):
    """Anyone can view an `ISnappySeries`."""
    usedfor = ISnappySeries


class EditSnappySeries(EditByRegistryExpertsOrAdmins):
    usedfor = ISnappySeries


class EditSnappySeriesSet(EditByRegistryExpertsOrAdmins):
    usedfor = ISnappySeriesSet


class ViewSnapBase(AnonymousAuthorization):
    """Anyone can view an `ISnapBase`."""
    usedfor = ISnapBase


class EditSnapBase(EditByRegistryExpertsOrAdmins):
    usedfor = ISnapBase


class EditSnapBaseSet(EditByRegistryExpertsOrAdmins):
    usedfor = ISnapBaseSet


class ViewOCIRecipeBuildRequest(DelegatedAuthorization):
    permission = 'launchpad.View'
    usedfor = IOCIRecipeBuildRequest

    def __init__(self, obj):
        super().__init__(obj, obj.recipe, 'launchpad.View')


class ViewOCIRecipe(AnonymousAuthorization):
    """Anyone can view public `IOCIRecipe`, but only subscribers can view
    private ones.
    """
    usedfor = IOCIRecipe

    def checkUnauthenticated(self):
        return self.obj.visibleByUser(None)

    def checkAuthenticated(self, user):
        return self.obj.visibleByUser(user.person)


class EditOCIRecipe(AuthorizationBase):
    permission = 'launchpad.Edit'
    usedfor = IOCIRecipe

    def checkAuthenticated(self, user):
        return (
            user.isOwner(self.obj) or
            user.in_commercial_admin or user.in_admin)


class AdminOCIRecipe(AuthorizationBase):
    """Restrict changing build settings on OCI recipes.

    The security of the non-virtualised build farm depends on these
    settings, so they can only be changed by "PPA"/commercial admins, or by
    "PPA" self admins on OCI recipes that they can already edit.
    """
    permission = 'launchpad.Admin'
    usedfor = IOCIRecipe

    def checkAuthenticated(self, user):
        if user.in_ppa_admin or user.in_commercial_admin or user.in_admin:
            return True
        return (
            user.in_ppa_self_admins
            and EditSnap(self.obj).checkAuthenticated(user))


class OCIRecipeSubscriptionEdit(AuthorizationBase):
    permission = 'launchpad.Edit'
    usedfor = IOCIRecipeSubscription

    def checkAuthenticated(self, user):
        """Is the user able to edit an OCI recipe subscription?

        Any team member can edit a OCI recipe subscription for their
        team.
        Launchpad Admins can also edit any OCI recipe subscription.
        The owner of the subscribed OCI recipe can edit the subscription. If
        the OCI recipe owner is a team, then members of the team can edit
        the subscription.
        """
        return (user.inTeam(self.obj.recipe.owner) or
                user.inTeam(self.obj.person) or
                user.inTeam(self.obj.subscribed_by) or
                user.in_admin)


class OCIRecipeSubscriptionView(AuthorizationBase):
    permission = 'launchpad.View'
    usedfor = IOCIRecipeSubscription

    def checkUnauthenticated(self):
        return self.obj.recipe.visibleByUser(None)

    def checkAuthenticated(self, user):
        return self.obj.recipe.visibleByUser(user.person)


class ViewOCIRecipeBuild(DelegatedAuthorization):
    permission = 'launchpad.View'
    usedfor = IOCIRecipeBuild

    def iter_objects(self):
        yield self.obj.recipe


class EditOCIRecipeBuild(AdminByBuilddAdmin):
    permission = 'launchpad.Edit'
    usedfor = IOCIRecipeBuild

    def checkAuthenticated(self, user):
        """Check edit access for OCI recipe builds.

        Allow admins, buildd admins, and the owner of the OCI recipe.
        (Note that the requester of the build is required to be in the team
        that owns the OCI recipe.)
        """
        auth_recipe = EditOCIRecipe(self.obj.recipe)
        if auth_recipe.checkAuthenticated(user):
            return True
        return super().checkAuthenticated(user)


class AdminOCIRecipeBuild(AdminByBuilddAdmin):
    usedfor = IOCIRecipeBuild


class ViewOCIRegistryCredentials(AuthorizationBase):
    permission = 'launchpad.View'
    usedfor = IOCIRegistryCredentials

    def checkAuthenticated(self, user):
        # This must be kept in sync with user_can_edit_credentials_for_owner
        # in lp.oci.interfaces.ociregistrycredentials.
        return (
            user.isOwner(self.obj) or
            user.in_admin)


class ViewOCIPushRule(AnonymousAuthorization):
    """Anyone can view an `IOCIPushRule`."""
    usedfor = IOCIPushRule


class OCIPushRuleEdit(AuthorizationBase):
    permission = 'launchpad.Edit'
    usedfor = IOCIPushRule

    def checkAuthenticated(self, user):
        return (
            user.isOwner(self.obj.recipe) or
            user.in_commercial_admin or user.in_admin)
