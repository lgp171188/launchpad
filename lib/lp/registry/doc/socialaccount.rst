Social Accounts
==========

Social Accounts are associated with a person and must be created through the
ISocialAccountSet utility.

    >>> from lp.registry.interfaces.person import IPersonSet
    >>> from lp.registry.interfaces.role import IHasOwner
    >>> from lp.registry.interfaces.socialaccount import (
    ...     ISocialAccount,
    ...     ISocialAccountSet,
    ...     SocialPlatformType,
    ... )

The new() method of ISocialAccountSet takes the person who will be associated
with the Social Account, a platform type and an identity dictionary.

    >>> salgado = getUtility(IPersonSet).getByName("salgado")
    >>> identity = {}
    >>> identity["network"] = "abc.org"
    >>> identity["nickname"] = "salgado"
    >>> social_account = getUtility(ISocialAccountSet).new(
    ...     salgado, SocialPlatformType.MATRIX, identity
    ... )

The returned SocialAccount object provides both ISocialAccount and IHasOwner.

    >>> from lp.testing import verifyObject
    >>> verifyObject(ISocialAccount, social_account)
    True
    >>> verifyObject(IHasOwner, social_account)
    True
