# Copyright 2004 Canonical Ltd.  All rights reserved.

__metaclass__ = type

import warnings

from zope.interface import classProvides
from zope.component import queryAdapter
from zope.component.interfaces import IView

from zope.security.interfaces import ISecurityPolicy
from zope.security.checker import CheckerPublic
from zope.security.proxy import removeSecurityProxy
from zope.security.simplepolicies import ParanoidSecurityPolicy
from zope.security.management import system_user

from canonical.launchpad.webapp.interfaces import ILaunchpadPrincipal
from canonical.launchpad.interfaces import IAuthorization, IObjectAuthorization


class LaunchpadSecurityPolicy(ParanoidSecurityPolicy):
    classProvides(ISecurityPolicy)

    def checkPermission(self, permission, object):
        """Check the permission, object, user against the launchpad
        authorization policy.

        If the object is a view, then consider the object to be the view's
        context.

        Workflow:
        - If we have zope.Public, allow.  (We shouldn't ever get this, though.)
        - If we have launchpad.AnyPerson and the user is an ILaunchpadPrincipal
          then allow.
        - If the object has an IObjectAuthorization adapter, use that to
          check the permission.
        - Otherwise, if the object has an IAuthorization named adapter, named
          after the permission, use that to check the permission.
        - Otherwise, deny.
        """
        # This check shouldn't be needed, strictly speaking.
        # However, it is here as a "belt and braces".
        # XXX: It should emit a warning.  Steve Alexander, 2004-11-24.
        #      This applies to the policy in zope3 also.
        if permission == 'zope.Public':
            warnings.warn('zope.Public being used raw on object %r' % object)
            return True
        if permission is CheckerPublic:
            return True
        users = [p.principal
                 for p in self.participations
                 if p.principal is not system_user]

        if not users:
            return False
        if len(users) > 1:
            raise RuntimeError, "More than one user participating."
        user = users[0]
        if (permission == 'launchpad.AnyPerson' and
            ILaunchpadPrincipal.providedBy(user)):
            return True
        else:
            # If we have a view, get its context and use that to get an
            # authorization adapter.
            if IView.providedBy(object):
                objecttoauthorize = object.context
            else:
                objecttoauthorize = object

            # Remove security proxies from object to authorize.
            objecttoauthorize = removeSecurityProxy(objecttoauthorize)


            # Get an IObjectAuthorization adapter.
            objectauthorization = IObjectAuthorization(objecttoauthorize, None)
            if objectauthorization is not None:
                result = objectauthorization.checkPermission(user, permission)
                if result is not True and result is not False:
                    warnings.warn(
                        'object authorization returning non-bool value: %r' %
                        objectauthorization)
                return bool(result)

            # If there is no IObjectAuthorization adapter, we look for an
            # IAuthorization adapter.  If there is no such adapter, then
            # the permission is not granted.
            authorization = queryAdapter(
                objecttoauthorize, IAuthorization, permission)
            if authorization is None:
                return False
            else:
                result = authorization.checkPermission(user)
                if result is not True and result is not False:
                    warnings.warn(
                        'authorization returning non-bool value: %r' %
                        objectauthorization)
                return bool(authorization.checkPermission(user))

