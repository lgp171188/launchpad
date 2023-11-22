# Copyright 2009-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = ["GPGKey", "GPGKeySet"]

from storm.locals import And, Bool, Int, Not, Reference, Select, Unicode
from zope.component import getUtility
from zope.interface import implementer

from lp.registry.interfaces.gpg import IGPGKey, IGPGKeySet
from lp.services.database.enumcol import DBEnum
from lp.services.database.interfaces import IStore
from lp.services.database.stormbase import StormBase
from lp.services.gpg.interfaces import (
    GPGKeyAlgorithm,
    IGPGHandler,
    gpg_algorithm_letter,
)
from lp.services.verification.model.logintoken import LoginToken


@implementer(IGPGKey)
class GPGKey(StormBase):
    __storm_table__ = "GPGKey"
    __storm_order__ = ["owner", "keyid"]

    id = Int(primary=True)

    owner_id = Int(name="owner", allow_none=False)
    owner = Reference(owner_id, "Person.id")

    keyid = Unicode(name="keyid", allow_none=False)
    fingerprint = Unicode(name="fingerprint", allow_none=False)

    keysize = Int(name="keysize", allow_none=False)

    algorithm = DBEnum(
        name="algorithm", allow_none=False, enum=GPGKeyAlgorithm
    )

    active = Bool(name="active", allow_none=False)

    can_encrypt = Bool(name="can_encrypt", allow_none=True)

    def __init__(
        self,
        owner,
        keyid,
        fingerprint,
        keysize,
        algorithm,
        active,
        can_encrypt=False,
    ):
        super().__init__()
        self.owner = owner
        self.keyid = keyid
        self.fingerprint = fingerprint
        self.keysize = keysize
        self.algorithm = algorithm
        self.active = active
        self.can_encrypt = can_encrypt

    @property
    def keyserverURL(self):
        return getUtility(IGPGHandler).getURLForKeyInServer(
            self.fingerprint, public=True
        )

    @property
    def displayname(self):
        return "%s%s/%s" % (
            self.keysize,
            gpg_algorithm_letter(self.algorithm),
            self.fingerprint,
        )


@implementer(IGPGKeySet)
class GPGKeySet:
    def new(
        self,
        owner,
        keyid,
        fingerprint,
        keysize,
        algorithm,
        active=True,
        can_encrypt=False,
    ):
        """See `IGPGKeySet`"""
        return GPGKey(
            owner=owner,
            keyid=keyid,
            fingerprint=fingerprint,
            keysize=keysize,
            algorithm=algorithm,
            active=active,
            can_encrypt=can_encrypt,
        )

    def activate(self, requester, key, can_encrypt):
        """See `IGPGKeySet`."""
        fingerprint = key.fingerprint
        lp_key = IStore(GPGKey).find(GPGKey, fingerprint=fingerprint).one()
        if lp_key:
            assert lp_key.owner == requester
            is_new = False
            # Then the key already exists, so let's reactivate it.
            lp_key.active = True
            lp_key.can_encrypt = can_encrypt
        else:
            is_new = True
            keyid = key.keyid
            keysize = key.keysize
            algorithm = key.algorithm
            lp_key = self.new(
                requester,
                keyid,
                fingerprint,
                keysize,
                algorithm,
                can_encrypt=can_encrypt,
            )
        return lp_key, is_new

    def deactivate(self, key):
        lp_key = IStore(GPGKey).find(GPGKey, fingerprint=key.fingerprint).one()
        lp_key.active = False

    def getByFingerprint(self, fingerprint, default=None):
        """See `IGPGKeySet`"""
        result = IStore(GPGKey).find(GPGKey, fingerprint=fingerprint).one()
        if result is None:
            return default
        return result

    def getGPGKeysForPerson(self, owner, active=True):
        clauses = []
        if active is False:
            clauses.extend(
                [
                    Not(GPGKey.active),
                    Not(
                        GPGKey.fingerprint.is_in(
                            Select(
                                LoginToken.fingerprint,
                                where=And(
                                    LoginToken.fingerprint != None,
                                    LoginToken.requester == owner,
                                    LoginToken.date_consumed == None,
                                ),
                            )
                        )
                    ),
                ]
            )
        else:
            clauses.append(GPGKey.active)
        clauses.append(GPGKey.owner == owner)
        return list(IStore(GPGKey).find(GPGKey, *clauses).order_by(GPGKey.id))
