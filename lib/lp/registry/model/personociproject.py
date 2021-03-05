# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""A person's view on an OCI project."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = []

from zope.interface import (
    implementer,
    provider,
    )

from lp.registry.interfaces.personociproject import (
    IPersonOCIProject,
    IPersonOCIProjectFactory,
    )


@implementer(IPersonOCIProject)
@provider(IPersonOCIProjectFactory)
class PersonOCIProject:

    def __init__(self, person, oci_project):
        self.person = person
        self.oci_project = oci_project

    @staticmethod
    def create(person, oci_project):
        return PersonOCIProject(person, oci_project)

    @property
    def display_name(self):
        return '%s in %s' % (
            self.person.display_name, self.oci_project.display_name)

    def __eq__(self, other):
        return (
            IPersonOCIProject.providedBy(other) and
            self.person == other.person and
            self.oci_project == other.oci_project)

    def __ne__(self, other):
        return not self == other

    def __hash__(self):
        return hash((self.person, self.oci_project))
