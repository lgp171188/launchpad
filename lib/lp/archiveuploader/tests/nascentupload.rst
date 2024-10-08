NascentUpload
=============

Import the test keys so we have them ready for verification

    >>> from lp.testing.gpgkeys import import_public_test_keys
    >>> import_public_test_keys()

We need to be logged into the security model in order to get any further

    >>> login("foo.bar@canonical.com")

For the purpose of this test, hoary needs to be an open (development)
distroseries so that we can upload to it.

    >>> from lp.registry.interfaces.distribution import IDistributionSet
    >>> from lp.registry.interfaces.series import SeriesStatus
    >>> ubuntu = getUtility(IDistributionSet)["ubuntu"]
    >>> hoary = ubuntu["hoary"]
    >>> hoary.status = SeriesStatus.DEVELOPMENT

A NascentUpload is a collection of files in a directory. They
represent what may turn out to be an acceptable upload to a launchpad
managed archive.

    >>> from lp.archiveuploader.nascentupload import NascentUpload
    >>> from lp.archiveuploader.tests import datadir, getPolicy

    >>> buildd_policy = getPolicy(
    ...     name="buildd", distro="ubuntu", distroseries="hoary"
    ... )

    >>> sync_policy = getPolicy(
    ...     name="sync", distro="ubuntu", distroseries="hoary"
    ... )

    >>> insecure_policy = getPolicy(
    ...     name="insecure", distro="ubuntu", distroseries="hoary"
    ... )

    >>> anything_policy = getPolicy(
    ...     name="anything", distro="ubuntu", distroseries="hoary"
    ... )


NascentUpload Processing
------------------------

Processing a NascentUpload consists of building files objects for each
specified file in the upload, executing all their specific checks and
collect all errors that may be generated. (see doc/nascentuploadfile.rst)

First, NascentUpload verifies that the changes file specified exist, and
tries to build a ChangesFile (see doc/nascentuploadfile.rst) object based
on that.

    >>> from lp.services.log.logger import DevNullLogger, FakeLogger

    >>> nonexistent = NascentUpload.from_changesfile_path(
    ...     datadir("DOES-NOT-EXIST"), buildd_policy, FakeLogger()
    ... )
    >>> nonexistent.process()
    Traceback (most recent call last):
    ...
    lp.archiveuploader.nascentupload.EarlyReturnUploadError: An error occurred
    that prevented further processing.
    >>> nonexistent.is_rejected
    True
    >>> print(nonexistent.rejection_message)
    Unable to read DOES-NOT-EXIST: ...

    >>> quodlibet = NascentUpload.from_changesfile_path(
    ...     datadir("quodlibet_0.13.1-1_i386.changes"),
    ...     anything_policy,
    ...     DevNullLogger(),
    ... )
    >>> quodlibet.process()
    >>> for f in quodlibet.changes.files:
    ...     print(f.filename, f)
    ...
    quodlibet_0.13.1-1_all.deb <...DebBinaryUploadFile...>
    quodlibet-ext_0.13.1-1_i386.deb <...DebBinaryUploadFile...>

After that there are also some overall_checks which helps to
investigate if the files contained in the uploads have a sane
relationship.

Now, the upload of quodlibet was signed, and the "anything" policy
verifies the signer. When we do signature verification, we parse the
maintainer field of the changes file, and ensure that a Person record
exists for it:

    >>> quodlibet.changes.signer is not None
    True
    >>> p = quodlibet.changes.maintainer["person"]
    >>> print(p.name)
    buildd
    >>> print(p.displayname)
    Ubuntu/i386 Build Daemon


Sourceful Uploads
.................

We can check if the uploads contents are 'sourceful' (contains source
files) or 'binaryful' (contain binary files):

    >>> quodlibet.sourceful
    False
    >>> quodlibet.binaryful
    True

We can distinguish between the arch-indep and arch-dep binary uploads
and therefore check if it matches what is described in the changesfiles:

    >>> quodlibet.archdep
    True
    >>> quodlibet.archindep
    True

The same happens for source uploads, where we can identify if a source
is 'native' (only a TARBALL, no diff + orig) or 'has_orig' (uses ORIG
+ DIFF source form).

    >>> ed_source_upload = NascentUpload.from_changesfile_path(
    ...     datadir("ed_0.2-20_i386.changes.source-only-unsigned"),
    ...     sync_policy,
    ...     DevNullLogger(),
    ... )

    >>> ed_source_upload.process()
    >>> for f in ed_source_upload.changes.files:
    ...     print(f.filename, f)
    ...
    ed_0.2-20.dsc <...DSCFile...>
    ed_0.2-20.diff.gz <...SourceUploadFile...>
    ed_0.2.orig.tar.gz <...SourceUploadFile...>

Since the sync_policy doesn't require the upload to be signed, we don't
try and parse the maintainer for it:

    >>> ed_source_upload.changes.signer is None
    True
    >>> print(ed_source_upload.changes.maintainer)
    None

ed_source upload is *sourceful*:

    >>> ed_source_upload.sourceful
    True
    >>> ed_source_upload.binaryful
    False

ed_source is uses ORIG + DIFF form:

    >>> from lp.archiveuploader.utils import determine_source_file_type
    >>> from lp.registry.interfaces.sourcepackage import SourcePackageFileType
    >>> def determine_file_types(upload):
    ...     return [
    ...         determine_source_file_type(uf.filename)
    ...         for uf in upload.changes.files
    ...     ]
    ...
    >>> def has_orig(upload):
    ...     return SourcePackageFileType.ORIG_TARBALL in determine_file_types(
    ...         upload
    ...     )
    ...
    >>> def has_native(upload):
    ...     return (
    ...         SourcePackageFileType.NATIVE_TARBALL
    ...         in determine_file_types(upload)
    ...     )
    ...

    >>> has_native(ed_source_upload)
    False
    >>> has_orig(ed_source_upload)
    True

For *sourceful* uploads 'archdep' and 'archindep' are always False:

    >>> ed_source_upload.archdep
    False
    >>> ed_source_upload.archindep
    False


Binaryful Uploads
.................

Let's try a simple binary upload:

    >>> ed_binary_upload = NascentUpload.from_changesfile_path(
    ...     datadir("ed_0.2-20_i386.changes.binary-only-unsigned"),
    ...     buildd_policy,
    ...     DevNullLogger(),
    ... )

    >>> ed_binary_upload.process()
    >>> for f in ed_binary_upload.changes.files:
    ...     print(f.filename, f)
    ...
    ed_0.2-20_i386.deb <...DebBinaryUploadFile...>

ed_binary is *binaryful*:

    >>> ed_binary_upload.sourceful
    False
    >>> ed_binary_upload.binaryful
    True

ed_binary contains only one 'architecture dependent binary':

    >>> ed_binary_upload.archdep
    True
    >>> ed_binary_upload.archindep
    False
    >>> ed_binary_upload.is_ppa
    False

As expected 'native' and 'hasorig' don't make any sense for binary
uploads, so they are always False:

    >>> has_native(ed_binary_upload)
    False
    >>> has_orig(ed_binary_upload)
    False

Since the binary policy lets things through unsigned, we don't try and
parse the maintainer for them either:

    >>> ed_binary_upload.changes.signer is None
    True
    >>> print(ed_binary_upload.changes.maintainer)
    None

Other ChangesFile information are also checked across the uploads
files specified. For instance, the changesfile Architecture list line
should match the files target architectures:

# Use the buildd policy as it accepts unsigned changes files and binary
# uploads.
    >>> modified_buildd_policy = getPolicy(
    ...     name="buildd", distro="ubuntu", distroseries="hoary"
    ... )

    >>> ed_mismatched_upload = NascentUpload.from_changesfile_path(
    ...     datadir("ed_0.2-20_i386.changes.mismatched-arch-unsigned"),
    ...     modified_buildd_policy,
    ...     DevNullLogger(),
    ... )

    >>> ed_mismatched_upload.process()

    >>> for f in ed_mismatched_upload.changes.files:
    ...     print(f.filename, f)
    ...
    ed_0.2-20_i386.deb <...DebBinaryUploadFile...>

    >>> for a in ed_mismatched_upload.changes.architectures:
    ...     print(a)
    ...
    amd64

Since the changesfile specify that only 'amd64' will be used and
there is a file that depends on 'i386' the upload is rejected:

    >>> print(ed_mismatched_upload.rejection_message)
    ed_0.2-20_i386.deb: control file lists arch as 'i386' which isn't in the
    changes file.


Uploads missing ORIG files
..........................

Uploads don't need to include the ORIG files when they're known to be in the
archive already.

    >>> insecure_policy_changed = getPolicy(
    ...     name="insecure", distro="ubuntu", distroseries="hoary"
    ... )

# Copy the .orig so that NascentUpload has access to it, although it
# wouldn't have been uploaded in practice because (as you can see below) the
# .orig was not included in the .changes file.
    >>> import shutil
    >>> _ = shutil.copy(datadir("ed_0.2.orig.tar.gz"), datadir("ed-0.2-21/"))

    >>> ed_upload = NascentUpload.from_changesfile_path(
    ...     datadir("ed-0.2-21/ed_0.2-21_source.changes"),
    ...     insecure_policy_changed,
    ...     DevNullLogger(),
    ... )

    >>> ed_upload.process()
    >>> ed_upload.is_rejected
    False
    >>> ed_upload.rejection_message
    ''

As we see here, the ORIG files were not included.

    >>> has_orig(ed_upload)
    False

And because of that it's not considered native.

    >>> has_native(ed_upload)
    False

But if we check the DSC we will find the reference to the already
known ORIG file:

    >>> for f in ed_upload.changes.dsc.files:
    ...     print(f.filename)
    ...
    ed_0.2.orig.tar.gz
    ed_0.2-21.diff.gz

    >>> success = ed_upload.do_accept()
    >>> success
    True

The notification message generated is described in more detail in
doc/nascentupload-announcements.rst.

Roll back everything related with ed_upload:

    >>> transaction.abort()
    >>> import os
    >>> os.remove(datadir("ed-0.2-21/ed_0.2.orig.tar.gz"))


Acceptance Work-flow
--------------------

The NascentUpload.do_accept method is the code which effectively adds
information to the database. Respective PackageUploadQueue,
SourcePackageRelease, Build and BinaryPackageRelease will only exist
after calling this method.

First up, construct an upload of just the ed source...

    >>> ed_src = NascentUpload.from_changesfile_path(
    ...     datadir("split-upload-test/ed_0.2-20_source.changes"),
    ...     sync_policy,
    ...     DevNullLogger(),
    ... )
    >>> ed_src.process()
    >>> ed_src.is_rejected
    False
    >>> success = ed_src.do_accept()
    >>> success
    True


SourcePackageRelease Details
............................

Retrieve the just-inserted SourcePackageRelease correspondent to 'ed'

    >>> ed_spr = ed_src.queue_root.sources[0].sourcepackagerelease

Check if we have rebuilt the change's author line properly (as
mentioned in bug # 30621)

    >>> print(ed_spr.changelog_entry)  # doctest: -NORMALIZE_WHITESPACE
    ed (0.2-20) unstable; urgency=low
    <BLANKLINE>
      * Move to dpatch; existing non-debian/ changes split into
    ...
        Closes: #130327
    <BLANKLINE>
     -- James Troup <james@nocrew.org>  Wed,  2 Apr 2003 17:19:47 +0100

Some new fields required for NoMoreAptFtparchive implementation are
present in SourcePackageRelease. They are cached from the DSC and used
for the archive index generation:

The 'Maintainer:' identity in RFC-822 format, as it was in DSC:

    >>> print(ed_spr.dsc_maintainer_rfc822)
    James Troup <james@nocrew.org>

Version of debian policy/standards used to build this source package:

    >>> print(ed_spr.dsc_standards_version)
    3.5.8.0

Format of the included DSC (.dsc) file:

    >>> print(ed_spr.dsc_format)
    1.0

Binaries names claimed to be resulted of this source, line with names
separated by space:

    >>> print(ed_spr.dsc_binaries)
    ed

Other DSC fields are also stored in the SourcePackageRelease record.

    >>> print(ed_spr.builddepends)
    dpatch

    >>> print(ed_spr.builddependsindep)
    <BLANKLINE>

    >>> print(ed_spr.build_conflicts)
    foo-bar

    >>> print(ed_spr.build_conflicts_indep)
    biscuit

The content of 'debian/copyright' is stored as the 'copyright'
attribute of SourcePackageRelease (note that its content is filtered
with encoding.guess()).

    >>> print(ed_spr.copyright)
    This is Debian GNU's prepackaged version of the FSF's GNU ed
    ...
    by the Foundation.

The ed source would be in NEW, so punt it into accepted.

    >>> ed_src.queue_root.setAccepted()


Allow uploads missing debian/copyright file
...........................................

Some source uploads use a fancy approach to build debian/copyright
on-the-fly for each binary they generate, sometimes using templates or
another similar feature.

Soyuz is prepared to accept those uploads (and avoid extra work on
maintainer's side), however it cannot store a proper
SourcePackageRelease.copyright content. See bug #134567.

    >>> nocopyright_src = NascentUpload.from_changesfile_path(
    ...     datadir(
    ...         "suite/nocopyright_1.0-1/nocopyright_1.0-1_source.changes"
    ...     ),
    ...     sync_policy,
    ...     DevNullLogger(),
    ... )
    >>> nocopyright_src.process()

    >>> nocopyright_src.is_rejected
    False
    >>> success = nocopyright_src.do_accept()
    >>> success
    True

On the absence of debian/copyright a warning is issued in the upload
processing log messages, then it can be further checked in Soyuz
production mailbox.

    >>> print(nocopyright_src.warning_message)
    <BLANKLINE>
    Upload Warnings:
    No copyright file found.

Nothing is stored in the SPR.copyright field.

    >>> nocopyright_queue = nocopyright_src.queue_root
    >>> nocopyright_spr = nocopyright_queue.sources[0].sourcepackagerelease

    >>> nocopyright_spr.copyright is None
    True

Let's reject the upload to avoid confusion during the next tests:

    >>> nocopyright_queue.setRejected()


Refuse to ACCEPT duplicated sources
...................................

Check if we refuse duplicated uploads even before publishing (bug #31038)
The uploaded source will be considered okay, since it still passing
all the consistency checks.

However there is another candidate, submitted before and not yet
published in the archive, which provides the same source package name
and source package version for the distroseries in question.

    >>> import logging
    >>> logger = FakeLogger()
    >>> logger.setLevel(logging.INFO)
    >>> ed_src_dup = NascentUpload.from_changesfile_path(
    ...     datadir("split-upload-test/ed_0.2-20_source.changes"),
    ...     sync_policy,
    ...     logger,
    ... )
    >>> ed_src_dup.process()
    >>> ed_src_dup.is_rejected
    False

This is a special trick to make do_accept() consider this upload OLD
(publication already present in the archive), so it will try to
automatically promote the queue entry to ACCEPTED.

    >>> for upload_file in ed_src_dup.changes.files:
    ...     upload_file.new = False
    ...

The we invoke do_accept() normally, since the upload is consistent.
but since the uniqueness check in IUpload.setAccepted() has detected
another accepted candidate that conflicts with the proposed one.
The upload will be rejected.

    >>> success = ed_src_dup.do_accept()
    INFO Exception while accepting:
    The source ed - 0.2-20 is already accepted in ubuntu/hoary and you
    cannot upload the same version within the same distribution. You
    have to modify the source version and re-upload.
    <BLANKLINE>
    Traceback...
    ...
    >>> success
    False
    >>> ed_src_dup.is_rejected
    True

    >>> print(ed_src_dup.rejection_message)
    The source ed - 0.2-20 is already accepted in ubuntu/hoary and you
    cannot upload the same version within the same distribution. You
    have to modify the source version and re-upload.


Staged Source and Binary upload with multiple binaries
......................................................

As we could see both, sources and binaries, get into Launchpad via
nascent-upload infrastructure, i.e., both are processed as 'uploads'.

However in Launchpad the package life-cycle can be described in 10
different stages:

  1. Source upload                     DRQ->DRQS->SPR
  2  Queue review (approval/rejection) DRQ ACCEPTED or REJECTED
  3. Source queue acceptance           pending SSPPH
  4. Source publication                published SSPPH
  5. Build creation                    needsbuild Build
  6. Build dispatching                 building Build
  7. Build gathering & Binary upload   fullybuilt Build + DRQ->DRQB->BPR
  8  Queue review (approval/rejection) DRQ ACCEPTED or REJECTED
  9. Binary queue acceptance          pending SBPPH
 10. Binary publication               published SBPPH

We will try to simulate this procedure for a source upload that
produces multiple binaries using sync policy:

    >>> sync_policy = getPolicy(
    ...     name="sync", distro="ubuntu", distroseries="hoary"
    ... )

Upload new source 'multibar', step 1:

    >>> multibar_src_upload = NascentUpload.from_changesfile_path(
    ...     datadir("suite/multibar_1.0-1/multibar_1.0-1_source.changes"),
    ...     sync_policy,
    ...     DevNullLogger(),
    ... )
    >>> multibar_src_upload.process()
    >>> success = multibar_src_upload.do_accept()
    >>> multibar_src_queue = multibar_src_upload.queue_root
    >>> multibar_src_queue.status.name
    'NEW'

    >>> len(multibar_src_queue.sources)
    1
    >>> multibar_spr = multibar_src_queue.sources[0].sourcepackagerelease
    >>> print(multibar_spr.title)
    multibar - 1.0-1

Once we have a new queue entry we are able to accept it, step 2:

    >>> multibar_src_queue.setAccepted()
    >>> multibar_src_queue.status.name
    'ACCEPTED'

Then the source gets accepted and published, step 3 and 4:

    >>> from lp.registry.interfaces.pocket import PackagePublishingPocket
    >>> from lp.soyuz.interfaces.publishing import IPublishingSet
    >>> getUtility(IPublishingSet).newSourcePublication(
    ...     multibar_src_queue.archive,
    ...     multibar_spr,
    ...     sync_policy.distroseries,
    ...     PackagePublishingPocket.RELEASE,
    ...     component=multibar_spr.component,
    ...     section=multibar_spr.section,
    ... )
    <SourcePackagePublishingHistory object>

Build creation is done based on the SourcePackageRelease object, step 5:

    >>> from lp.soyuz.interfaces.binarypackagebuild import (
    ...     IBinaryPackageBuildSet,
    ... )
    >>> multibar_build = getUtility(IBinaryPackageBuildSet).new(
    ...     multibar_spr,
    ...     multibar_src_queue.archive,
    ...     hoary["i386"],
    ...     PackagePublishingPocket.RELEASE,
    ... )

    >>> multibar_build.status.name
    'NEEDSBUILD'

We have just created a pending build record for hoary/i386.

Now we also assume that the build was dispatched by the worker-scanner
script, step 6.

On step 7, the worker-scanner collects the files generated on builders
and organises them as an ordinary binary upload having a changesfile
and the collection of DEB files produced.

At this point worker-scanner moves the upload to the appropriate path
(/srv/launchpad.net/builddmaster). A cron job invokes process-upload.py
with the 'buildd' upload policy and processes all files in that directory.

    >>> buildd_policy = getPolicy(
    ...     name="buildd", distro="ubuntu", distroseries="hoary"
    ... )

    >>> multibar_bin_upload = NascentUpload.from_changesfile_path(
    ...     datadir("suite/multibar_1.0-1/multibar_1.0-1_i386.changes"),
    ...     buildd_policy,
    ...     DevNullLogger(),
    ... )
    >>> multibar_bin_upload.process(build=multibar_build)
    >>> success = multibar_bin_upload.do_accept()

Now that we have successfully processed the binaries coming from a
builder, step 8, we can check the status of the database entities
related to it.

We have a NEW queue entry, containing the Build results:

    >>> multibar_bin_queue = multibar_bin_upload.queue_root
    >>> multibar_bin_queue.status.name
    'NEW'
    >>> len(multibar_bin_queue.builds)
    1

The build considered as 'producer' of the upload binaries is the same
that we have created in step 5:

    >>> build = multibar_bin_queue.builds[0].build
    >>> build.id == multibar_build.id
    True

Also the build record was updated to FULLYBUILT in nascentupload domain.

    >>> build.status.name
    'FULLYBUILT'

After certifying that the build record is marked as FULLYBUILT the
worker-scanner can safely update the build information (buildlog,
duration, etc) and clean the builder for anther job.

If the build record was not marked as FULLYBUILT during the
upload-time, it means that the worker should be held with the build
results for later processing.

Updating the build record as part of the upload processing avoids possible
inconsistencies when a binary upload was not processed correctly, then
was not stored in Launchpad database. The worker-scanner has no way to
recognise such situations easily, since process-upload exits with
success even when the upload is rejected. See bug #32261 for further info.

Chuck it all away again:

    >>> transaction.abort()


Post-Release pockets uploads
----------------------------

And this time, try an upload to -updates, it'll have to be signed etc because
we're using the insecure policy to check everything in it end-to-end. We have
to set hoary to CURRENT in order to do this because we're not allowed
to upload to -UPDATES in a DEVELOPMENT series.

    >>> from lp.testing.dbuser import lp_dbuser
    >>> with lp_dbuser():
    ...     hoary.status = SeriesStatus.CURRENT
    ...

Note that the policy do not have fixed distroseries, it will be
overridden by the changesfile:

    >>> norelease_sync_policy = getPolicy(name="sync", distro="ubuntu")

    >>> ed_src = NascentUpload.from_changesfile_path(
    ...     datadir("updates-upload-test/ed_0.2-20_source.changes"),
    ...     norelease_sync_policy,
    ...     DevNullLogger(),
    ... )
    >>> ed_src.process()
    >>> ed_src.is_rejected
    False

    >>> success = ed_src.do_accept()

    >>> print(ed_src.queue_root.pocket.name)
    UPDATES

Even though this went to a pocket and thus would be unapproved rather
than accepted, the ed upload ought still make it to NEW instead of
unapproved.

    >>> print(ed_src.queue_root.status.name)
    NEW

And pop it back to development now that we're done

    >>> with lp_dbuser():
    ...     hoary.status = SeriesStatus.DEVELOPMENT
    ...

Check the uploader behaviour against a missing orig.tar.gz file,
      bug # 30741.

    >>> ed21_src = NascentUpload.from_changesfile_path(
    ...     datadir("ed-0.2-21/ed_0.2-21_source.changes"),
    ...     sync_policy,
    ...     DevNullLogger(),
    ... )
    >>> ed21_src.process()
    >>> ed21_src.is_rejected
    True
    >>> print(ed21_src.rejection_message + "\nEND")
    Unable to find ed_0.2.orig.tar.gz in upload or distribution.
    Files specified in DSC are broken or missing, skipping package unpack
    verification.
    END


Installer source uploads doesn't contain 'Standards-Version'
------------------------------------------------------------

Check if we can accept a installer-source upload which doesn't have
'Standards-Version' field in DSC. See bug #75874 for further
information.

    >>> inst_src = NascentUpload.from_changesfile_path(
    ...     datadir("test75874_0.1_source.changes"),
    ...     sync_policy,
    ...     DevNullLogger(),
    ... )
    >>> inst_src.process()

    >>> inst_src.is_rejected
    False

    >>> success = inst_src.do_accept()
    >>> success
    True

Look for the respective SourcePackageRelease entry and inspect its
content, it should have all the required fields except the
'dsc_standards_version':

    >>> from lp.soyuz.enums import PackageUploadStatus
    >>> inst_queue = hoary.getPackageUploads(
    ...     PackageUploadStatus.NEW, name="test75874", exact_match=True
    ... )[0]
    >>> inst_spr = inst_queue.sources[0].sourcepackagerelease

    >>> print(inst_spr.dsc_maintainer_rfc822)
    Colin Watson <cjwatson@ubuntu.com>

    >>> print(inst_spr.dsc_binaries)
    test75874

    >>> inst_spr.dsc_standards_version is None
    True

Chuck it all away again

    >>> transaction.abort()


Insecure Policy
---------------

'insecure' upload policy forces NascentUpload to perform ACLs over the
DSC signature. It only allows 'source' upload where both, changesfile
and DSC, should be signed.

Import the test keys again since the transaction was aborted before.

    >>> from lp.testing.gpgkeys import import_public_test_keys
    >>> import_public_test_keys()

When using 'insecure' policy, NascentUpload instance stores the DSC
signing key reference as an IGPGKey:

    >>> bar_ok = NascentUpload.from_changesfile_path(
    ...     datadir("suite/bar_1.0-1/bar_1.0-1_source.changes"),
    ...     insecure_policy,
    ...     DevNullLogger(),
    ... )
    >>> bar_ok.process()
    >>> bar_ok.is_rejected
    False

    >>> from lp.testing import verifyObject
    >>> from lp.registry.interfaces.gpg import IGPGKey
    >>> from lp.registry.interfaces.person import IPersonSet

    >>> verifyObject(IGPGKey, bar_ok.changes.dsc.signingkey)
    True

    >>> verifyObject(IGPGKey, bar_ok.changes.signingkey)
    True

The second key of name16 person is used to sign uploads (the first gpgkey
record is a placeholder one, we used the second key):

    >>> name16 = getUtility(IPersonSet).getByName("name16")
    >>> uploader_key = name16.gpg_keys[1]
    >>> print(uploader_key.fingerprint)
    340CA3BB270E2716C9EE0B768E7EB7086C64A8C5

Both, DSC and changesfile are signed with Name16's second key.

    >>> print(bar_ok.changes.dsc.signingkey.fingerprint)
    340CA3BB270E2716C9EE0B768E7EB7086C64A8C5

    >>> print(bar_ok.changes.signingkey.fingerprint)
    340CA3BB270E2716C9EE0B768E7EB7086C64A8C5

Let's modify the current ACL rules for ubuntu, moving the upload
rights to all components from 'ubuntu-team' to 'mark':

    >>> from lp.services.database.interfaces import IStore
    >>> from lp.soyuz.model.archivepermission import ArchivePermission
    >>> with lp_dbuser():
    ...     new_uploader = getUtility(IPersonSet).getByName("mark")
    ...     store = IStore(ArchivePermission)
    ...     for permission in store.find(ArchivePermission):
    ...         permission.person = new_uploader
    ...     store.flush()
    ...

This time the upload will fail because the ACLs don't let
"name16", the key owner, upload a package.

    >>> bar_failed = NascentUpload.from_changesfile_path(
    ...     datadir("suite/bar_1.0-1/bar_1.0-1_source.changes"),
    ...     insecure_policy,
    ...     DevNullLogger(),
    ... )

    >>> bar_failed.process()
    >>> bar_failed.is_rejected
    True
    >>> print(bar_failed.rejection_message)
    The signer of this package has no upload rights to this distribution's
    primary archive.  Did you mean to upload to a PPA?

Even in a rejected upload using 'insecure' policy, the DSC signing key
and the changesfile sigining key are stored in NascentUpload instance
for further checks:

    >>> verifyObject(IGPGKey, bar_failed.changes.dsc.signingkey)
    True
    >>> verifyObject(IGPGKey, bar_failed.changes.signingkey)
    True

    >>> print(bar_failed.changes.dsc.signingkey.fingerprint)
    340CA3BB270E2716C9EE0B768E7EB7086C64A8C5

    >>> print(bar_failed.changes.signingkey.fingerprint)
    340CA3BB270E2716C9EE0B768E7EB7086C64A8C5

The ACL rules also enable us to specify that a user has a
package-specific upload right.  In the test package data, bar_1.0-1 is
signed by "Foo Bar" who is name16 in the sample data.  As shown above,
they currently have no upload rights at all to Ubuntu.  However, we can add
an ArchivePermission record to permit them to upload "bar" specifically.

    >>> from lp.registry.interfaces.sourcepackagename import (
    ...     ISourcePackageNameSet,
    ... )
    >>> from lp.soyuz.enums import ArchivePermissionType
    >>> with lp_dbuser():
    ...     bar_name = getUtility(ISourcePackageNameSet).getOrCreateByName(
    ...         "bar"
    ...     )
    ...     discard = ArchivePermission(
    ...         archive=ubuntu.main_archive,
    ...         person=name16,
    ...         permission=ArchivePermissionType.UPLOAD,
    ...         sourcepackagename=bar_name,
    ...         component=None,
    ...     )
    ...

Now try the "bar" upload:

    >>> bar2 = NascentUpload.from_changesfile_path(
    ...     datadir("suite/bar_1.0-1/bar_1.0-1_source.changes"),
    ...     insecure_policy,
    ...     DevNullLogger(),
    ... )
    >>> bar2.process()
    >>> bar2.is_rejected
    False

    >>> print(bar2.rejection_message)


Uploads to copy archives
------------------------

Uploads to copy archives are not allowed.

    >>> from lp.soyuz.enums import ArchivePurpose
    >>> from lp.soyuz.interfaces.archive import IArchiveSet
    >>> cprov = getUtility(IPersonSet).getByName("cprov")
    >>> copy_archive = getUtility(IArchiveSet).new(
    ...     owner=cprov,
    ...     purpose=ArchivePurpose.COPY,
    ...     distribution=ubuntu,
    ...     name="no-uploads-allowed",
    ... )
    >>> copy_archive_policy = getPolicy(
    ...     name="anything", distro="ubuntu", distroseries="hoary"
    ... )

Make this upload policy pertain to the copy archive.

    >>> copy_archive_policy.archive = copy_archive
    >>> quodlibet = NascentUpload.from_changesfile_path(
    ...     datadir("quodlibet_0.13.1-1_i386.changes"),
    ...     copy_archive_policy,
    ...     DevNullLogger(),
    ... )

Now process the upload.

    >>> quodlibet.process()

It goes through although destined for a copy archive because it's
a binary upload.

    >>> quodlibet.is_rejected
    False
    >>> quodlibet.binaryful
    True
