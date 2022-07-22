# Copyright 2009-2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Security adapters for the lp.services.librarian package."""

from lp.app.security import AuthorizationBase
from lp.services.librarian.interfaces import ILibraryFileAliasWithParent


class EditLibraryFileAliasWithParent(AuthorizationBase):
    permission = "launchpad.Edit"
    usedfor = ILibraryFileAliasWithParent

    def checkAuthenticated(self, user):
        """Only persons which can edit an LFA's parent can edit an LFA.

        By default, a LibraryFileAlias does not know about its parent.
        Such aliases are never editable. Use an adapter to provide a
        parent object.

        If a parent is known, users which can edit the parent can also
        edit properties of the LibraryFileAlias.
        """
        parent = getattr(self.obj, "__parent__", None)
        if parent is None:
            return False
        return self.forwardCheckAuthenticated(user, parent)


class ViewLibraryFileAliasWithParent(AuthorizationBase):
    """Authorization class for viewing LibraryFileAliass having a parent."""

    permission = "launchpad.View"
    usedfor = ILibraryFileAliasWithParent

    def checkAuthenticated(self, user):
        """Only persons which can edit an LFA's parent can edit an LFA.

        By default, a LibraryFileAlias does not know about its parent.

        If a parent is known, users which can view the parent can also
        view the LibraryFileAlias.
        """
        parent = getattr(self.obj, "__parent__", None)
        if parent is None:
            return False
        return self.forwardCheckAuthenticated(user, parent)
