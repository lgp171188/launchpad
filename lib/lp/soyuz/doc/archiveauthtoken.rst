ArchiveAuthToken
================

This content class represents an authorisation token associated with
an IPerson and an IArchive.  The tokens are used to permit Launchpad
users access to a published private archive and are written out to
.htaccess files in the archive's filesystem by the publisher.

See also archivesubscriber.rst.

First we create a private PPA for Joe.

    >>> login("admin@canonical.com")
    >>> joe = factory.makePerson(name="joe", displayname="Joe Smith")
    >>> joe_private_ppa = factory.makeArchive(
    ...     owner=joe, private=True, name="ppa"
    ... )


Creating new tokens
-------------------

New tokens are created using IArchive.newAuthToken() but this is only
possible if there is already a valid subscription for the user for
that archive.

Create Brad, and his teams:

    >>> login("admin@canonical.com")
    >>> bradsmith = factory.makePerson(
    ...     name="bradsmith",
    ...     displayname="Brad Smith",
    ...     email="brad@example.com",
    ... )
    >>> teambrad = factory.makeTeam(
    ...     owner=bradsmith, displayname="Team Brad", name="teambrad"
    ... )
    >>> teambrad2 = factory.makeTeam(
    ...     owner=bradsmith, displayname="Team Brad 2", name="teambrad2"
    ... )

Create a subscription for Team Brad to joe's archive:

    >>> ignored = login_person(joe)
    >>> subscription_to_joe_private_ppa = joe_private_ppa.newSubscription(
    ...     teambrad, joe
    ... )
    >>> login("brad@example.com")

It is not possible to create a token for the subscribed team.

    >>> joe_private_ppa.newAuthToken(teambrad)
    Traceback (most recent call last):
    ...
    lp.soyuz.interfaces.archive.NoTokensForTeams:
    Subscription tokens can be created for individuals only.

But now that the subscription is there, we can create a token as Brad.

    >>> token_with_random_string = joe_private_ppa.newAuthToken(bradsmith)

By default the tokens are 20 characters long.

    >>> print(len(token_with_random_string.token))
    20

It is not possible to create a second token when one already exists:

    >>> new_token = joe_private_ppa.newAuthToken(bradsmith)
    Traceback (most recent call last):
    ...
    lp.soyuz.interfaces.archivesubscriber.ArchiveSubscriptionError:
    Brad Smith already has a token for PPA for Joe Smith.

So deactivate the old token so that we can create a new token:

    >>> ignored = login_person(bradsmith)
    >>> token_with_random_string.deactivate()
    >>> login("brad@example.com")

We can also specify our own token for testing purposes:

    >>> new_token = joe_private_ppa.newAuthToken(bradsmith, "testtoken")

The new token is returned and reflects the data:

    >>> print(new_token.archive.displayname)
    PPA for Joe Smith

    >>> print(new_token.person.name)
    bradsmith

    >>> print(new_token.token)
    testtoken

    >>> print(new_token.archive_url)
    http://bradsmith:testtoken@private-ppa.launchpad.test/joe/ppa/...

Commit the new token to the database.

    >>> from storm.store import Store
    >>> Store.of(new_token).commit()

Tokens also contain some date information:

    >>> new_token.date_created is not None
    True

    >>> print(new_token.date_deactivated)
    None


Retrieving existing tokens
--------------------------

The ArchiveAuthTokenSet utility allows you to retrieve tokens by ID and by
the token text itself.  To access tokens you need launchpad.View privilege
which applies to the person in the token and launchpad admins.

    >>> from lp.soyuz.interfaces.archiveauthtoken import IArchiveAuthTokenSet
    >>> token_set = getUtility(IArchiveAuthTokenSet)

    >>> login("no-priv@canonical.com")

    >>> token = token_set.get(new_token.id)
    Traceback (most recent call last):
    ...
    zope.security.interfaces.Unauthorized: ...

Log in as Brad Smith, who is the person in the token.

    >>> login("brad@example.com")

And retrieve the token by id and by token data:

    >>> print(token_set.get(new_token.id).token)
    testtoken

    >>> print(token_set.getByToken("testtoken").person.name)
    bradsmith

It's also possible to retrieve a set of all the tokens for an archive.

    >>> tokens = token_set.getByArchive(joe_private_ppa)
    >>> print(tokens.count())
    1

    >>> for token in tokens:
    ...     print(token.person.name)
    ...
    bradsmith

Tokens can also be retrieved by archive and person:

    >>> print(
    ...     token_set.getActiveTokenForArchiveAndPerson(
    ...         new_token.archive, new_token.person
    ...     ).token
    ... )
    testtoken

Or by archive and person name:

    >>> print(
    ...     token_set.getActiveTokenForArchiveAndPersonName(
    ...         new_token.archive, "bradsmith"
    ...     ).token
    ... )
    testtoken

Tokens are only returned if they match a current subscription:

    >>> from zope.security.proxy import removeSecurityProxy
    >>> from lp.soyuz.enums import ArchiveSubscriberStatus
    >>> removeSecurityProxy(subscription_to_joe_private_ppa).status = (
    ...     ArchiveSubscriberStatus.EXPIRED
    ... )

    >>> print(
    ...     token_set.getActiveTokenForArchiveAndPerson(
    ...         new_token.archive, new_token.person
    ...     )
    ... )
    None
    >>> print(
    ...     token_set.getActiveTokenForArchiveAndPersonName(
    ...         new_token.archive, "bradsmith"
    ...     )
    ... )
    None

    >>> removeSecurityProxy(subscription_to_joe_private_ppa).status = (
    ...     ArchiveSubscriberStatus.CURRENT
    ... )

Retrieving tokens works even if the user is subscribed to the archive via
multiple paths:

    >>> _ = login_person(joe)
    >>> _ = joe_private_ppa.newSubscription(teambrad2, joe)
    >>> login("brad@example.com")
    >>> print(
    ...     token_set.getActiveTokenForArchiveAndPerson(
    ...         new_token.archive, new_token.person
    ...     ).token
    ... )
    testtoken
    >>> print(
    ...     token_set.getActiveTokenForArchiveAndPersonName(
    ...         new_token.archive, "bradsmith"
    ...     ).token
    ... )
    testtoken

Tokens for inactive users are not returned.

    >>> from lp.services.identity.interfaces.account import AccountStatus

    >>> login("admin@canonical.com")
    >>> new_token.person.setAccountStatus(
    ...     AccountStatus.DEACTIVATED, None, "Bye"
    ... )
    >>> _ = login_person(joe)

    >>> print(
    ...     token_set.getActiveTokenForArchiveAndPerson(
    ...         new_token.archive, new_token.person
    ...     )
    ... )
    None
    >>> print(
    ...     token_set.getActiveTokenForArchiveAndPersonName(
    ...         new_token.archive, "bradsmith"
    ...     )
    ... )
    None

    >>> login("admin@canonical.com")
    >>> new_token.person.setAccountStatus(AccountStatus.ACTIVE, None, "Back")


Amending Tokens
---------------

Tokens can only be de-activated after they are created.  The calling user
also needs launchpad.Edit on the token, which means either someone with
IArchive launchpad.Append (as for creating new tokens) or an admin.

    >>> login("no-priv@canonical.com")
    >>> new_token.deactivate()
    Traceback (most recent call last):
    ...
    zope.security.interfaces.Unauthorized: ...

    >>> ignored = login_person(joe)
    >>> new_token.deactivate()

Deactivating sets the date_deactivated value.

    >>> new_token.date_deactivated is not None
    True

We can do this as an admin too:

    >>> new_token = joe_private_ppa.newAuthToken(bradsmith)
    >>> login("admin@canonical.com")
    >>> new_token.deactivate()

Deactivating a token stops it being returned from getByArchive().  The
previous count of 1 is now reduced to 0.

    >>> token_set.getByArchive(joe_private_ppa).count()
    0

The IArchiveAuthTokenSet.getActiveTokenForArchiveAndPerson() method will
also not return tokens that have been deactivated:

    >>> print(
    ...     token_set.getActiveTokenForArchiveAndPerson(
    ...         new_token.archive, new_token.person
    ...     )
    ... )
    None

