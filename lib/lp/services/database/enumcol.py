# Copyright 2009-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from lazr.enum import DBEnumeratedType, DBItem
from storm.properties import SimpleProperty
from storm.variables import Variable
from zope.security.proxy import isinstance as zope_isinstance

__all__ = [
    "DBEnum",
]


def check_enum_type(enum):
    if not issubclass(enum, DBEnumeratedType):
        raise TypeError(
            "%r must be a DBEnumeratedType: %r" % (enum, type(enum))
        )


def check_type(enum):
    if type(enum) in (list, tuple):
        for element in enum:
            check_enum_type(element)
    else:
        check_enum_type(enum)


class DBEnumVariable(Variable):
    """A Storm variable class representing a DBEnumeratedType."""

    __slots__ = ("_enum",)

    def __init__(self, *args, **kwargs):
        self._enum = kwargs.pop("enum")
        super().__init__(*args, **kwargs)

    def parse_set(self, value, from_db):
        if from_db:
            for enum in self._enum:
                try:
                    return enum.items[value]
                except KeyError:
                    pass
            raise KeyError(
                "%r not in present in any of %r" % (value, self._enum)
            )
        else:
            if not zope_isinstance(value, DBItem):
                raise TypeError("Not a DBItem: %r" % (value,))
            if value.enum not in self._enum:
                raise TypeError(
                    "DBItem from unknown enum, %r not in %r"
                    % (value.enum.name, self._enum)
                )
            return value

    def parse_get(self, value, to_db):
        if to_db:
            return value.value
        else:
            return value


class DBEnum(SimpleProperty):
    variable_class = DBEnumVariable

    def __init__(self, *args, **kwargs):
        enum = kwargs.pop("enum")
        if type(enum) not in (list, tuple):
            enum = (enum,)
        check_type(enum)
        super().__init__(enum=enum, *args, **kwargs)
