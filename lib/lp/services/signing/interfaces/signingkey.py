# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Interfaces for signing keys stored at the signing service."""

__metaclass__ = type

__all__ = [
    'ISigningKey'
]

from lp.services.signing.enums import SigningKeyType
from lp.registry.interfaces.distroseries import IDistroSeries
from lp.soyuz.interfaces.archive import IArchive
from zope.interface.interface import Interface
from zope.schema import (
    Int,
    Text,
    Datetime,
    Choice
    )
from lazr.restful.fields import Reference
from lp import _


class ISigningKey(Interface):
    """A key registered to sign uploaded files"""

    id = Int(title=_('ID'), required=True, readonly=True)

    archive = Reference(
        IArchive, title=_("Archive"), required=True,
        description=_("The archive that owns this key."))

    distro_series = Reference(
        IDistroSeries, title=_("Distro series"), required=False,
        description=_("The minimum series that uses this key, if any."))

    key_type = Choice(
        title=_("The signing key type (UEFI, KMOD, etc)."),
        required=True, readonly=True, vocabulary=SigningKeyType)

    fingerprint = Text(
        title=_("Fingerprint of the key"), required=True, readonly=True)

    public_key = Text(
        title=_("Public key binary content"), required=False,
        readonly=True)

    date_created = Datetime(
        title=_('When this key was created'), required=True, readonly=True)
