Archive signing
===============

`IArchive ` objects may be signed using its a IGPGKey pointed by its
'signing_key' attribute.

PPAs are created (activated, in production jargon) without a defined
'signing_key'. A GPG key will be generated later by a auxiliary script
and attached to the corresponding `IArchive`.

The secret part of the key will be stored in the path pointed by
`config.personalpackagearchive.signing_keys_root`, named by their
fingerprint. E.g.: ABCDEF0123456789ABCDDCBA0000111112345678.key

Once the signing key is available, the subsequent publications will
result in a signed repository.

The signed repository will contain a detached signature of the
top-level 'Release' file, named 'Release.gpg' and a ASCII-armored
export of the public GPG key (name 'key.gpg'). A clearsigned
'InRelease' file is also created, reducing the risk of clients
acquiring skewed copies of the content and its signature.

We will set up and use the test-keyserver.

    >>> from lp.testing.keyserver import KeyServerTac
    >>> tac = KeyServerTac()
    >>> tac.setUp()


Querying 'pending signing key' PPAs
-----------------------------------

`IArchiveSet.getArchivesPendingSigningKey` allows call-sites to query for
PPA pending signing key generation.

    >>> from lp.registry.interfaces.person import IPersonSet
    >>> from lp.soyuz.interfaces.archive import IArchiveSet

Only PPAs with at least one source publication are considered.

    >>> archive_set = getUtility(IArchiveSet)
    >>> for ppa in archive_set.getArchivesPendingSigningKey():
    ...     print(ppa.displayname)
    ...
    PPA for Celso Providelo
    PPA for Mark Shuttleworth

The PPA for 'No Privileges' user exists, is enabled and has no
signing, but it also does not contain any source publications, that's
why it's skipped in the getArchivesPendingSigningKey() results.

    >>> cprov = getUtility(IPersonSet).getByName("cprov")
    >>> no_priv = getUtility(IPersonSet).getByName("no-priv")

    >>> print(no_priv.archive.displayname)
    PPA for No Privileges Person

    >>> no_priv.archive.enabled
    True

    >>> print(no_priv.archive.signing_key)
    None

    >>> no_priv.archive.number_of_sources
    0

'No Privileges' PPA will be considered for signing_key creation when
we copy an arbitrary source into it.

    >>> a_source = cprov.archive.getPublishedSources().first()
    >>> copied_sources = a_source.copyTo(
    ...     a_source.distroseries, a_source.pocket, no_priv.archive
    ... )

    >>> for ppa in archive_set.getArchivesPendingSigningKey():
    ...     print(ppa.displayname)
    ...
    PPA for Celso Providelo
    PPA for Mark Shuttleworth
    PPA for No Privileges Person

Disabled PPAs are excluded from the 'PendingSigningKey' pool:

    >>> no_priv.archive.disable()

    >>> for ppa in archive_set.getArchivesPendingSigningKey():
    ...     print(ppa.displayname)
    ...
    PPA for Celso Providelo
    PPA for Mark Shuttleworth

Indeed, Marks's PPA does not have a defined 'signing_key'.

    >>> mark = getUtility(IPersonSet).getByName("mark")
    >>> print(mark.archive.signing_key)
    None

    >>> print(mark.archive.signing_key_fingerprint)
    None

We will select the only available IGPGKey from the sampledata.

    >>> foo_bar = getUtility(IPersonSet).getByName("name16")
    >>> [a_key] = foo_bar.gpg_keys
    >>> print(a_key.displayname)
    1024D/ABCDEF0123456789ABCDDCBA0000111112345678

And use it as the Mark's PPA signing key.

    >>> mark.archive.signing_key_owner = a_key.owner
    >>> mark.archive.signing_key_fingerprint = a_key.fingerprint
    >>> print(mark.archive.signing_key_fingerprint)
    ABCDEF0123456789ABCDDCBA0000111112345678

It will exclude Mark's PPA from the 'PendingSigningKey' pool as well.

    >>> for ppa in archive_set.getArchivesPendingSigningKey():
    ...     print(ppa.displayname)
    ...
    PPA for Celso Providelo

We can also query for copy archives.

    >>> from lp.soyuz.enums import ArchivePurpose
    >>> rebuild_archive = factory.makeArchive(
    ...     distribution=cprov.archive.distribution,
    ...     name="test-rebuild",
    ...     displayname="Test rebuild",
    ...     purpose=ArchivePurpose.COPY,
    ... )
    >>> _ = a_source.copyTo(
    ...     a_source.distroseries, a_source.pocket, rebuild_archive
    ... )
    >>> for archive in archive_set.getArchivesPendingSigningKey(
    ...     purpose=ArchivePurpose.COPY
    ... ):
    ...     print(archive.displayname)
    Test rebuild

Set up a signing key for the new test rebuild archive, and after that it no
longer shows up as pending signing key generation.

    >>> rebuild_archive.signing_key_owner = a_key.owner
    >>> rebuild_archive.signing_key_fingerprint = a_key.fingerprint
    >>> for archive in archive_set.getArchivesPendingSigningKey(
    ...     purpose=ArchivePurpose.COPY
    ... ):
    ...     print(archive.displayname)
    >>> rebuild_archive.signing_key_owner = None
    >>> rebuild_archive.signing_key_fingerprint = None


Generating a PPA signing key
----------------------------

As mentioned above, generated signing_keys will be stored in a
location defined by the system configuration.

    >>> from lp.services.config import config
    >>> print(config.personalpackagearchive.signing_keys_root)
    /var/tmp/ppa-signing-keys.test

In order to manipulate 'signing_keys' securily the target archive
object has to be adapted to `IArchiveGPGSigningKey`.

    >>> from lp.archivepublisher.interfaces.archivegpgsigningkey import (
    ...     IArchiveGPGSigningKey,
    ... )

We will adapt Celso's PPA after modifying its distribution to allow
proper publish configuration based on the sampledata.

    >>> cprov = getUtility(IPersonSet).getByName("cprov")

    >>> from lp.registry.interfaces.distribution import IDistributionSet
    >>> cprov.archive.distribution = getUtility(IDistributionSet).getByName(
    ...     "ubuntutest"
    ... )

    >>> archive_signing_key = IArchiveGPGSigningKey(cprov.archive)

Once adapted `IArchiveGPGSigningKey` is properly implemented.

    >>> from zope.interface.verify import verifyObject
    >>> verifyObject(IArchiveGPGSigningKey, archive_signing_key)
    True

`IArchiveGPGSigningKey` object contain the corresponding IArchive
object.

    >>> print(archive_signing_key.archive.displayname)
    PPA for Celso Providelo

It also implements exportSecretKey() which receive a `PymeKey` and
export it in the appropriate location.

We will create MockKey objects implementing only the methods required
to test the export functions.

    >>> class MockKey:
    ...     def __init__(self, secret):
    ...         self.secret = secret
    ...         self.fingerprint = "fpr"
    ...
    ...     def export(self):
    ...         return ("Secret %s" % self.secret).encode()
    ...

exportSecretKey() raises an error if given a public key.

    >>> archive_signing_key.exportSecretKey(MockKey(False))
    Traceback (most recent call last):
    ...
    AssertionError: Only secret keys should be exported.

Now, if given the right type of key, it will result in a exported key
in the expected path.

    >>> mock_key = MockKey(True)
    >>> archive_signing_key.exportSecretKey(mock_key)
    >>> with open(archive_signing_key.getPathForSecretKey(mock_key)) as f:
    ...     print(f.read())
    ...
    Secret True

At this point we can use the `IArchiveGPGSigningKey` to generate and
assign a real signing_key, although this procedure depends heavily on
machine entropy and ends up being very slow in our test machine.

    ### archive_signing_key.generateSigningKey()

We will use a pre-existing key in our tree which is virtually
identical to the one that would be generated. The key will be 'set' by
using a method `IArchiveGPGSigningKey` skips the key generation but uses
exactly the same procedure for setting the signing_key information.

    >>> import os
    >>> from lp.testing.gpgkeys import gpgkeysdir
    >>> key_path = os.path.join(gpgkeysdir, "ppa-sample@canonical.com.sec")
    >>> archive_signing_key.setSigningKey(key_path)

The assigned key is a sign-only, password-less 1024-RSA GPG key owner
by the 'PPA key guard' celebrity and represented by a IGPGKey record.

    >>> signing_key = archive_signing_key.archive.signing_key

    >>> from lp.registry.interfaces.gpg import IGPGKey
    >>> verifyObject(IGPGKey, signing_key)
    True

    >>> print(signing_key.owner.name)
    ppa-key-guard

    >>> print(signing_key.algorithm.title)
    RSA

    >>> print(signing_key.keysize)
    1024

    >>> print(signing_key.active)
    True

    >>> print(signing_key.can_encrypt)
    False

The generated key UID follows the "Launchpad PPA for %(person.displayname)s"
format.

    >>> from lp.services.gpg.interfaces import IGPGHandler
    >>> gpghandler = getUtility(IGPGHandler)

    >>> retrieved_key = gpghandler.retrieveKey(signing_key.fingerprint)

    >>> [uid] = retrieved_key.uids
    >>> print(uid.name)
    Launchpad PPA for Celso áéíóú Providelo

The secret key is securily stored in the designed configuration
path. So only the IGPGHandler itself can access it.

    >>> with open(archive_signing_key.getPathForSecretKey(signing_key)) as f:
    ...     print(f.read())
    ...
    -----BEGIN PGP PRIVATE KEY BLOCK-----
    ...
    -----END PGP PRIVATE KEY BLOCK-----
    <BLANKLINE>

If called against a PPA which already has a 'signing_key'
`generateSigningKey` will raise an error.

    >>> archive_signing_key.generateSigningKey()
    Traceback (most recent call last):
    ...
    AssertionError: Cannot override signing_keys.

Let's reset the gpg local key ring, so we can check that the public
key is available in the keyserver.

    >>> gpghandler.resetLocalState()

    >>> retrieved_key = gpghandler.retrieveKey(signing_key.fingerprint)
    >>> retrieved_key.fingerprint == signing_key.fingerprint
    True

As documented in archive.rst, when a named-ppa is created it is
already configured to used the same signing-key created for the
default PPA. We will create a named-ppa for Celso.

    >>> named_ppa = getUtility(IArchiveSet).new(
    ...     owner=cprov, purpose=ArchivePurpose.PPA, name="boing"
    ... )

As expected it will use the same key used in Celso's default PPA.

    >>> print(cprov.archive.signing_key.fingerprint)
    0D57E99656BEFB0897606EE9A022DD1F5001B46D

    >>> print(named_ppa.signing_key.fingerprint)
    0D57E99656BEFB0897606EE9A022DD1F5001B46D

We will reset the signing key of the just created named PPA,
simulating the situation when a the default PPA and a named-ppas get
created within the same cycle of the key-generator process.

    >>> from lp.services.propertycache import get_property_cache
    >>> login("foo.bar@canonical.com")
    >>> named_ppa.signing_key_owner = None
    >>> named_ppa.signing_key_fingerprint = None
    >>> del get_property_cache(named_ppa).signing_key
    >>> login(ANONYMOUS)

    >>> print(named_ppa.signing_key)
    None

Default PPAs are always created first and thus get their keys generated
before the named-ppa for the same owner. We submit the named-ppa to
the key generation procedure, as it would be normally in production.

    >>> named_ppa_signing_key = IArchiveGPGSigningKey(named_ppa)
    >>> named_ppa_signing_key.generateSigningKey()

Instead of generating a new key, the signing key from the default ppa
(Celso's default PPA) gets reused.

    >>> print(cprov.archive.signing_key.fingerprint)
    0D57E99656BEFB0897606EE9A022DD1F5001B46D

    >>> print(named_ppa.signing_key.fingerprint)
    0D57E99656BEFB0897606EE9A022DD1F5001B46D

We will reset the signing-keys for both PPA of Celso.

    >>> login("foo.bar@canonical.com")
    >>> cprov.archive.signing_key_owner = None
    >>> cprov.archive.signing_key_fingerprint = None
    >>> del get_property_cache(cprov.archive).signing_key
    >>> named_ppa.signing_key_owner = None
    >>> named_ppa.signing_key_fingerprint = None
    >>> del get_property_cache(named_ppa).signing_key
    >>> login(ANONYMOUS)

    >>> print(cprov.archive.signing_key)
    None

    >>> print(named_ppa.signing_key)
    None

Then modify the GPGHandler utility to return a sampledata key instead
of generating a new one, mainly for running the test faster and for
printing the context the key is generated.

    >>> def mock_key_generator(name, logger=None):
    ...     print("Generating:", name)
    ...     key_path = os.path.join(
    ...         gpgkeysdir, "ppa-sample@canonical.com.sec"
    ...     )
    ...     with open(key_path, "rb") as f:
    ...         return gpghandler.importSecretKey(f.read())
    ...

    >>> from zope.security.proxy import removeSecurityProxy
    >>> naked_gpghandler = removeSecurityProxy(gpghandler)
    >>> real_key_generator = naked_gpghandler.generateKey
    >>> naked_gpghandler.generateKey = mock_key_generator

When the signing key for the named-ppa is requested, it is generated
in the default PPA context then propagated to the named-ppa. The key is
named after the user, even if the default PPA name is something different.

    >>> cprov.display_name = "Not Celso Providelo"
    >>> named_ppa_signing_key = IArchiveGPGSigningKey(named_ppa)
    >>> named_ppa_signing_key.generateSigningKey()
    Generating: Launchpad PPA for Not Celso Providelo

    >>> print(cprov.archive.signing_key.fingerprint)
    0D57E99656BEFB0897606EE9A022DD1F5001B46D

    >>> print(named_ppa.signing_key.fingerprint)
    0D57E99656BEFB0897606EE9A022DD1F5001B46D

Keys generated for copy archives use a different naming scheme.

    >>> IArchiveGPGSigningKey(rebuild_archive).generateSigningKey()
    Generating: Launchpad copy archive ubuntu/test-rebuild

Restore the original functionality of GPGHandler.

    >>> naked_gpghandler.generateKey = real_key_generator


Signing PPA repository
----------------------

`IArchiveGPGSigningKey.signRepository` can be user to sign repositories
for archive which already contains a 'signing_key'.

Celso's default PPA will uses the testing signing key.

    >>> login("foo.bar@canonical.com")
    >>> cprov.archive.signing_key_owner = signing_key.owner
    >>> cprov.archive.signing_key_fingerprint = signing_key.fingerprint
    >>> del get_property_cache(cprov.archive).signing_key
    >>> login(ANONYMOUS)

When signing repositores we assert they contain the right format and
the expected file.

    >>> test_suite = "hoary"
    >>> archive_signing_key.signRepository(test_suite)
    Traceback (most recent call last):
    ...
    AssertionError: Release file doesn't exist in the repository:
    /var/tmp/ppa.test/cprov/ppa/ubuntutest/dists/hoary/Release

It produces a detached signature for the repository Release current
file contents, and a clearsigned InRelease file.

    >>> from lp.archivepublisher.config import getPubConfig
    >>> archive_root = getPubConfig(cprov.archive).archiveroot

    >>> suite_path = os.path.join(archive_root, "dists", test_suite)
    >>> os.makedirs(suite_path)
    >>> release_path = os.path.join(suite_path, "Release")

    >>> release_file = open(release_path, "w")
    >>> _ = release_file.write("This is a fake release file.")
    >>> release_file.close()

    >>> _ = archive_signing_key.signRepository(test_suite)

    >>> with open(release_path + ".gpg") as f:
    ...     print(f.read())
    ...
    -----BEGIN PGP SIGNATURE-----
    ...
    -----END PGP SIGNATURE-----
    <BLANKLINE>

    >>> inline_release_path = os.path.join(suite_path, "InRelease")
    >>> with open(inline_release_path) as f:
    ...     print(f.read())
    ...
    -----BEGIN PGP SIGNED MESSAGE-----
    ...
    -----BEGIN PGP SIGNATURE-----
    ...
    -----END PGP SIGNATURE-----
    <BLANKLINE>

The signature can be verified by retrieving the public key from the
keyserver.

    >>> gpghandler.resetLocalState()

    >>> retrieved_key = gpghandler.retrieveKey(signing_key.fingerprint)

    >>> with open(release_path, "rb") as release_file:
    ...     with open(release_path + ".gpg", "rb") as signature_file:
    ...         signature = gpghandler.getVerifiedSignature(
    ...             content=release_file.read(),
    ...             signature=signature_file.read(),
    ...         )
    ...

    >>> expected_fingerprint = (
    ...     archive_signing_key.archive.signing_key.fingerprint
    ... )
    >>> signature.fingerprint == expected_fingerprint
    True

    >>> with open(inline_release_path, "rb") as inline_release_file:
    ...     inline_signature = gpghandler.getVerifiedSignature(
    ...         content=inline_release_file.read()
    ...     )
    ...
    >>> inline_signature.fingerprint == expected_fingerprint
    True
    >>> print(inline_signature.plain_data.decode("UTF-8"))
    This is a fake release file.
    <BLANKLINE>

Finally, if we try to sign a repository for which the archive doesn't
have a 'signing_key' set,  it raises an error.

    >>> cprov.archive.signing_key_owner = None
    >>> cprov.archive.signing_key_fingerprint = None
    >>> del get_property_cache(cprov.archive).signing_key

    >>> archive_signing_key.signRepository(test_suite)
    Traceback (most recent call last):
    ...
    lp.archivepublisher.interfaces.archivegpgsigningkey.CannotSignArchive: No
    signing key available for PPA for Celso Providelo

We'll purge 'signing_keys_root' and the PPA repository root so that
other tests don't choke on it, and shut down the server.

    >>> import shutil
    >>> shutil.rmtree(config.personalpackagearchive.signing_keys_root)
    >>> shutil.rmtree(config.personalpackagearchive.root)
    >>> tac.tearDown()
