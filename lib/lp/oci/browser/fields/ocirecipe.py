# Copyright 2015-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

__all__ = [
    'OCIRecipeField',
    ]

from zope.interface import implementer
from zope.schema import Choice
from zope.schema.interfaces import IChoice


class IOCIRecipeField(IChoice):
    pass


@implementer(IOCIRecipeField)
class OCIRecipeField(Choice):
    pass
