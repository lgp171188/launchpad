# Copyright 2009-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Testing infrastructure for the Launchpad application.

This module should not contain tests (but it should be tested).
"""

__all__ = [
    "GPGSigningContext",
    "is_security_proxied_or_harmless",
    "LaunchpadObjectFactory",
    "ObjectFactory",
    "remove_security_proxy_and_shout_at_engineer",
]


import base64
import hashlib
import os
import sys
import uuid
import warnings
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from email.encoders import encode_base64
from email.message import Message as EmailMessage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid
from functools import wraps
from io import BytesIO
from itertools import count
from textwrap import dedent

import six
from breezy.revision import Revision as BzrRevision
from brzbuildrecipe.recipe import BaseRecipeBranch
from cryptography.utils import int_to_bytes
from launchpadlib.launchpad import Launchpad
from lazr.jobrunner.jobrunner import SuspendJobException
from twisted.conch.ssh.common import MP, NS
from twisted.conch.test import keydata
from twisted.python.util import mergeFunctionMetadata
from zope.component import getUtility
from zope.interface.interfaces import ComponentLookupError
from zope.security.proxy import Proxy, ProxyFactory, removeSecurityProxy

from lp.app.enums import (
    PROPRIETARY_INFORMATION_TYPES,
    PUBLIC_INFORMATION_TYPES,
    InformationType,
    ServiceUsage,
)
from lp.app.interfaces.launchpad import ILaunchpadCelebrities
from lp.archivepublisher.interfaces.publisherconfig import IPublisherConfigSet
from lp.archiveuploader.dscfile import DSCFile
from lp.blueprints.enums import (
    NewSpecificationDefinitionStatus,
    SpecificationDefinitionStatus,
    SpecificationWorkItemStatus,
)
from lp.blueprints.interfaces.specification import ISpecificationSet
from lp.blueprints.interfaces.sprint import ISprintSet
from lp.bugs.interfaces.apportjob import IProcessApportBlobJobSource
from lp.bugs.interfaces.bug import CreateBugParams, IBugSet
from lp.bugs.interfaces.bugtask import (
    BugTaskImportance,
    BugTaskStatus,
    IBugTaskSet,
)
from lp.bugs.interfaces.bugtracker import BugTrackerType, IBugTrackerSet
from lp.bugs.interfaces.bugwatch import IBugWatchSet
from lp.bugs.interfaces.cve import CveStatus, ICveSet
from lp.bugs.interfaces.vulnerability import (
    IVulnerabilityActivitySet,
    IVulnerabilitySet,
    VulnerabilityChange,
    VulnerabilityStatus,
)
from lp.bugs.model.bug import FileBugData
from lp.buildmaster.builderproxy import FetchServicePolicy
from lp.buildmaster.enums import (
    BuildBaseImageType,
    BuilderResetProtocol,
    BuildStatus,
)
from lp.buildmaster.interfaces.builder import IBuilderSet
from lp.buildmaster.interfaces.processor import (
    IProcessorSet,
    ProcessorNotFound,
)
from lp.charms.interfaces.charmbase import ICharmBaseSet
from lp.charms.interfaces.charmrecipe import ICharmRecipeSet
from lp.charms.interfaces.charmrecipebuild import ICharmRecipeBuildSet
from lp.charms.model.charmrecipebuild import CharmFile
from lp.code.enums import (
    BranchMergeProposalStatus,
    BranchSubscriptionNotificationLevel,
    BranchType,
    CodeImportMachineState,
    CodeImportResultStatus,
    CodeImportReviewStatus,
    CodeReviewNotificationLevel,
    GitObjectType,
    GitRepositoryType,
    RevisionControlSystems,
    RevisionStatusArtifactType,
    TargetRevisionControlSystems,
)
from lp.code.errors import UnknownBranchTypeError
from lp.code.interfaces.branch import IBranch
from lp.code.interfaces.branchnamespace import get_branch_namespace
from lp.code.interfaces.cibuild import ICIBuildSet
from lp.code.interfaces.codeimport import ICodeImportSet
from lp.code.interfaces.codeimportevent import ICodeImportEventSet
from lp.code.interfaces.codeimportmachine import ICodeImportMachineSet
from lp.code.interfaces.codeimportresult import ICodeImportResultSet
from lp.code.interfaces.gitnamespace import get_git_namespace
from lp.code.interfaces.gitref import IGitRef, IGitRefRemoteSet
from lp.code.interfaces.gitrepository import IGitRepository
from lp.code.interfaces.linkedbranch import ICanHasLinkedBranch
from lp.code.interfaces.revision import IRevisionSet
from lp.code.interfaces.revisionstatus import (
    IRevisionStatusArtifactSet,
    IRevisionStatusReportSet,
)
from lp.code.interfaces.sourcepackagerecipe import (
    MINIMAL_RECIPE_TEXT_BZR,
    MINIMAL_RECIPE_TEXT_GIT,
    ISourcePackageRecipeSource,
)
from lp.code.interfaces.sourcepackagerecipebuild import (
    ISourcePackageRecipeBuildSource,
)
from lp.code.model.diff import Diff, PreviewDiff
from lp.code.tests.helpers import GitHostingFixture
from lp.crafts.interfaces.craftrecipe import ICraftRecipeSet
from lp.crafts.interfaces.craftrecipebuild import ICraftRecipeBuildSet
from lp.crafts.model.craftrecipebuild import CraftFile
from lp.oci.interfaces.ocipushrule import IOCIPushRuleSet
from lp.oci.interfaces.ocirecipe import IOCIRecipeSet
from lp.oci.interfaces.ocirecipebuild import IOCIRecipeBuildSet
from lp.oci.interfaces.ociregistrycredentials import IOCIRegistryCredentialsSet
from lp.oci.model.ocirecipebuild import OCIFile
from lp.oci.model.ocirecipebuildjob import (
    OCIRecipeBuildJob,
    OCIRecipeBuildJobType,
)
from lp.registry.enums import (
    BranchSharingPolicy,
    BugSharingPolicy,
    DistroSeriesDifferenceStatus,
    DistroSeriesDifferenceType,
    SpecificationSharingPolicy,
    TeamMembershipPolicy,
)
from lp.registry.interfaces.accesspolicy import (
    IAccessArtifactGrantSource,
    IAccessArtifactSource,
    IAccessPolicyArtifactSource,
    IAccessPolicyGrantSource,
    IAccessPolicySource,
)
from lp.registry.interfaces.distribution import IDistribution, IDistributionSet
from lp.registry.interfaces.distributionmirror import (
    MirrorContent,
    MirrorSpeed,
)
from lp.registry.interfaces.distributionsourcepackage import (
    IDistributionSourcePackage,
)
from lp.registry.interfaces.distroseries import IDistroSeries
from lp.registry.interfaces.distroseriesdifference import (
    IDistroSeriesDifferenceSource,
)
from lp.registry.interfaces.distroseriesdifferencecomment import (
    IDistroSeriesDifferenceCommentSource,
)
from lp.registry.interfaces.distroseriesparent import IDistroSeriesParentSet
from lp.registry.interfaces.gpg import IGPGKeySet
from lp.registry.interfaces.mailinglist import (
    IMailingListSet,
    MailingListStatus,
)
from lp.registry.interfaces.mailinglistsubscription import (
    MailingListAutoSubscribePolicy,
)
from lp.registry.interfaces.ociproject import IOCIProjectSet
from lp.registry.interfaces.ociprojectname import IOCIProjectNameSet
from lp.registry.interfaces.packaging import IPackagingUtil, PackagingType
from lp.registry.interfaces.person import (
    IPerson,
    IPersonSet,
    PersonCreationRationale,
)
from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.registry.interfaces.poll import IPollSet, PollAlgorithm, PollSecrecy
from lp.registry.interfaces.product import IProduct, IProductSet, License
from lp.registry.interfaces.productseries import IProductSeries
from lp.registry.interfaces.projectgroup import IProjectGroupSet
from lp.registry.interfaces.series import SeriesStatus
from lp.registry.interfaces.sourcepackage import (
    ISourcePackage,
    SourcePackageFileType,
    SourcePackageType,
    SourcePackageUrgency,
)
from lp.registry.interfaces.sourcepackagename import ISourcePackageNameSet
from lp.registry.interfaces.ssh import ISSHKeySet
from lp.registry.model.commercialsubscription import CommercialSubscription
from lp.registry.model.karma import KarmaTotalCache
from lp.registry.model.milestone import Milestone
from lp.registry.model.packaging import Packaging
from lp.registry.model.suitesourcepackage import SuiteSourcePackage
from lp.rocks.interfaces.rockbase import IRockBaseSet
from lp.rocks.interfaces.rockrecipe import IRockRecipeSet
from lp.rocks.interfaces.rockrecipebuild import IRockRecipeBuildSet
from lp.rocks.model.rockrecipebuild import RockFile
from lp.services.auth.interfaces import IAccessTokenSet
from lp.services.auth.utils import create_access_token_secret
from lp.services.compat import message_as_bytes
from lp.services.config import config
from lp.services.database.constants import DEFAULT, UTC_NOW
from lp.services.database.interfaces import (
    IPrimaryStore,
    IStore,
    IStoreSelector,
)
from lp.services.database.policy import PrimaryDatabasePolicy
from lp.services.database.sqlbase import flush_database_updates
from lp.services.gpg.interfaces import GPGKeyAlgorithm, IGPGHandler
from lp.services.identity.interfaces.account import (
    AccountCreationRationale,
    AccountStatus,
    IAccountSet,
)
from lp.services.identity.interfaces.emailaddress import (
    EmailAddressStatus,
    IEmailAddressSet,
)
from lp.services.identity.model.account import Account
from lp.services.librarian.interfaces import ILibraryFileAliasSet
from lp.services.librarian.model import LibraryFileAlias, LibraryFileContent
from lp.services.mail.signedmessage import SignedMessage
from lp.services.messages.model.message import Message, MessageChunk
from lp.services.oauth.interfaces import IOAuthConsumerSet
from lp.services.openid.model.openididentifier import OpenIdIdentifier
from lp.services.propertycache import clear_property_cache, get_property_cache
from lp.services.signing.enums import SigningKeyType
from lp.services.signing.interfaces.signingkey import IArchiveSigningKeySet
from lp.services.signing.model.signingkey import SigningKey
from lp.services.temporaryblobstorage.interfaces import (
    ITemporaryStorageManager,
)
from lp.services.temporaryblobstorage.model import TemporaryBlobStorage
from lp.services.utils import AutoDecorateMetaClass
from lp.services.webapp.interfaces import OAuthPermission
from lp.services.webapp.sorting import sorted_version_numbers
from lp.services.webhooks.interfaces import IWebhookSet
from lp.services.worlddata.interfaces.country import ICountrySet
from lp.services.worlddata.interfaces.language import ILanguageSet
from lp.snappy.interfaces.snap import ISnapSet
from lp.snappy.interfaces.snapbase import ISnapBaseSet
from lp.snappy.interfaces.snapbuild import ISnapBuildSet
from lp.snappy.interfaces.snappyseries import ISnappySeriesSet
from lp.snappy.model.snapbuild import SnapFile
from lp.soyuz.adapters.overrides import SourceOverride
from lp.soyuz.adapters.packagelocation import PackageLocation
from lp.soyuz.enums import (
    ArchivePublishingMethod,
    ArchivePurpose,
    ArchiveRepositoryFormat,
    BinaryPackageFileType,
    BinaryPackageFormat,
    DistroArchSeriesFilterSense,
    PackageDiffStatus,
    PackagePublishingPriority,
    PackagePublishingStatus,
    PackageUploadCustomFormat,
    PackageUploadStatus,
)
from lp.soyuz.interfaces.archive import IArchiveSet, default_name_by_purpose
from lp.soyuz.interfaces.archivefile import IArchiveFileSet
from lp.soyuz.interfaces.archivepermission import IArchivePermissionSet
from lp.soyuz.interfaces.binarypackagebuild import IBinaryPackageBuildSet
from lp.soyuz.interfaces.binarypackagename import IBinaryPackageNameSet
from lp.soyuz.interfaces.component import IComponent, IComponentSet
from lp.soyuz.interfaces.livefs import ILiveFSSet
from lp.soyuz.interfaces.livefsbuild import ILiveFSBuildSet
from lp.soyuz.interfaces.packagecopyjob import IPlainPackageCopyJobSource
from lp.soyuz.interfaces.packageset import IPackagesetSet
from lp.soyuz.interfaces.publishing import IPublishingSet
from lp.soyuz.interfaces.queue import IPackageUploadSet
from lp.soyuz.interfaces.section import ISectionSet
from lp.soyuz.model.component import ComponentSelection
from lp.soyuz.model.distributionsourcepackagecache import (
    DistributionSourcePackageCache,
)
from lp.soyuz.model.distroarchseriesfilter import DistroArchSeriesFilter
from lp.soyuz.model.files import BinaryPackageFile
from lp.soyuz.model.livefsbuild import LiveFSFile
from lp.soyuz.model.packagediff import PackageDiff
from lp.testing import (
    ANONYMOUS,
    admin_logged_in,
    celebrity_logged_in,
    launchpadlib_for,
    login,
    login_as,
    login_person,
    person_logged_in,
    run_with_login,
    time_counter,
    with_celebrity_logged_in,
)
from lp.testing.dbuser import dbuser
from lp.translations.enums import LanguagePackType, RosettaImportStatus
from lp.translations.interfaces.languagepack import ILanguagePackSet
from lp.translations.interfaces.potemplate import IPOTemplateSet
from lp.translations.interfaces.side import TranslationSide
from lp.translations.interfaces.translationfileformat import (
    TranslationFileFormat,
)
from lp.translations.interfaces.translationgroup import ITranslationGroupSet
from lp.translations.interfaces.translationimportqueue import (
    ITranslationImportQueue,
)
from lp.translations.interfaces.translationmessage import (
    RosettaTranslationOrigin,
)
from lp.translations.interfaces.translationsperson import ITranslationsPerson
from lp.translations.interfaces.translationtemplatesbuild import (
    ITranslationTemplatesBuildSource,
)
from lp.translations.interfaces.translator import ITranslatorSet
from lp.translations.model.translationtemplateitem import (
    TranslationTemplateItem,
)
from lp.translations.utilities.sanitize import sanitize_translations_from_webui

SPACE = " "


def default_primary_store(func):
    """Decorator to temporarily set the default Store to the primary.

    In some cases, such as in the middle of a page test story,
    we might be calling factory methods with the default Store set
    to the standby which breaks stuff. For instance, if we set an account's
    password that needs to happen on the primary store and this is forced.
    However, if we then read it back the default Store has to be used.
    """

    @wraps(func)
    def with_default_primary_store(*args, **kw):
        try:
            store_selector = getUtility(IStoreSelector)
        except ComponentLookupError:
            # Utilities not registered. No policies.
            return func(*args, **kw)
        store_selector.push(PrimaryDatabasePolicy())
        try:
            return func(*args, **kw)
        finally:
            store_selector.pop()

    return mergeFunctionMetadata(func, with_default_primary_store)


# We use this for default parameters where None has a specific meaning. For
# example, makeBranch(product=None) means "make a junk branch". None, because
# None means "junk branch".
_DEFAULT = object()


class GPGSigningContext:
    """A helper object to hold the key, password and mode."""

    def __init__(self, key, password="", mode=None):
        self.key = key
        self.password = password
        self.mode = mode


class ObjectFactory(metaclass=AutoDecorateMetaClass):
    """Factory methods for creating basic Python objects."""

    # This allocates process-wide unique integers.  We count on Python doing
    # only cooperative threading to make this safe across threads.

    __decorators = (default_primary_store,)

    _unique_int_counter = count(100000)

    def getUniqueEmailAddress(self):
        return "%s@example.com" % self.getUniqueUnicode("email")

    def getUniqueInteger(self):
        """Return an integer unique to this factory instance.

        For each thread, this will be a series of increasing numbers, but the
        starting point will be unique per thread.
        """
        return next(ObjectFactory._unique_int_counter)

    def getUniqueHexString(self, digits=None):
        """Return a unique hexadecimal string.

        :param digits: The number of digits in the string. 'None' means you
            don't care.
        :return: A hexadecimal string, with 'a'-'f' in lower case.
        """
        hex_number = "%x" % self.getUniqueInteger()
        if digits is not None:
            hex_number = hex_number.zfill(digits)
        return hex_number

    # XXX cjwatson 2020-09-22: Most users of getUniqueString should use
    # either getUniqueBytes or getUniqueUnicode instead.  Remove this
    # comment when all remaining instances have been audited as explicitly
    # requiring native strings (i.e. bytes on Python 2, text on Python 3).
    def getUniqueString(self, prefix=None):
        """Return a native string unique to this factory instance.

        The string returned will always be a valid name that can be used in
        Launchpad URLs.

        :param prefix: Used as a prefix for the unique string. If
            unspecified, generates a name starting with 'unique' and
            mentioning the calling source location.
        """
        if prefix is None:
            frame = sys._getframe(2)
            source_filename = frame.f_code.co_filename
            # Dots and dashes cause trouble with some consumers of these
            # names.
            source = (
                os.path.basename(source_filename)
                .replace("_", "-")
                .replace(".", "-")
            )
            if source.startswith("<doctest "):
                # Like '-<doctest xx-build-summary-rst[10]>'.
                source = (
                    source.replace("<doctest ", "")
                    .replace("[", "")
                    .replace("]>", "")
                )
            prefix = "unique-from-%s-line%d" % (source, frame.f_lineno)
        string = "%s-%s" % (prefix, self.getUniqueInteger())
        return string

    def getUniqueBytes(self, prefix=None):
        return six.ensure_binary(self.getUniqueString(prefix=prefix))

    def getUniqueUnicode(self, prefix=None):
        return six.ensure_text(self.getUniqueString(prefix=prefix))

    def getUniqueURL(self, scheme=None, host=None):
        """Return a URL unique to this run of the test case."""
        if scheme is None:
            scheme = "http"
        if host is None:
            host = "%s.example.com" % self.getUniqueUnicode("domain")
        return "%s://%s/%s" % (scheme, host, self.getUniqueUnicode("path"))

    def getUniqueDate(self):
        """Return a unique date since January 1 2009.

        Each date returned by this function will more recent (or further into
        the future) than the previous one.
        """
        epoch = datetime(2009, 1, 1, tzinfo=timezone.utc)
        return epoch + timedelta(minutes=self.getUniqueInteger())


def check_security_proxy(func):
    """
    Decorator for factory methods to ensure that the returned objects are
    either harmless or wrapped with a security proxy.
    """

    @wraps(func)
    def wrapped(*args, **kw):
        result = func(*args, **kw)
        if not is_security_proxied_or_harmless(result):
            raise UnproxiedFactoryMethodError(func.__name__)
        return result

    return wrapped


class LaunchpadObjectFactory(ObjectFactory):
    """Factory methods for creating Launchpad objects.

    All the factory methods should be callable with no parameters.
    When this is done, the returned object should have unique references
    for any other required objects.

    Factory methods must always return objects that are either harmless (see
    `is_security_proxied_or_harmless`) or wrapped with a security proxy.
    The purpose of this is to ensure that production code works when given
    security-proxied objects.  It's OK for test-only code (including factory
    methods) to remove security proxies as needed when creating test
    objects, although when they're making assertions about the behaviour of
    production code then they should make sure to log in as an appropriate
    user (for webapp code) or use a Zopeless layer (for scripts) in order to
    make sure that they're accurately simulating how the code will run in
    production.
    """

    __decorators = (check_security_proxy,)

    def loginAsAnyone(self, participation=None):
        """Log in as an arbitrary person.

        If you want to log in as a celebrity, including admins, see
        `lp.testing.login_celebrity`.
        """
        login(ANONYMOUS)
        person = self.makePerson()
        login_as(person, participation)
        return person

    @with_celebrity_logged_in("admin")
    def makeAdministrator(self, name=None, email=None):
        return self.makePerson(
            name=name,
            email=email,
            member_of=[getUtility(ILaunchpadCelebrities).admin],
        )

    @with_celebrity_logged_in("admin")
    def makeRegistryExpert(self, name=None, email="expert@example.com"):
        return self.makePerson(
            name=name,
            email=email,
            member_of=[getUtility(ILaunchpadCelebrities).registry_experts],
        )

    @with_celebrity_logged_in("admin")
    def makeCommercialAdmin(self, name=None, email=None):
        return self.makePerson(
            name=name,
            email=email,
            member_of=[getUtility(ILaunchpadCelebrities).commercial_admin],
        )

    def makeCopyArchiveLocation(
        self, distribution=None, owner=None, name=None, enabled=True
    ):
        """Create and return a new arbitrary location for copy packages."""
        copy_archive = self.makeArchive(
            distribution, owner, name, ArchivePurpose.COPY, enabled
        )

        distribution = copy_archive.distribution
        distroseries = distribution.currentseries
        pocket = PackagePublishingPocket.RELEASE

        location = PackageLocation(
            copy_archive, distribution, distroseries, pocket
        )
        return ProxyFactory(location)

    def makeAccount(
        self,
        displayname=None,
        status=AccountStatus.ACTIVE,
        rationale=AccountCreationRationale.UNKNOWN,
    ):
        """Create and return a new Account."""
        if displayname is None:
            displayname = self.getUniqueString("displayname")
        account = getUtility(IAccountSet).new(rationale, displayname)
        removeSecurityProxy(account).status = status
        self.makeOpenIdIdentifier(account)
        return account

    def makeOpenIdIdentifier(self, account, identifier=None):
        """Attach an OpenIdIdentifier to an Account."""
        # Unfortunately, there are many tests connecting as many
        # different database users that expect to be able to create
        # working accounts using these factory methods. The stored
        # procedure provides a work around and avoids us having to
        # grant INSERT rights to these database users and avoids the
        # security problems that would cause. The stored procedure
        # ensures that there is at least one OpenId Identifier attached
        # to the account that can be used to login. If the OpenId
        # Identifier needed to be created, it will not be usable in the
        # production environments so access to execute this stored
        # procedure cannot be used to compromise accounts.
        IPrimaryStore(OpenIdIdentifier).execute(
            "SELECT add_test_openid_identifier(%s)", (account.id,)
        )

    def makeGPGKey(self, owner, fingerprint=None, keyid=None, keysize=None):
        """Give 'owner' a crappy GPG key for the purposes of testing."""
        if not keyid:
            keyid = self.getUniqueHexString(digits=8).upper()
        if not fingerprint:
            fingerprint = keyid + "A" * 32
        if not keysize:
            keysize = self.getUniqueInteger()
        keyset = getUtility(IGPGKeySet)
        key = keyset.new(
            owner,
            keyid=keyid,
            fingerprint=fingerprint,
            keysize=keysize,
            algorithm=GPGKeyAlgorithm.R,
            active=True,
            can_encrypt=False,
        )
        return key

    def makePerson(
        self,
        email=None,
        name=None,
        displayname=None,
        account_status=None,
        email_address_status=None,
        hide_email_addresses=False,
        time_zone=None,
        latitude=None,
        longitude=None,
        description=None,
        selfgenerated_bugnotifications=False,
        member_of=(),
        karma=None,
    ):
        """Create and return a new, arbitrary Person.

        :param email: The email address for the new person.
        :param name: The name for the new person.
        :param email_address_status: If specified, the status of the email
            address is set to the email_address_status.
        :param displayname: The display name to use for the person.
        :param hide_email_addresses: Whether or not to hide the person's email
            address(es) from other users.
        :param time_zone: This person's time zone, as a string.
        :param latitude: This person's latitude, as a float.
        :param longitude: This person's longitude, as a float.
        :param selfgenerated_bugnotifications: Receive own bugmail.
        """
        if name is None:
            name = self.getUniqueString("person-name")
        if account_status == AccountStatus.PLACEHOLDER:
            # Placeholder people are pretty special, so just create and
            # bail out.
            openid = self.getUniqueUnicode("%s-openid" % name)
            person = getUtility(IPersonSet).createPlaceholderPerson(
                openid, name
            )
            return person
        # By default, make the email address preferred.
        if email is None:
            email = self.getUniqueEmailAddress()
        if (
            email_address_status is None
            or email_address_status == EmailAddressStatus.VALIDATED
        ):
            email_address_status = EmailAddressStatus.PREFERRED
        if account_status == AccountStatus.NOACCOUNT:
            email_address_status = EmailAddressStatus.NEW
        person, email = getUtility(IPersonSet).createPersonAndEmail(
            email,
            rationale=PersonCreationRationale.UNKNOWN,
            name=name,
            displayname=displayname,
            hide_email_addresses=hide_email_addresses,
        )
        naked_person = removeSecurityProxy(person)
        if description is not None:
            naked_person.description = description

        if (
            time_zone is not None
            or latitude is not None
            or longitude is not None
        ):
            naked_person.setLocation(latitude, longitude, time_zone, person)

        # Make sure the non-security-proxied object is not returned.
        del naked_person

        if selfgenerated_bugnotifications:
            # Set it explicitly only when True because the default
            # is False.
            person.selfgenerated_bugnotifications = True

        # To make the person someone valid in Launchpad, validate the
        # email.
        if email_address_status == EmailAddressStatus.PREFERRED:
            account = IPrimaryStore(Account).get(Account, person.account_id)
            account.status = AccountStatus.ACTIVE
            person.setPreferredEmail(email)

        removeSecurityProxy(email).status = email_address_status

        once_active = (
            AccountStatus.DEACTIVATED,
            AccountStatus.SUSPENDED,
            AccountStatus.DECEASED,
        )
        if account_status:
            if account_status in once_active:
                removeSecurityProxy(person.account).status = (
                    AccountStatus.ACTIVE
                )
            removeSecurityProxy(person.account).status = account_status
        self.makeOpenIdIdentifier(person.account)

        for team in member_of:
            with person_logged_in(team.teamowner):
                team.addMember(person, team.teamowner)

        if karma is not None:
            with dbuser("karma"):
                # Give the user karma to make the user non-probationary.
                KarmaTotalCache(person=person, karma_total=karma)
        # Ensure updated ValidPersonCache
        flush_database_updates()
        return person

    def makePersonByName(
        self,
        first_name,
        set_preferred_email=True,
        use_default_autosubscribe_policy=False,
    ):
        """Create a new person with the given first name.

        The person will be given two email addresses, with the 'long form'
        (e.g. anne.person@example.com) as the preferred address.  Return
        the new person object.

        The person will also have their mailing list auto-subscription
        policy set to 'NEVER' unless 'use_default_autosubscribe_policy' is
        set to True. (This requires the Launchpad.Edit permission).  This
        is useful for testing, where we often want precise control over
        when a person gets subscribed to a mailing list.

        :param first_name: First name of the person, capitalized.
        :type first_name: string
        :param set_preferred_email: Flag specifying whether
            <name>.person@example.com should be set as the user's
            preferred email address.
        :type set_preferred_email: bool
        :param use_default_autosubscribe_policy: Flag specifying whether
            the person's `mailing_list_auto_subscribe_policy` should be set.
        :type use_default_autosubscribe_policy: bool
        :return: The newly created person.
        :rtype: `IPerson`
        """
        variable_name = first_name.lower()
        full_name = first_name + " Person"
        # E.g. firstname.person@example.com will be an alternative address.
        preferred_address = variable_name + ".person@example.com"
        # E.g. aperson@example.org will be the preferred address.
        alternative_address = variable_name[0] + "person@example.org"
        person, email = getUtility(IPersonSet).createPersonAndEmail(
            preferred_address,
            PersonCreationRationale.OWNER_CREATED_LAUNCHPAD,
            name=variable_name,
            displayname=full_name,
        )
        if set_preferred_email:
            # setPreferredEmail no longer activates the account
            # automatically.
            account = IPrimaryStore(Account).get(Account, person.account_id)
            account.reactivate("Activated by factory.makePersonByName")
            person.setPreferredEmail(email)

        if not use_default_autosubscribe_policy:
            # Shut off list auto-subscription so that we have direct control
            # over subscriptions in the doctests.
            with person_logged_in(person):
                person.mailing_list_auto_subscribe_policy = (
                    MailingListAutoSubscribePolicy.NEVER
                )
        account = IPrimaryStore(Account).get(Account, person.account_id)
        getUtility(IEmailAddressSet).new(
            alternative_address, person, EmailAddressStatus.VALIDATED
        )
        return person

    def makeEmail(self, address, person, email_status=None):
        """Create a new email address for a person.

        :param address: The email address to create.
        :type address: string
        :param person: The person to assign the email address to.
        :type person: `IPerson`
        :param email_status: The default status of the email address,
            if given.  If not given, `EmailAddressStatus.VALIDATED`
            will be used.
        :type email_status: `EmailAddressStatus`
        :return: The newly created email address.
        :rtype: `IEmailAddress`
        """
        if email_status is None:
            email_status = EmailAddressStatus.VALIDATED
        return getUtility(IEmailAddressSet).new(address, person, email_status)

    def makeTeam(
        self,
        owner=None,
        displayname=None,
        email=None,
        name=None,
        description=None,
        icon=None,
        logo=None,
        membership_policy=TeamMembershipPolicy.OPEN,
        visibility=None,
        members=None,
    ):
        """Create and return a new, arbitrary Team.

        :param owner: The person or person name to use as the team's owner.
            If not given, a person will be auto-generated.
        :type owner: `IPerson` or string
        :param displayname: The team's display name.  If not given we'll use
            the auto-generated name.
        :param description: Team team's description.
        :type description string:
        :param email: The email address to use as the team's contact address.
        :type email: string
        :param icon: The team's icon.
        :param logo: The team's logo.
        :param membership_policy: The membership policy of the team.
        :type membership_policy: `TeamMembershipPolicy`
        :param visibility: The team's visibility. If it's None, the default
            (public) will be used.
        :type visibility: `PersonVisibility`
        :param members: People or teams to be added to the new team
        :type members: An iterable of objects implementing IPerson
        :return: The new team
        :rtype: `ITeam`
        """
        if owner is None:
            owner = self.makePerson()
        elif isinstance(owner, str):
            owner = getUtility(IPersonSet).getByName(owner)
        else:
            pass
        if name is None:
            name = self.getUniqueString("team-name")
        if displayname is None:
            displayname = SPACE.join(
                word.capitalize() for word in name.split("-")
            )
        team = getUtility(IPersonSet).newTeam(
            owner,
            name,
            displayname,
            description,
            membership_policy=membership_policy,
        )
        naked_team = removeSecurityProxy(team)
        if visibility is not None:
            # Visibility is normally restricted to launchpad.Commercial, so
            # removing the security proxy as we don't care here.
            naked_team.visibility = visibility
            naked_team._ensurePolicies()
        if email is not None:
            removeSecurityProxy(team).setContactAddress(
                getUtility(IEmailAddressSet).new(email, team)
            )
        if icon is not None:
            naked_team.icon = icon
        if logo is not None:
            naked_team.logo = logo
        if members is not None:
            for member in members:
                naked_team.addMember(member, owner)
        return team

    def makePoll(
        self, team, name, title, proposition, poll_type=PollAlgorithm.SIMPLE
    ):
        """Create a new poll which starts tomorrow and lasts for a week."""
        dateopens = datetime.now(timezone.utc) + timedelta(days=1)
        datecloses = dateopens + timedelta(days=7)
        return getUtility(IPollSet).new(
            team,
            name,
            title,
            proposition,
            dateopens,
            datecloses,
            PollSecrecy.SECRET,
            allowspoilt=True,
            poll_type=poll_type,
            check_permissions=False,
        )

    def makeTranslationGroup(
        self, owner=None, name=None, title=None, summary=None, url=None
    ):
        """Create a new, arbitrary `TranslationGroup`."""
        if owner is None:
            owner = self.makePerson()
        if name is None:
            name = self.getUniqueUnicode("translationgroup")
        if title is None:
            title = self.getUniqueUnicode("title")
        if summary is None:
            summary = self.getUniqueUnicode("summary")
        group = getUtility(ITranslationGroupSet).new(
            name, title, summary, url, owner
        )
        IStore(group).flush()
        return group

    def makeTranslator(
        self,
        language_code=None,
        group=None,
        person=None,
        license=True,
        language=None,
    ):
        """Create a new, arbitrary `Translator`."""
        assert (
            language_code is None or language is None
        ), "Please specify only one of language_code and language."
        if language_code is None:
            if language is None:
                language = self.makeLanguage()
            language_code = language.code
        else:
            language = getUtility(ILanguageSet).getLanguageByCode(
                language_code
            )
            if language is None:
                language = self.makeLanguage(language_code=language_code)

        if group is None:
            group = self.makeTranslationGroup()
        if person is None:
            person = self.makePerson()
        tx_person = ITranslationsPerson(person)
        insecure_tx_person = removeSecurityProxy(tx_person)
        insecure_tx_person.translations_relicensing_agreement = license
        return getUtility(ITranslatorSet).new(group, language, person)

    def makeMilestone(
        self,
        product=None,
        distribution=None,
        productseries=None,
        name=None,
        active=True,
        dateexpected=None,
        distroseries=None,
    ):
        if (
            product is None
            and distribution is None
            and productseries is None
            and distroseries is None
        ):
            product = self.makeProduct()
        if distribution is None and distroseries is None:
            if productseries is not None:
                product = productseries.product
            else:
                productseries = self.makeProductSeries(product=product)
        elif distroseries is None:
            distroseries = self.makeDistroSeries(distribution=distribution)
        else:
            distribution = distroseries.distribution
        if name is None:
            name = self.getUniqueString()
        return ProxyFactory(
            Milestone(
                product=product,
                distribution=distribution,
                productseries=productseries,
                distroseries=distroseries,
                name=name,
                active=active,
                dateexpected=dateexpected,
            )
        )

    def makeProcessor(
        self,
        name=None,
        title=None,
        description=None,
        restricted=False,
        build_by_default=True,
        supports_virtualized=False,
        supports_nonvirtualized=True,
    ):
        """Create a new processor.

        :param name: Name of the processor
        :param title: Optional title
        :param description: Optional description
        :param restricted: If the processor is restricted.
        :return: A `IProcessor`
        """
        if name is None:
            name = self.getUniqueString()
        if title is None:
            title = "The %s processor" % name
        if description is None:
            description = "The %s processor and compatible processors" % name
        return getUtility(IProcessorSet).new(
            name,
            title,
            description,
            restricted=restricted,
            build_by_default=build_by_default,
            supports_virtualized=supports_virtualized,
            supports_nonvirtualized=supports_nonvirtualized,
        )

    def makeProductRelease(
        self, milestone=None, product=None, productseries=None
    ):
        if milestone is None:
            milestone = self.makeMilestone(
                product=product, productseries=productseries
            )
        with person_logged_in(milestone.productseries.product.owner):
            release = milestone.createProductRelease(
                milestone.product.owner, datetime.now(timezone.utc)
            )
        return release

    def makeProductReleaseFile(
        self,
        signed=True,
        product=None,
        productseries=None,
        milestone=None,
        release=None,
        description="test file",
        filename="test.txt",
    ):
        signature_filename = None
        signature_content = None
        if signed:
            signature_filename = "%s.asc" % filename
            signature_content = b"123"
        if release is None:
            release = self.makeProductRelease(
                product=product,
                productseries=productseries,
                milestone=milestone,
            )
        with person_logged_in(release.milestone.product.owner):
            release_file = release.addReleaseFile(
                filename,
                b"test",
                "text/plain",
                uploader=release.milestone.product.owner,
                signature_filename=signature_filename,
                signature_content=signature_content,
                description=description,
            )
        IStore(release).flush()
        return release_file

    def makeProduct(
        self,
        name=None,
        projectgroup=None,
        displayname=None,
        licenses=None,
        owner=None,
        registrant=None,
        title=None,
        summary=None,
        official_malone=None,
        translations_usage=None,
        bug_supervisor=None,
        driver=None,
        icon=None,
        bug_sharing_policy=None,
        branch_sharing_policy=None,
        specification_sharing_policy=None,
        information_type=None,
        answers_usage=None,
        vcs=None,
    ):
        """Create and return a new, arbitrary Product."""
        if owner is None:
            owner = self.makePerson()
        if name is None:
            name = self.getUniqueString("product-name")
        if displayname is None:
            if name is None:
                displayname = self.getUniqueString("displayname")
            else:
                displayname = name.capitalize()
        if licenses is None:
            if (
                information_type in PROPRIETARY_INFORMATION_TYPES
                or (
                    bug_sharing_policy is not None
                    and bug_sharing_policy != BugSharingPolicy.PUBLIC
                )
                or (
                    branch_sharing_policy is not None
                    and branch_sharing_policy != BranchSharingPolicy.PUBLIC
                )
                or (
                    specification_sharing_policy is not None
                    and specification_sharing_policy
                    != SpecificationSharingPolicy.PUBLIC
                )
            ):
                licenses = [License.OTHER_PROPRIETARY]
            else:
                licenses = [License.GNU_GPL_V2]
        if title is None:
            title = self.getUniqueString("title")
        if summary is None:
            summary = self.getUniqueString("summary")
        admins = getUtility(ILaunchpadCelebrities).admin
        with person_logged_in(admins.teamowner):
            product = getUtility(IProductSet).createProduct(
                owner,
                name,
                displayname,
                title,
                summary,
                self.getUniqueString("description"),
                licenses=licenses,
                projectgroup=projectgroup,
                registrant=registrant,
                icon=icon,
                information_type=information_type,
                vcs=vcs,
            )
        naked_product = removeSecurityProxy(product)
        if official_malone is not None:
            naked_product.official_malone = official_malone
        if translations_usage is not None:
            naked_product.translations_usage = translations_usage
        if answers_usage is not None:
            naked_product.answers_usage = answers_usage
        if bug_supervisor is not None:
            naked_product.bug_supervisor = bug_supervisor
        if driver is not None:
            naked_product.driver = driver
        if branch_sharing_policy:
            naked_product.setBranchSharingPolicy(branch_sharing_policy)
        if bug_sharing_policy:
            naked_product.setBugSharingPolicy(bug_sharing_policy)
        if specification_sharing_policy:
            naked_product.setSpecificationSharingPolicy(
                specification_sharing_policy
            )
        return product

    def makeProductSeries(
        self,
        product=None,
        name=None,
        owner=None,
        summary=None,
        date_created=None,
        branch=None,
    ):
        """Create a new, arbitrary ProductSeries.

        :param branch: If supplied, the branch to set as
            ProductSeries.branch.
        :param date_created: If supplied, the date the series is created.
        :param name: If supplied, the name of the series.
        :param owner: If supplied, the owner of the series.
        :param product: If supplied, the series is created for this product.
            Otherwise, a new product is created.
        :param summary: If supplied, the product series summary.
        """
        if product is None:
            product = self.makeProduct()
        if owner is None:
            owner = removeSecurityProxy(product).owner
        if name is None:
            name = self.getUniqueString()
        if summary is None:
            summary = self.getUniqueString()
        # We don't want to login() as the person used to create the product,
        # so we remove the security proxy before creating the series.
        naked_product = removeSecurityProxy(product)
        series = naked_product.newSeries(
            owner=owner, name=name, summary=summary, branch=branch
        )
        if date_created is not None:
            series.datecreated = date_created
        return ProxyFactory(series)

    def makeProject(
        self,
        name=None,
        displayname=None,
        title=None,
        homepageurl=None,
        summary=None,
        owner=None,
        driver=None,
        description=None,
    ):
        """Create and return a new, arbitrary ProjectGroup."""
        if owner is None:
            owner = self.makePerson()
        if name is None:
            name = self.getUniqueString("project-name")
        if displayname is None:
            displayname = self.getUniqueString("displayname")
        if summary is None:
            summary = self.getUniqueString("summary")
        if description is None:
            description = self.getUniqueString("description")
        if title is None:
            title = self.getUniqueString("title")
        project = getUtility(IProjectGroupSet).new(
            name=name,
            display_name=displayname,
            title=title,
            homepageurl=homepageurl,
            summary=summary,
            description=description,
            owner=owner,
        )
        if driver is not None:
            removeSecurityProxy(project).driver = driver
        return project

    def makeSprint(self, title=None, name=None, time_starts=None):
        """Make a sprint."""
        if title is None:
            title = self.getUniqueUnicode("title")
        owner = self.makePerson()
        if name is None:
            name = self.getUniqueUnicode("name")
        if time_starts is None:
            time_starts = datetime(2009, 1, 1, tzinfo=timezone.utc)
        time_ends = time_starts + timedelta(days=1)
        time_zone = "UTC"
        summary = self.getUniqueUnicode("summary")
        return getUtility(ISprintSet).new(
            owner=owner,
            name=name,
            title=title,
            time_zone=time_zone,
            time_starts=time_starts,
            time_ends=time_ends,
            summary=summary,
        )

    def makeStackedOnBranchChain(self, depth=5, **kwargs):
        branch = None
        for _ in range(depth):
            branch = self.makeAnyBranch(stacked_on=branch, **kwargs)
        return branch

    def makeBranch(
        self,
        branch_type=None,
        owner=None,
        name=None,
        product=_DEFAULT,
        url=_DEFAULT,
        registrant=None,
        information_type=None,
        stacked_on=None,
        sourcepackage=None,
        reviewer=None,
        target=None,
        **optional_branch_args,
    ):
        """Create and return a new, arbitrary Branch of the given type.

        Any parameters for `IBranchNamespace.createBranch` can be specified to
        override the default ones.
        """
        if branch_type is None:
            branch_type = BranchType.HOSTED
        if owner is None:
            owner = self.makePerson()
        if name is None:
            name = self.getUniqueString("branch")
        if target is not None:
            assert product is _DEFAULT
            assert sourcepackage is None
            if IProduct.providedBy(target):
                product = target
            elif ISourcePackage.providedBy(target):
                sourcepackage = target
            else:
                raise AssertionError("Unknown target: %r" % target)

        if sourcepackage is None:
            if product is _DEFAULT:
                product = self.makeProduct()
            sourcepackagename = None
            distroseries = None
        else:
            assert (
                product is _DEFAULT
            ), "Passed source package AND product details"
            product = None
            sourcepackagename = sourcepackage.sourcepackagename
            distroseries = sourcepackage.distroseries

        if registrant is None:
            if owner.is_team:
                registrant = removeSecurityProxy(owner).teamowner
            else:
                registrant = owner

        if branch_type in (BranchType.HOSTED, BranchType.IMPORTED):
            url = None
        elif branch_type in (BranchType.MIRRORED, BranchType.REMOTE):
            if url is _DEFAULT:
                url = self.getUniqueURL()
        else:
            raise UnknownBranchTypeError(
                "Unrecognized branch type: %r" % (branch_type,)
            )

        namespace = get_branch_namespace(
            owner,
            product=product,
            distroseries=distroseries,
            sourcepackagename=sourcepackagename,
        )
        branch = namespace.createBranch(
            branch_type=branch_type,
            name=name,
            registrant=registrant,
            url=url,
            **optional_branch_args,
        )
        naked_branch = removeSecurityProxy(branch)
        if information_type is not None:
            naked_branch.transitionToInformationType(
                information_type, registrant, verify_policy=False
            )
        if stacked_on is not None:
            naked_branch.branchChanged(
                removeSecurityProxy(stacked_on).unique_name,
                "rev1",
                None,
                None,
                None,
            )
        if reviewer is not None:
            naked_branch.reviewer = reviewer
        return branch

    def makePackagingLink(
        self,
        productseries=None,
        sourcepackagename=None,
        distroseries=None,
        packaging_type=None,
        owner=None,
        sourcepackage=None,
        in_ubuntu=False,
    ) -> Packaging:
        assert sourcepackage is None or (
            distroseries is None and sourcepackagename is None
        ), (
            "Specify either a sourcepackage or a "
            "distroseries/sourcepackagename pair"
        )
        if productseries is None:
            productseries = self.makeProduct().development_focus
        if sourcepackage is not None:
            distroseries = sourcepackage.distroseries
            sourcepackagename = sourcepackage.sourcepackagename
        else:
            make_sourcepackagename = sourcepackagename is None or isinstance(
                sourcepackagename, str
            )
            if make_sourcepackagename:
                sourcepackagename = self.makeSourcePackageName(
                    sourcepackagename
                )
            if distroseries is None:
                if in_ubuntu:
                    distroseries = self.makeUbuntuDistroSeries()
                else:
                    distroseries = self.makeDistroSeries()
        if packaging_type is None:
            packaging_type = PackagingType.PRIME
        if owner is None:
            owner = self.makePerson()
        return getUtility(IPackagingUtil).createPackaging(
            productseries=productseries,
            sourcepackagename=sourcepackagename,
            distroseries=distroseries,
            packaging=packaging_type,
            owner=owner,
        )

    def makePackageBranch(
        self,
        sourcepackage=None,
        distroseries=None,
        sourcepackagename=None,
        owner=None,
        **kwargs,
    ):
        """Make a package branch on an arbitrary package.

        See `makeBranch` for more information on arguments.

        You can pass in either `sourcepackage` or one or both of
        `distroseries` and `sourcepackagename`, but not combinations or all of
        them.
        """
        assert not (
            sourcepackage is not None and distroseries is not None
        ), "Don't pass in both sourcepackage and distroseries"
        assert not (
            sourcepackage is not None and sourcepackagename is not None
        ), "Don't pass in both sourcepackage and sourcepackagename"
        if sourcepackage is None:
            sourcepackage = self.makeSourcePackage(
                sourcepackagename=sourcepackagename,
                distroseries=distroseries,
                owner=owner,
            )
        return self.makeBranch(
            sourcepackage=sourcepackage, owner=owner, **kwargs
        )

    def makePersonalBranch(self, owner=None, **kwargs):
        """Make a personal branch on an arbitrary person.

        See `makeBranch` for more information on arguments.
        """
        if owner is None:
            owner = self.makePerson()
        return self.makeBranch(
            owner=owner, product=None, sourcepackage=None, **kwargs
        )

    def makeProductBranch(self, product=None, **kwargs):
        """Make a product branch on an arbitrary product.

        See `makeBranch` for more information on arguments.
        """
        if product is None:
            product = self.makeProduct()
        return self.makeBranch(product=product, **kwargs)

    def makeAnyBranch(self, **kwargs):
        """Make a branch without caring about its container.

        See `makeBranch` for more information on arguments.
        """
        return self.makeProductBranch(**kwargs)

    def makeBranchTargetBranch(
        self,
        target,
        branch_type=BranchType.HOSTED,
        name=None,
        owner=None,
        creator=None,
    ):
        """Create a branch in a BranchTarget."""
        if name is None:
            name = self.getUniqueString("branch")
        if owner is None:
            owner = self.makePerson()
        if creator is None:
            creator = owner
        namespace = target.getNamespace(owner)
        return ProxyFactory(namespace.createBranch(branch_type, name, creator))

    def makeRelatedBranchesForSourcePackage(
        self, sourcepackage=None, **kwargs
    ):
        """Create some branches associated with a sourcepackage."""

        reference_branch = self.makePackageBranch(sourcepackage=sourcepackage)
        return self.makeRelatedBranches(
            reference_branch=reference_branch, **kwargs
        )

    def makeRelatedBranchesForProduct(self, product=None, **kwargs):
        """Create some branches associated with a product."""

        reference_branch = self.makeProductBranch(product=product)
        return self.makeRelatedBranches(
            reference_branch=reference_branch, **kwargs
        )

    def makeRelatedBranches(
        self,
        reference_branch=None,
        with_series_branches=True,
        with_package_branches=True,
        with_private_branches=False,
    ):
        """Create some branches associated with a reference branch.
        The other branches are:
          - series branches: a set of branches associated with product
            series of the same product as the reference branch.
          - package branches: a set of branches associated with packagesource
            entities of the same product as the reference branch or the same
            sourcepackage depending on what type of branch it is.

        If no reference branch is supplied, create one.

        Returns: a tuple consisting of
        (reference_branch, related_series_branches, related_package_branches)

        """
        related_series_branch_info = []
        related_package_branch_info = []
        # Make the base_branch if required and find the product if one exists.
        naked_product = None
        if reference_branch is None:
            naked_product = removeSecurityProxy(self.makeProduct())
            # Create the 'source' branch ie the base branch of a recipe.
            reference_branch = self.makeProductBranch(
                name="reference_branch", product=naked_product
            )
        elif reference_branch.product is not None:
            naked_product = removeSecurityProxy(reference_branch.product)

        related_branch_owner = self.makePerson()
        # Only branches related to products have related series branches.
        if with_series_branches and naked_product is not None:
            series_branch_info = []

            # Add some product series
            def makeSeriesBranch(name, information_type):
                branch = self.makeBranch(
                    name=name,
                    product=naked_product,
                    owner=related_branch_owner,
                    information_type=information_type,
                )
                series = self.makeProductSeries(
                    product=naked_product, branch=branch
                )
                return branch, series

            for x in range(4):
                information_type = InformationType.PUBLIC
                if x == 0 and with_private_branches:
                    information_type = InformationType.USERDATA
                (branch, series) = makeSeriesBranch(
                    ("series_branch_%s" % x), information_type
                )
                if information_type == InformationType.PUBLIC:
                    series_branch_info.append((branch, series))

            # Sort them
            related_series_branch_info = sorted_version_numbers(
                series_branch_info, key=lambda branch_info: branch_info[1].name
            )

            # Add a development branch at the start of the list.
            naked_product.development_focus.name = "trunk"
            devel_branch = self.makeProductBranch(
                product=naked_product,
                name="trunk_branch",
                owner=related_branch_owner,
            )
            linked_branch = ICanHasLinkedBranch(naked_product)
            linked_branch.setBranch(devel_branch)
            related_series_branch_info.insert(
                0,
                (devel_branch, ProxyFactory(naked_product.development_focus)),
            )

        if with_package_branches:
            # Create related package branches if the base_branch is
            # associated with a product.
            if naked_product is not None:

                def makePackageBranch(name, information_type):
                    distro = self.makeDistribution()
                    distroseries = self.makeDistroSeries(distribution=distro)
                    sourcepackagename = self.makeSourcePackageName()

                    suitesourcepackage = self.makeSuiteSourcePackage(
                        sourcepackagename=sourcepackagename,
                        distroseries=distroseries,
                        pocket=PackagePublishingPocket.RELEASE,
                    )
                    naked_sourcepackage = removeSecurityProxy(
                        suitesourcepackage
                    )

                    branch = self.makePackageBranch(
                        name=name,
                        owner=related_branch_owner,
                        sourcepackagename=sourcepackagename,
                        distroseries=distroseries,
                        information_type=information_type,
                    )
                    linked_branch = ICanHasLinkedBranch(naked_sourcepackage)
                    with celebrity_logged_in("admin"):
                        linked_branch.setBranch(branch, related_branch_owner)

                    series = self.makeProductSeries(product=naked_product)
                    self.makePackagingLink(
                        distroseries=distroseries,
                        productseries=series,
                        sourcepackagename=sourcepackagename,
                    )
                    return branch, distroseries

                for x in range(5):
                    information_type = InformationType.PUBLIC
                    if x == 0 and with_private_branches:
                        information_type = InformationType.USERDATA
                    branch, distroseries = makePackageBranch(
                        ("product_package_branch_%s" % x), information_type
                    )
                    if information_type == InformationType.PUBLIC:
                        related_package_branch_info.append(
                            (branch, distroseries)
                        )

            # Create related package branches if the base_branch is
            # associated with a sourcepackage.
            if reference_branch.sourcepackage is not None:
                distroseries = reference_branch.sourcepackage.distroseries
                for pocket in [
                    PackagePublishingPocket.RELEASE,
                    PackagePublishingPocket.UPDATES,
                ]:
                    branch = self.makePackageBranch(
                        name="package_branch_%s" % pocket.name,
                        distroseries=distroseries,
                    )
                    with celebrity_logged_in("admin"):
                        reference_branch.sourcepackage.setBranch(
                            pocket, branch, related_branch_owner
                        )

                    related_package_branch_info.append((branch, distroseries))

            related_package_branch_info = sorted_version_numbers(
                related_package_branch_info,
                key=lambda branch_info: branch_info[1].name,
            )

        return (
            reference_branch,
            related_series_branch_info,
            related_package_branch_info,
        )

    def enableDefaultStackingForProduct(self, product, branch=None):
        """Give 'product' a default stacked-on branch.

        :param product: The product to give a default stacked-on branch to.
        :param branch: The branch that should be the default stacked-on
            branch.  If not supplied, a fresh branch will be created.
        """
        if branch is None:
            branch = self.makeBranch(product=product)
        # We just remove the security proxies to be able to change the objects
        # here.
        removeSecurityProxy(branch).branchChanged("", "rev1", None, None, None)
        naked_series = removeSecurityProxy(product.development_focus)
        naked_series.branch = branch
        return branch

    def enableDefaultStackingForPackage(self, package, branch):
        """Give 'package' a default stacked-on branch.

        :param package: The package to give a default stacked-on branch to.
        :param branch: The branch that should be the default stacked-on
            branch.
        """
        # We just remove the security proxies to be able to change the branch
        # here.
        removeSecurityProxy(branch).branchChanged("", "rev1", None, None, None)
        with person_logged_in(package.distribution.owner):
            package.development_version.setBranch(
                PackagePublishingPocket.RELEASE,
                branch,
                package.distribution.owner,
            )
        return branch

    def makeBranchMergeProposal(
        self,
        target_branch=None,
        registrant=None,
        set_state=None,
        prerequisite_branch=None,
        product=None,
        initial_comment=None,
        source_branch=None,
        date_created=None,
        commit_message=None,
        description=None,
        reviewer=None,
        merged_revno=None,
    ):
        """Create a proposal to merge based on anonymous branches."""
        if target_branch is not None:
            target_branch = removeSecurityProxy(target_branch)
            target = target_branch.target
        elif source_branch is not None:
            target = source_branch.target
        elif prerequisite_branch is not None:
            target = prerequisite_branch.target
        else:
            # Create a target product branch, and use that target.  This is
            # needed to make sure we get a branch target that has the needed
            # security proxy.
            target_branch = self.makeProductBranch(product)
            target = target_branch.target

        # Fall back to initial_comment for description and commit_message.
        if description is None:
            description = initial_comment
        if commit_message is None:
            commit_message = initial_comment

        if target_branch is None:
            target_branch = self.makeBranchTargetBranch(target)
        if source_branch is None:
            source_branch = self.makeBranchTargetBranch(target)
        if registrant is None:
            registrant = self.makePerson()
        review_requests = []
        if reviewer is not None:
            review_requests.append((reviewer, None))
        proposal = source_branch.addLandingTarget(
            registrant,
            target_branch,
            review_requests=review_requests,
            merge_prerequisite=prerequisite_branch,
            description=description,
            commit_message=commit_message,
            date_created=date_created,
        )

        unsafe_proposal = removeSecurityProxy(proposal)
        unsafe_proposal.merged_revno = merged_revno
        if (
            set_state is None
            or set_state == BranchMergeProposalStatus.WORK_IN_PROGRESS
        ):
            # The initial state is work in progress, so do nothing.
            pass
        elif set_state == BranchMergeProposalStatus.NEEDS_REVIEW:
            unsafe_proposal.requestReview()
        elif set_state == BranchMergeProposalStatus.CODE_APPROVED:
            unsafe_proposal.approveBranch(
                proposal.merge_target.owner, "some_revision"
            )
        elif set_state == BranchMergeProposalStatus.REJECTED:
            unsafe_proposal.rejectBranch(
                proposal.merge_target.owner, "some_revision"
            )
        elif set_state == BranchMergeProposalStatus.MERGED:
            unsafe_proposal.markAsMerged()
        elif set_state == BranchMergeProposalStatus.SUPERSEDED:
            unsafe_proposal.resubmit(proposal.registrant)
        else:
            raise AssertionError("Unknown status: %s" % set_state)

        return ProxyFactory(proposal)

    def makeBranchMergeProposalForGit(
        self,
        target_ref=None,
        registrant=None,
        set_state=None,
        prerequisite_ref=None,
        target=_DEFAULT,
        initial_comment=None,
        source_ref=None,
        date_created=None,
        commit_message=None,
        description=None,
        reviewer=None,
        merged_revision_id=None,
    ):
        """Create a proposal to merge based on anonymous branches."""
        if target is not _DEFAULT:
            pass
        elif target_ref is not None:
            target = target_ref.target
        elif source_ref is not None:
            target = source_ref.target
        elif prerequisite_ref is not None:
            target = prerequisite_ref.target
        else:
            # Create a reference for a repository on the target, and use
            # that target.
            [target_ref] = self.makeGitRefs(target=target)
            target = target_ref.target

        # Fall back to initial_comment for description and commit_message.
        if description is None:
            description = initial_comment
        if commit_message is None:
            commit_message = initial_comment

        if target_ref is None:
            [target_ref] = self.makeGitRefs(target=target)
        if source_ref is None:
            [source_ref] = self.makeGitRefs(target=target)
        if registrant is None:
            registrant = self.makePerson()
        review_requests = []
        if reviewer is not None:
            review_requests.append((reviewer, None))
        proposal = source_ref.addLandingTarget(
            registrant,
            target_ref,
            review_requests=review_requests,
            merge_prerequisite=prerequisite_ref,
            description=description,
            commit_message=commit_message,
            date_created=date_created,
        )

        unsafe_proposal = removeSecurityProxy(proposal)
        unsafe_proposal.merged_revision_id = merged_revision_id
        if (
            set_state is None
            or set_state == BranchMergeProposalStatus.WORK_IN_PROGRESS
        ):
            # The initial state is work in progress, so do nothing.
            pass
        elif set_state == BranchMergeProposalStatus.NEEDS_REVIEW:
            unsafe_proposal.requestReview()
        elif set_state == BranchMergeProposalStatus.CODE_APPROVED:
            unsafe_proposal.approveBranch(
                proposal.merge_target.owner, "some_revision"
            )
        elif set_state == BranchMergeProposalStatus.REJECTED:
            unsafe_proposal.rejectBranch(
                proposal.merge_target.owner, "some_revision"
            )
        elif set_state == BranchMergeProposalStatus.MERGED:
            unsafe_proposal.markAsMerged()
        elif set_state == BranchMergeProposalStatus.SUPERSEDED:
            unsafe_proposal.resubmit(proposal.registrant)
        else:
            raise AssertionError("Unknown status: %s" % set_state)

        return ProxyFactory(proposal)

    def makeBranchSubscription(
        self, branch=None, person=None, subscribed_by=None
    ):
        """Create a BranchSubscription."""
        if branch is None:
            branch = self.makeBranch()
        if person is None:
            person = self.makePerson()
        if subscribed_by is None:
            subscribed_by = person
        return branch.subscribe(
            removeSecurityProxy(person),
            BranchSubscriptionNotificationLevel.NOEMAIL,
            None,
            CodeReviewNotificationLevel.NOEMAIL,
            subscribed_by,
        )

    def makeDiff(self, size="small"):
        diff_path = os.path.join(
            os.path.dirname(__file__), f"data/{size}.diff"
        )
        with open(os.path.join(diff_path), "rb") as diff:
            diff_text = diff.read()
            return ProxyFactory(
                Diff.fromFile(BytesIO(diff_text), len(diff_text))
            )

    def makePreviewDiff(
        self,
        conflicts="",
        merge_proposal=None,
        date_created=None,
        size="small",
        git=False,
    ):
        diff = self.makeDiff(size)
        if merge_proposal is None:
            if git:
                merge_proposal = self.makeBranchMergeProposalForGit()
            else:
                merge_proposal = self.makeBranchMergeProposal()
        preview_diff = PreviewDiff()
        preview_diff.branch_merge_proposal = merge_proposal
        preview_diff.conflicts = conflicts
        preview_diff.diff = diff
        preview_diff.source_revision_id = self.getUniqueUnicode()
        preview_diff.target_revision_id = self.getUniqueUnicode()
        if date_created:
            preview_diff.date_created = date_created
        return ProxyFactory(preview_diff)

    def makeIncrementalDiff(
        self, merge_proposal=None, old_revision=None, new_revision=None
    ):
        diff = self.makeDiff()
        if merge_proposal is None:
            source_branch = self.makeBranch()
        else:
            source_branch = merge_proposal.source_branch

        def make_revision(parent=None):
            sequence = source_branch.revision_history.count() + 1
            if parent is None:
                parent_ids = []
            else:
                parent_ids = [parent.revision_id]
            branch_revision = self.makeBranchRevision(
                source_branch,
                sequence=sequence,
                revision_date=self.getUniqueDate(),
                parent_ids=parent_ids,
            )
            return branch_revision.revision

        if old_revision is None:
            old_revision = make_revision()
        if merge_proposal is None:
            merge_proposal = self.makeBranchMergeProposal(
                date_created=self.getUniqueDate(), source_branch=source_branch
            )
        if new_revision is None:
            new_revision = make_revision(old_revision)
        return merge_proposal.generateIncrementalDiff(
            old_revision, new_revision, diff
        )

    def makeBzrRevision(self, revision_id=None, parent_ids=None, props=None):
        if revision_id is None:
            revision_id = self.getUniqueString("revision-id")
        if parent_ids is None:
            parent_ids = []
        return BzrRevision(
            message=self.getUniqueString("message"),
            revision_id=revision_id,
            committer=self.getUniqueString("committer"),
            parent_ids=parent_ids,
            timestamp=0,
            timezone=0,
            properties=props,
        )

    def makeRevision(
        self,
        author=None,
        revision_date=None,
        parent_ids=None,
        rev_id=None,
        log_body=None,
        date_created=None,
    ):
        """Create a single `Revision`."""
        if author is None:
            author = self.getUniqueString("author")
        elif IPerson.providedBy(author):
            author = removeSecurityProxy(author).preferredemail.email
        if revision_date is None:
            revision_date = datetime.now(timezone.utc)
        if parent_ids is None:
            parent_ids = []
        if rev_id is None:
            rev_id = self.getUniqueUnicode("revision-id")
        elif isinstance(rev_id, bytes):
            rev_id = rev_id.decode()
        else:
            rev_id = rev_id
        if log_body is None:
            log_body = self.getUniqueString("log-body")
        return getUtility(IRevisionSet).new(
            revision_id=rev_id,
            log_body=log_body,
            revision_date=revision_date,
            revision_author=author,
            parent_ids=parent_ids,
            properties={},
            _date_created=date_created,
        )

    def makeRevisionsForBranch(
        self, branch, count=5, author=None, date_generator=None
    ):
        """Add `count` revisions to the revision history of `branch`.

        :param branch: The branch to add the revisions to.
        :param count: The number of revisions to add.
        :param author: A string for the author name.
        :param date_generator: A `time_counter` instance, defaults to starting
                               from 1-Jan-2007 if not set.
        """
        if date_generator is None:
            date_generator = time_counter(
                datetime(2007, 1, 1, tzinfo=timezone.utc),
                delta=timedelta(days=1),
            )
        sequence = branch.revision_count
        parent = branch.getTipRevision()
        if parent is None:
            parent_ids = []
        else:
            parent_ids = [parent.revision_id]

        revision_set = getUtility(IRevisionSet)
        if author is None:
            author = self.getUniqueString("author")
        for _ in range(count):
            revision = revision_set.new(
                revision_id=self.getUniqueString("revision-id"),
                log_body=self.getUniqueString("log-body"),
                revision_date=next(date_generator),
                revision_author=author,
                parent_ids=parent_ids,
                properties={},
            )
            sequence += 1
            branch.createBranchRevision(sequence, revision)
            parent = revision
            parent_ids = [parent.revision_id]
        if branch.branch_type not in (BranchType.REMOTE, BranchType.HOSTED):
            branch.startMirroring()
        removeSecurityProxy(branch).branchChanged(
            "", parent.revision_id, None, None, None
        )
        branch.updateScannedDetails(parent, sequence)

    def makeBranchRevision(
        self,
        branch=None,
        revision_id=None,
        sequence=None,
        parent_ids=None,
        revision_date=None,
    ):
        if branch is None:
            branch = self.makeBranch()
        else:
            branch = removeSecurityProxy(branch)
        revision = self.makeRevision(
            rev_id=revision_id,
            parent_ids=parent_ids,
            revision_date=revision_date,
        )
        return ProxyFactory(branch.createBranchRevision(sequence, revision))

    def makeGitRepository(
        self,
        repository_type=None,
        owner=None,
        reviewer=None,
        target=_DEFAULT,
        registrant=None,
        name=None,
        information_type=None,
        **optional_repository_args,
    ):
        """Create and return a new, arbitrary GitRepository.

        Any parameters for `IGitNamespace.createRepository` can be specified
        to override the default ones.
        """
        if repository_type is None:
            repository_type = GitRepositoryType.HOSTED
        if owner is None:
            owner = self.makePerson()
        if name is None:
            name = self.getUniqueUnicode("gitrepository")

        if target is _DEFAULT:
            target = self.makeProduct()

        if registrant is None:
            if owner.is_team:
                registrant = removeSecurityProxy(owner).teamowner
            else:
                registrant = owner

        namespace = get_git_namespace(target, owner)
        repository = namespace.createRepository(
            repository_type=repository_type,
            registrant=registrant,
            name=name,
            reviewer=reviewer,
            **optional_repository_args,
        )
        naked_repository = removeSecurityProxy(repository)
        if information_type is not None:
            naked_repository.transitionToInformationType(
                information_type, registrant, verify_policy=False
            )
        return repository

    def makeGitSubscription(
        self, repository=None, person=None, subscribed_by=None
    ):
        """Create a GitSubscription."""
        if repository is None:
            repository = self.makeGitRepository()
        if person is None:
            person = self.makePerson()
        if subscribed_by is None:
            subscribed_by = person
        return repository.subscribe(
            removeSecurityProxy(person),
            BranchSubscriptionNotificationLevel.NOEMAIL,
            None,
            CodeReviewNotificationLevel.NOEMAIL,
            subscribed_by,
        )

    def makeGitRefs(self, repository=None, paths=None, **repository_kwargs):
        """Create and return a list of new, arbitrary GitRefs."""
        if repository is None:
            repository = self.makeGitRepository(**repository_kwargs)
        if paths is None:
            paths = [self.getUniqueUnicode("refs/heads/path")]
        refs_info = {
            path: {
                "sha1": hashlib.sha1(path.encode()).hexdigest(),
                "type": GitObjectType.COMMIT,
            }
            for path in paths
        }
        with GitHostingFixture():
            refs_by_path = {
                ref.path: ProxyFactory(ref)
                for ref in removeSecurityProxy(repository).createOrUpdateRefs(
                    refs_info, get_objects=True
                )
            }
        return [refs_by_path[path] for path in paths]

    def makeGitRefRemote(self, repository_url=None, path=None):
        """Create an object representing a ref in a remote repository."""
        if repository_url is None:
            repository_url = self.getUniqueURL()
        if path is None:
            path = self.getUniqueUnicode("refs/heads/path")
        return getUtility(IGitRefRemoteSet).new(repository_url, path)

    def makeGitRule(
        self,
        repository=None,
        ref_pattern="refs/heads/*",
        creator=None,
        position=None,
        **repository_kwargs,
    ):
        """Create a Git repository access rule."""
        if repository is None:
            repository = self.makeGitRepository(**repository_kwargs)
        if creator is None:
            creator = repository.owner
        with person_logged_in(creator):
            return ProxyFactory(
                repository.addRule(ref_pattern, creator, position=position)
            )

    def makeGitRuleGrant(
        self,
        rule=None,
        grantee=None,
        grantor=None,
        can_create=False,
        can_push=False,
        can_force_push=False,
        **rule_kwargs,
    ):
        """Create a Git repository access grant."""
        if rule is None:
            rule = self.makeGitRule(**rule_kwargs)
        if grantee is None:
            grantee = self.makePerson()
        if grantor is None:
            grantor = removeSecurityProxy(rule).repository.owner
        with person_logged_in(grantor):
            return ProxyFactory(
                rule.addGrant(
                    grantee,
                    grantor,
                    can_create=can_create,
                    can_push=can_push,
                    can_force_push=can_force_push,
                )
            )

    def makeRevisionStatusReport(
        self,
        user=None,
        title=None,
        git_repository=None,
        commit_sha1=None,
        result_summary=None,
        url=None,
        result=None,
        ci_build=None,
        properties=None,
        distro_arch_series=None,
    ):
        """Create a new RevisionStatusReport."""
        if title is None:
            title = self.getUniqueUnicode()
        if git_repository is None:
            if ci_build is not None:
                git_repository = ci_build.git_repository
            else:
                git_repository = self.makeGitRepository()
        if user is None:
            user = git_repository.owner
        if commit_sha1 is None:
            if ci_build is not None:
                commit_sha1 = ci_build.commit_sha1
            else:
                commit_sha1 = hashlib.sha1(self.getUniqueBytes()).hexdigest()
        if result_summary is None:
            result_summary = self.getUniqueUnicode()
        return getUtility(IRevisionStatusReportSet).new(
            user,
            title,
            git_repository,
            commit_sha1,
            url,
            result_summary,
            result,
            ci_build=ci_build,
            properties=properties,
            distro_arch_series=distro_arch_series,
        )

    def makeRevisionStatusArtifact(
        self,
        lfa=None,
        content=None,
        report=None,
        artifact_type=None,
        restricted=False,
        date_created=DEFAULT,
    ):
        """Create a new RevisionStatusArtifact."""
        if lfa is None:
            lfa = self.makeLibraryFileAlias(
                content=content, restricted=restricted
            )
        if report is None:
            report = self.makeRevisionStatusReport()
        if artifact_type is None:
            artifact_type = RevisionStatusArtifactType.LOG
        return getUtility(IRevisionStatusArtifactSet).new(
            lfa, report, artifact_type, date_created=date_created
        )

    def makeBug(
        self,
        target=None,
        owner=None,
        bug_watch_url=None,
        information_type=None,
        date_closed=None,
        title=None,
        date_created=None,
        description=None,
        comment=None,
        status=None,
        milestone=None,
        series=None,
        tags=None,
    ):
        """Create and return a new, arbitrary Bug.

        The bug returned uses default values where possible. See
        `IBugSet.new` for more information.

        :param target: The initial bug target. If not specified, falls
            back to the milestone target, then the series target, then a
            new product.
        :param owner: The reporter of the bug. If not set, one is created.
        :param bug_watch_url: If specified, create a bug watch pointing
            to this URL.
        :param milestone: If set, the milestone.target must match the
            target parameter's pillar.
        :param series: If set, the series's pillar must match the target
            parameter's.
        :param tags: If set, the tags to be added with the bug.
        """
        if target is None:
            if milestone is not None:
                target = milestone.target
            elif series is not None:
                target = series.pillar
            else:
                target = self.makeProduct()
                if information_type == InformationType.PROPRIETARY:
                    self.makeAccessPolicy(pillar=target)
        if IDistributionSourcePackage.providedBy(target):
            self.makeSourcePackagePublishingHistory(
                distroseries=target.distribution.currentseries,
                sourcepackagename=target.sourcepackagename,
            )
        if owner is None:
            owner = self.makePerson()
        if title is None:
            title = self.getUniqueString("bug-title")
        if comment is None:
            comment = self.getUniqueString()
        create_bug_params = CreateBugParams(
            owner,
            title,
            comment=comment,
            information_type=information_type,
            datecreated=date_created,
            description=description,
            status=status,
            tags=tags,
            target=target,
        )
        bug = getUtility(IBugSet).createBug(create_bug_params)
        if bug_watch_url is not None:
            # fromText() creates a bug watch associated with the bug.
            with person_logged_in(owner):
                getUtility(IBugWatchSet).fromText(bug_watch_url, bug, owner)
        bugtask = removeSecurityProxy(bug).default_bugtask
        if date_closed is not None:
            with person_logged_in(owner):
                bugtask.transitionToStatus(
                    BugTaskStatus.FIXRELEASED, owner, when=date_closed
                )
        if milestone is not None:
            with person_logged_in(owner):
                bugtask.transitionToMilestone(
                    milestone, milestone.target.owner
                )
        if series is not None:
            with person_logged_in(owner):
                task = bug.addTask(owner, series)
                task.transitionToStatus(status, owner)
        removeSecurityProxy(bug).clearBugNotificationRecipientsCache()
        return bug

    def makeBugTask(
        self, bug=None, target=None, owner=None, publish=True, status=None
    ):
        """Create and return a bug task.

        If the bug is already targeted to the given target, the existing
        bug task is returned.

        Private (and soon all) bugs cannot affect multiple projects
        so we ensure that if a bug has not been specified and one is
        created, it is for the same pillar as that of the specified target.

        :param bug: The `IBug` the bug tasks should be part of. If None,
            one will be created.
        :param target: The `IBugTarget`, to which the bug will be
            targeted to.
        """

        # Find and return the existing target if one exists.
        if bug is not None and target is not None:
            existing_bugtask = removeSecurityProxy(bug).getBugTask(target)
            if existing_bugtask is not None:
                return ProxyFactory(existing_bugtask)

        # If we are adding a task to an existing bug, and no target is
        # is specified, we use the same pillar as already exists to ensure
        # that we don't end up with a bug affecting multiple projects.
        if target is None:
            default_bugtask = bug and removeSecurityProxy(bug.default_bugtask)
            if default_bugtask is not None:
                existing_pillar = default_bugtask.pillar
                if IProduct.providedBy(existing_pillar):
                    target = self.makeProductSeries(product=existing_pillar)
                elif IDistribution.providedBy(existing_pillar):
                    target = self.makeDistroSeries(
                        distribution=existing_pillar
                    )
            if target is None:
                target = self.makeProduct()

        prerequisite_target = None
        if IProductSeries.providedBy(target):
            # We can't have a series task without a product task.
            prerequisite_target = target.product
        if IDistroSeries.providedBy(target):
            # We can't have a series task without a distribution task.
            prerequisite_target = target.distribution
        if ISourcePackage.providedBy(target):
            # We can't have a series task without a distribution task.
            prerequisite_target = target.distribution_sourcepackage
            if publish:
                self.makeSourcePackagePublishingHistory(
                    distroseries=target.distroseries,
                    sourcepackagename=target.sourcepackagename,
                )
        if IDistributionSourcePackage.providedBy(target):
            if publish:
                self.makeSourcePackagePublishingHistory(
                    distroseries=target.distribution.currentseries,
                    sourcepackagename=target.sourcepackagename,
                )
        if prerequisite_target is not None:
            prerequisite = bug and removeSecurityProxy(bug).getBugTask(
                prerequisite_target
            )
            if prerequisite is None:
                prerequisite = self.makeBugTask(
                    bug, prerequisite_target, publish=publish
                )
                bug = prerequisite.bug

        if bug is None:
            bug = self.makeBug()

        if owner is None:
            owner = self.makePerson()
        task = getUtility(IBugTaskSet).createTask(
            removeSecurityProxy(bug), owner, target, status=status
        )
        removeSecurityProxy(bug).clearBugNotificationRecipientsCache()
        return task

    def makeBugNomination(self, bug=None, target=None):
        """Create and return a BugNomination.

        Will create a non-series task if it does not already exist.

        :param bug: The `IBug` the nomination should be for. If None,
            one will be created.
        :param target: The `IProductSeries`, `IDistroSeries` or
            `ISourcePackage` to nominate for.
        """
        if ISourcePackage.providedBy(target):
            non_series = target.distribution_sourcepackage
            series = target.distroseries
        else:
            non_series = target.parent
            series = target
        with celebrity_logged_in("admin"):
            bug = self.makeBugTask(bug=bug, target=non_series).bug
            nomination = bug.addNomination(
                getUtility(ILaunchpadCelebrities).admin, series
            )
        return nomination

    def makeBugTracker(
        self, base_url=None, bugtrackertype=None, title=None, name=None
    ):
        """Make a new bug tracker."""
        owner = self.makePerson()

        if base_url is None:
            base_url = "http://%s.example.com/" % self.getUniqueString()
        if bugtrackertype is None:
            bugtrackertype = BugTrackerType.BUGZILLA

        return getUtility(IBugTrackerSet).ensureBugTracker(
            base_url, owner, bugtrackertype, title=title, name=name
        )

    def makeBugTrackerWithWatches(self, base_url=None, count=2):
        """Make a new bug tracker with some watches."""
        bug_tracker = self.makeBugTracker(base_url=base_url)
        bug_watches = [
            self.makeBugWatch(bugtracker=bug_tracker) for i in range(count)
        ]
        return (bug_tracker, bug_watches)

    def makeBugTrackerComponentGroup(self, name=None, bug_tracker=None):
        """Make a new bug tracker component group."""
        if name is None:
            name = self.getUniqueUnicode()
        if bug_tracker is None:
            bug_tracker = self.makeBugTracker()

        component_group = bug_tracker.addRemoteComponentGroup(name)
        return component_group

    def makeBugTrackerComponent(
        self, name=None, component_group=None, custom=None
    ):
        """Make a new bug tracker component."""
        if name is None:
            name = self.getUniqueUnicode()
        if component_group is None:
            component_group = self.makeBugTrackerComponentGroup()
        if custom is None:
            custom = False
        if custom:
            component = component_group.addCustomComponent(name)
        else:
            component = component_group.addComponent(name)
        return component

    def makeBugWatch(
        self,
        remote_bug=None,
        bugtracker=None,
        bug=None,
        owner=None,
        bug_task=None,
    ):
        """Make a new bug watch."""
        if remote_bug is None:
            remote_bug = self.getUniqueInteger()

        if bugtracker is None:
            bugtracker = self.makeBugTracker()

        if bug_task is not None:
            # If someone passes a value for bug *and* a value for
            # bug_task then the bug value will get clobbered, but that
            # doesn't matter since the bug should be the one that the
            # bug task belongs to anyway (unless they're having a crazy
            # moment, in which case we're saving them from themselves).
            bug = bug_task.bug
        elif bug is None:
            bug = self.makeBug()

        if owner is None:
            owner = self.makePerson()

        bug_watch = getUtility(IBugWatchSet).createBugWatch(
            bug, owner, bugtracker, str(remote_bug)
        )
        if bug_task is not None:
            bug_task.bugwatch = bug_watch
        removeSecurityProxy(bug_watch).next_check = datetime.now(timezone.utc)
        return bug_watch

    def makeBugComment(
        self, bug=None, owner=None, subject=None, body=None, bug_watch=None
    ):
        """Create and return a new bug comment.

        :param bug: An `IBug` or a bug ID or name, or None, in which
            case a new bug is created.
        :param owner: An `IPerson`, or None, in which case a new
            person is created.
        :param subject: An `IMessage` or a string, or None, in which
            case a new message will be generated.
        :param body: An `IMessage` or a string, or None, in which
            case a new message will be generated.
        :param bug_watch: An `IBugWatch`, which will be used to set the
            new comment's bugwatch attribute.
        :return: An `IBugMessage`.
        """
        if bug is None:
            bug = self.makeBug()
        elif isinstance(bug, (int, str)):
            bug = getUtility(IBugSet).getByNameOrID(str(bug))
        if owner is None:
            owner = self.makePerson()
        if subject is None:
            subject = self.getUniqueString()
        if body is None:
            body = self.getUniqueString()
        with person_logged_in(owner):
            return bug.newMessage(
                owner=owner,
                subject=subject,
                content=body,
                parent=None,
                bugwatch=bug_watch,
                remote_comment_id=None,
            )

    def makeBugAttachment(
        self,
        bug=None,
        owner=None,
        data=None,
        comment=None,
        filename=None,
        content_type=None,
        description=None,
        url=None,
        is_patch=_DEFAULT,
    ):
        """Create and return a new bug attachment.

        :param bug: An `IBug` or a bug ID or name, or None, in which
            case a new bug is created.
        :param owner: An `IPerson`, or None, in which case a new
            person is created.
        :param data: A file-like object or a string, or None, in which
            case a unique string will be used.
        :param comment: An `IMessage` or a string, or None, in which
            case a new message will be generated.
        :param filename: A string, or None, in which case a unique
            string will be used.
        :param content_type: The MIME-type of this file.
        :param description: The description of the attachment.
        :param url: External URL of the attachment (a string or None)
        :param is_patch: If true, this attachment is a patch.
        :return: An `IBugAttachment`.
        """
        if url:
            if data or filename:
                raise ValueError(
                    "Either `url` or `data` / `filename` can be provided."
                )
        else:
            if data is None:
                data = self.getUniqueBytes()
            if filename is None:
                filename = self.getUniqueString()

        if bug is None:
            bug = self.makeBug()
        elif isinstance(bug, (int, str)):
            bug = getUtility(IBugSet).getByNameOrID(str(bug))
        if owner is None:
            owner = self.makePerson()
        if description is None:
            description = self.getUniqueString()
        if comment is None:
            comment = self.getUniqueString()
        # If the default value of is_patch when creating a new
        # BugAttachment should ever change, we don't want to interfere
        # with that.  So, we only override it if our caller explicitly
        # passed it.
        other_params = {}
        if is_patch is not _DEFAULT:
            other_params["is_patch"] = is_patch
        return bug.addAttachment(
            owner,
            data,
            comment,
            filename,
            url,
            content_type=content_type,
            description=description,
            **other_params,
        )

    def makeBugSubscriptionFilter(
        self, target=None, subscriber=None, subscribed_by=None
    ):
        """Create and return a new bug subscription filter.

        :param target: An `IStructuralSubscriptionTarget`.  Defaults to a
            new `Product`.
        :param subscriber: An `IPerson`.  Defaults to a new `Person`.
        :param subscribed_by: An `IPerson`.  Defaults to `subscriber`.
        :return: An `IBugSubscriptionFilter`.
        """
        if target is None:
            target = self.makeProduct()
        if subscriber is None:
            subscriber = self.makePerson()
        if subscribed_by is None:
            subscribed_by = subscriber
        return ProxyFactory(
            removeSecurityProxy(target).addBugSubscriptionFilter(
                subscriber, subscribed_by
            )
        )

    def makeSignedMessage(
        self,
        msgid=None,
        body=None,
        subject=None,
        attachment_contents=None,
        force_transfer_encoding=False,
        email_address=None,
        signing_context=None,
        to_address=None,
    ):
        """Return an ISignedMessage.

        :param msgid: An rfc2822 message-id.
        :param body: The body of the message.
        :param attachment_contents: The contents of an attachment.
        :param force_transfer_encoding: If True, ensure a transfer encoding is
            used.
        :param email_address: The address the mail is from.
        :param signing_context: A GPGSigningContext instance containing the
            gpg key to sign with.  If None, the message is unsigned.  The
            context also contains the password and gpg signing mode.
        """
        mail = SignedMessage()
        if email_address is None:
            person = self.makePerson()
            email_address = removeSecurityProxy(person).preferredemail.email
        mail["From"] = email_address
        if to_address is None:
            to_address = removeSecurityProxy(
                self.makePerson()
            ).preferredemail.email
        mail["To"] = to_address
        if subject is None:
            subject = self.getUniqueString("subject")
        mail["Subject"] = subject
        if msgid is None:
            msgid = self.makeUniqueRFC822MsgId()
        if body is None:
            body = self.getUniqueString("body")
        charset = "ascii"
        try:
            body = body.encode(charset)
        except UnicodeEncodeError:
            charset = "utf-8"
            body = body.encode(charset)
        mail["Message-Id"] = msgid
        mail["Date"] = formatdate()
        if signing_context is not None:
            gpghandler = getUtility(IGPGHandler)
            body = gpghandler.signContent(
                body,
                signing_context.key,
                signing_context.password,
                signing_context.mode,
            )
            assert body is not None
        if attachment_contents is None:
            mail.set_payload(body)
            body_part = mail
        else:
            body_part = EmailMessage()
            body_part.set_payload(body)
            mail.attach(body_part)
            attach_part = EmailMessage()
            attach_part.set_payload(attachment_contents)
            attach_part["Content-type"] = "application/octet-stream"
            if force_transfer_encoding:
                encode_base64(attach_part)
            mail.attach(attach_part)
            mail["Content-type"] = "multipart/mixed"
        body_part["Content-type"] = "text/plain"
        if force_transfer_encoding:
            encode_base64(body_part)
        body_part.set_charset(charset)
        mail.parsed_bytes = message_as_bytes(mail)
        return mail

    def makeSpecification(
        self,
        product=None,
        title=None,
        distribution=None,
        name=None,
        summary=None,
        owner=None,
        status=NewSpecificationDefinitionStatus.NEW,
        implementation_status=None,
        goal=None,
        specurl=None,
        assignee=None,
        drafter=None,
        approver=None,
        whiteboard=None,
        milestone=None,
        information_type=None,
        priority=None,
    ):
        """Create and return a new, arbitrary Blueprint.

        :param product: The product to make the blueprint on.  If one is
            not specified, an arbitrary product is created.
        """
        if distribution and product:
            raise AssertionError(
                "Cannot target a Specification to a distribution and "
                "a product simultaneously."
            )
        proprietary = (
            information_type not in PUBLIC_INFORMATION_TYPES
            and information_type is not None
        )
        if (
            product is None
            and milestone is not None
            and milestone.productseries is not None
        ):
            product = milestone.productseries.product
        if distribution is None and product is None:
            if proprietary:
                if information_type == InformationType.EMBARGOED:
                    specification_sharing_policy = (
                        SpecificationSharingPolicy.EMBARGOED_OR_PROPRIETARY
                    )
                else:
                    specification_sharing_policy = (
                        SpecificationSharingPolicy.PUBLIC_OR_PROPRIETARY
                    )
            else:
                specification_sharing_policy = None
            product = self.makeProduct(
                specification_sharing_policy=specification_sharing_policy
            )
        if name is None:
            name = self.getUniqueString("name")
        if summary is None:
            summary = self.getUniqueString("summary")
        if title is None:
            title = self.getUniqueString("title")
        if owner is None:
            owner = self.makePerson()
        status_names = NewSpecificationDefinitionStatus.items.mapping.keys()
        if status.name in status_names:
            definition_status = status
        else:
            # This is to satisfy life cycle requirements.
            definition_status = NewSpecificationDefinitionStatus.NEW
        spec = getUtility(ISpecificationSet).new(
            name=name,
            title=title,
            specurl=None,
            summary=summary,
            definition_status=definition_status,
            whiteboard=whiteboard,
            owner=owner,
            assignee=assignee,
            drafter=drafter,
            approver=approver,
            target=product or distribution,
        )
        naked_spec = removeSecurityProxy(spec)
        if priority is not None:
            naked_spec.priority = priority
        if status.name not in status_names:
            # Set the closed status after the status has a sane initial state.
            naked_spec.definition_status = status
        if status in (
            SpecificationDefinitionStatus.OBSOLETE,
            SpecificationDefinitionStatus.SUPERSEDED,
        ):
            # This is to satisfy a DB constraint of obsolete specs.
            naked_spec.completer = owner
            naked_spec.date_completed = datetime.now(timezone.utc)
        naked_spec.specurl = specurl
        naked_spec.milestone = milestone
        if goal is not None:
            naked_spec.proposeGoal(goal, spec.target.owner)
        if implementation_status is not None:
            naked_spec.implementation_status = implementation_status
            naked_spec.updateLifecycleStatus(owner)
        if information_type is not None:
            if proprietary:
                naked_spec.target._ensurePolicies([information_type])
            naked_spec.transitionToInformationType(
                information_type, naked_spec.target.owner
            )
        return spec

    makeBlueprint = makeSpecification

    def makeSpecificationWorkItem(
        self,
        title=None,
        specification=None,
        assignee=None,
        milestone=None,
        deleted=False,
        status=SpecificationWorkItemStatus.TODO,
        sequence=None,
    ):
        if title is None:
            title = self.getUniqueString("title")
        if specification is None:
            product = None
            distribution = None
            if milestone is not None:
                product = milestone.product
                distribution = milestone.distribution
            specification = self.makeSpecification(
                product=product, distribution=distribution
            )
        if sequence is None:
            sequence = self.getUniqueInteger()
        work_item = removeSecurityProxy(specification).newWorkItem(
            title=title,
            sequence=sequence,
            status=status,
            assignee=assignee,
            milestone=milestone,
        )
        work_item.deleted = deleted
        return ProxyFactory(work_item)

    def makeQuestion(
        self, target=None, title=None, owner=None, description=None, **kwargs
    ):
        """Create and return a new, arbitrary Question.

        :param target: The IQuestionTarget to make the question on. If one is
            not specified, an arbitrary product is created.
        :param title: The question title. If one is not provided, an
            arbitrary title is created.
        :param owner: The owner of the question. If one is not provided, the
            question target owner will be used.
        :param description: The question description.
        """
        if target is None:
            target = self.makeProduct()
        if title is None:
            title = self.getUniqueUnicode("title")
        if owner is None:
            owner = target.owner
        if description is None:
            description = self.getUniqueUnicode("description")
        with person_logged_in(owner):
            question = target.newQuestion(
                owner=owner, title=title, description=description, **kwargs
            )
        return question

    def makeQuestionSubscription(self, question=None, person=None):
        """Create a QuestionSubscription."""
        if question is None:
            question = self.makeQuestion()
        if person is None:
            person = self.makePerson()
        with person_logged_in(person):
            return question.subscribe(person)

    def makeFAQ(self, target=None, title=None):
        """Create and return a new, arbitrary FAQ.

        :param target: The IFAQTarget to make the FAQ on. If one is
            not specified, an arbitrary product is created.
        :param title: The FAQ title. If one is not provided, an
            arbitrary title is created.
        """
        if target is None:
            target = self.makeProduct()
        if title is None:
            title = self.getUniqueString("title")
        return ProxyFactory(
            target.newFAQ(owner=target.owner, title=title, content="content")
        )

    def makePackageCodeImport(self, sourcepackage=None, **kwargs):
        """Make a code import targeting a sourcepackage."""
        if sourcepackage is None:
            sourcepackage = self.makeSourcePackage()
        return self.makeCodeImport(context=sourcepackage, **kwargs)

    def makeProductCodeImport(self, product=None, **kwargs):
        """Make a code import targeting a product."""
        if product is None:
            product = self.makeProduct()
        return self.makeCodeImport(context=product, **kwargs)

    def makeCodeImport(
        self,
        svn_branch_url=None,
        cvs_root=None,
        cvs_module=None,
        context=None,
        branch_name=None,
        git_repo_url=None,
        bzr_branch_url=None,
        registrant=None,
        rcs_type=None,
        target_rcs_type=None,
        review_status=None,
        owner=None,
    ):
        """Create and return a new, arbitrary code import.

        The type of code import will be inferred from the source details
        passed in, but defaults to a Subversion->Bazaar import from an
        arbitrary unique URL.  (If the target type is specified as Git, then
        the source type instead defaults to Git.)
        """
        if target_rcs_type is None:
            target_rcs_type = TargetRevisionControlSystems.BZR
        if (
            svn_branch_url
            is cvs_root
            is cvs_module
            is git_repo_url
            is bzr_branch_url
            is None
        ):
            if target_rcs_type == TargetRevisionControlSystems.BZR:
                svn_branch_url = self.getUniqueURL()
            else:
                git_repo_url = self.getUniqueURL()

        if context is None:
            context = self.makeProduct()
        if branch_name is None:
            branch_name = self.getUniqueUnicode("name")
        if registrant is None:
            registrant = self.makePerson()

        code_import_set = getUtility(ICodeImportSet)
        if svn_branch_url is not None:
            assert rcs_type in (None, RevisionControlSystems.BZR_SVN)
            return code_import_set.new(
                registrant,
                context,
                branch_name,
                rcs_type=RevisionControlSystems.BZR_SVN,
                target_rcs_type=target_rcs_type,
                url=svn_branch_url,
                review_status=review_status,
                owner=owner,
            )
        elif git_repo_url is not None:
            assert rcs_type in (None, RevisionControlSystems.GIT)
            return code_import_set.new(
                registrant,
                context,
                branch_name,
                rcs_type=RevisionControlSystems.GIT,
                target_rcs_type=target_rcs_type,
                url=git_repo_url,
                review_status=review_status,
                owner=owner,
            )
        elif bzr_branch_url is not None:
            return code_import_set.new(
                registrant,
                context,
                branch_name,
                rcs_type=RevisionControlSystems.BZR,
                target_rcs_type=target_rcs_type,
                url=bzr_branch_url,
                review_status=review_status,
                owner=owner,
            )
        else:
            assert rcs_type in (None, RevisionControlSystems.CVS)
            return code_import_set.new(
                registrant,
                context,
                branch_name,
                rcs_type=RevisionControlSystems.CVS,
                target_rcs_type=target_rcs_type,
                cvs_root=cvs_root,
                cvs_module=cvs_module,
                review_status=review_status,
                owner=owner,
            )

    def makeChangelog(self, spn=None, versions=[]):
        """Create and return a LFA of a valid Debian-style changelog.

        Note that the changelog returned is unicode - this is deliberate
        so that code is forced to cope with it as utf-8 changelogs are
        normal.
        """
        if spn is None:
            spn = self.getUniqueString()
        changelog = ""
        for version in versions:
            entry = dedent(
                """\
            %s (%s) unstable; urgency=low

              * %s.

             -- Føo Bær <foo@example.com>  Tue, 01 Jan 1970 01:50:41 +0000

            """
                % (spn, version, version)
            )
            changelog += entry
        return self.makeLibraryFileAlias(content=changelog.encode("utf-8"))

    def makeCodeImportEvent(self, code_import=None):
        """Create and return a CodeImportEvent."""
        if code_import is None:
            code_import = self.makeCodeImport()
        person = self.makePerson()
        code_import_event_set = getUtility(ICodeImportEventSet)
        return code_import_event_set.newCreate(code_import, person)

    def makeCodeImportJob(self, code_import=None):
        """Create and return a new code import job for the given import.

        This implies setting the import's review_status to REVIEWED.
        """
        if code_import is None:
            code_import = self.makeCodeImport()
        code_import.updateFromData(
            {"review_status": CodeImportReviewStatus.REVIEWED},
            code_import.registrant,
        )
        return code_import.import_job

    def makeCodeImportMachine(self, set_online=False, hostname=None):
        """Return a new CodeImportMachine.

        The machine will be in the OFFLINE state."""
        if hostname is None:
            hostname = self.getUniqueUnicode("machine-")
        if set_online:
            state = CodeImportMachineState.ONLINE
        else:
            state = CodeImportMachineState.OFFLINE
        machine = getUtility(ICodeImportMachineSet).new(hostname, state)
        return machine

    def makeCodeImportResult(
        self,
        code_import=None,
        result_status=None,
        date_started=None,
        date_finished=None,
        log_excerpt=None,
        log_alias=None,
        machine=None,
        requesting_user=None,
    ):
        """Create and return a new CodeImportResult."""
        if code_import is None:
            code_import = self.makeCodeImport()
        if machine is None:
            machine = self.makeCodeImportMachine()
        if log_excerpt is None:
            log_excerpt = self.getUniqueUnicode()
        if result_status is None:
            result_status = CodeImportResultStatus.FAILURE
        if date_finished is None:
            # If a date_started is specified, then base the finish time
            # on that.
            if date_started is None:
                date_finished = next(time_counter())
            else:
                date_finished = date_started + timedelta(hours=4)
        if date_started is None:
            date_started = date_finished - timedelta(hours=4)
        if log_alias is None:
            log_alias = self.makeLibraryFileAlias()
        return getUtility(ICodeImportResultSet).new(
            code_import,
            machine,
            requesting_user,
            log_excerpt,
            log_alias,
            result_status,
            date_started,
            date_finished,
        )

    def makeCodeReviewComment(
        self,
        sender=None,
        subject=None,
        body=None,
        vote=None,
        vote_tag=None,
        parent=None,
        merge_proposal=None,
        date_created=DEFAULT,
        git=False,
    ):
        if sender is None:
            sender = self.makePerson()
        if subject is None:
            subject = self.getUniqueString("subject")
        if body is None:
            body = self.getUniqueString("content")
        if merge_proposal is None:
            if parent:
                merge_proposal = parent.branch_merge_proposal
            elif git:
                merge_proposal = self.makeBranchMergeProposalForGit(
                    registrant=sender
                )
            else:
                merge_proposal = self.makeBranchMergeProposal(
                    registrant=sender
                )
        with person_logged_in(sender):
            return ProxyFactory(
                merge_proposal.createComment(
                    sender,
                    subject,
                    body,
                    vote,
                    vote_tag,
                    parent,
                    _date_created=date_created,
                )
            )

    def makeCodeReviewVoteReference(self, git=False):
        if git:
            bmp = removeSecurityProxy(self.makeBranchMergeProposalForGit())
        else:
            bmp = removeSecurityProxy(self.makeBranchMergeProposal())
        candidate = self.makePerson()
        return ProxyFactory(bmp.nominateReviewer(candidate, bmp.registrant))

    def makeMessage(
        self,
        subject=None,
        content=None,
        parent=None,
        owner=None,
        datecreated=None,
    ):
        if subject is None:
            subject = self.getUniqueString()
        if content is None:
            content = self.getUniqueString()
        if owner is None:
            owner = self.makePerson()
        if datecreated is None:
            datecreated = datetime.now(timezone.utc)
        rfc822msgid = self.makeUniqueRFC822MsgId()
        message = Message(
            rfc822msgid=rfc822msgid,
            subject=subject,
            owner=owner,
            parent=parent,
            datecreated=datecreated,
        )
        MessageChunk(message=message, sequence=1, content=content)
        return message

    def makeLanguage(
        self,
        language_code=None,
        name=None,
        pluralforms=None,
        plural_expression=None,
    ):
        """Makes a language given the language_code and name."""
        if language_code is None:
            language_code = self.getUniqueString("lang")
        if name is None:
            name = "Language %s" % language_code
        if plural_expression is None and pluralforms is not None:
            # If the number of plural forms is known, the language
            # should also have a plural expression and vice versa.
            plural_expression = "n %% %d" % pluralforms

        language_set = getUtility(ILanguageSet)
        return language_set.createLanguage(
            language_code,
            name,
            pluralforms=pluralforms,
            pluralexpression=plural_expression,
        )

    def makeLanguagePack(self, distroseries=None, languagepack_type=None):
        """Create a language pack."""
        if distroseries is None:
            distroseries = self.makeUbuntuDistroSeries()
        if languagepack_type is None:
            languagepack_type = LanguagePackType.FULL
        return getUtility(ILanguagePackSet).addLanguagePack(
            distroseries, self.makeLibraryFileAlias(), languagepack_type
        )

    def makeLibraryFileAlias(
        self,
        filename=None,
        content=None,
        content_type="text/plain",
        restricted=False,
        expires=None,
        db_only=False,
    ):
        """Make a library file, and return the alias."""
        if filename is None:
            filename = self.getUniqueString("filename")
        if content is None:
            content = self.getUniqueBytes()
        else:
            content = six.ensure_binary(content)

        if db_only:
            # Often we don't actually care if the file exists on disk.
            # This lets us run tests without a librarian server.
            lfc = LibraryFileContent(
                filesize=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
                sha1=hashlib.sha1(content).hexdigest(),
                md5=hashlib.md5(content).hexdigest(),
            )
            IStore(LibraryFileContent).add(lfc)
            lfa = ProxyFactory(
                LibraryFileAlias(
                    content=lfc,
                    filename=filename,
                    mimetype=content_type,
                    expires=expires,
                    restricted=restricted,
                )
            )
            IStore(LibraryFileAlias).flush()
        else:
            lfa = getUtility(ILibraryFileAliasSet).create(
                filename,
                len(content),
                BytesIO(content),
                content_type,
                expires=expires,
                restricted=restricted,
            )
        return lfa

    def makeDistribution(
        self,
        name=None,
        displayname=None,
        owner=None,
        registrant=None,
        members=None,
        title=None,
        aliases=None,
        bug_supervisor=None,
        driver=None,
        publish_root_dir=None,
        publish_base_url=None,
        publish_copy_base_url=None,
        no_pubconf=False,
        icon=None,
        summary=None,
        vcs=None,
        oci_project_admin=None,
        bug_sharing_policy=None,
        branch_sharing_policy=None,
        specification_sharing_policy=None,
        information_type=None,
    ):
        """Make a new distribution."""
        if name is None:
            name = self.getUniqueString(prefix="distribution")
        if displayname is None:
            displayname = name.capitalize()
        if title is None:
            title = self.getUniqueString()
        description = self.getUniqueString()
        if summary is None:
            summary = self.getUniqueString()
        domainname = self.getUniqueString()
        if registrant is None:
            registrant = self.makePerson()
        if owner is None:
            owner = self.makePerson()
        if members is None:
            members = self.makeTeam(owner)
        distro = getUtility(IDistributionSet).new(
            name,
            displayname,
            title,
            description,
            summary,
            domainname,
            members,
            owner,
            registrant,
            icon=icon,
            vcs=vcs,
            information_type=information_type,
        )
        naked_distro = removeSecurityProxy(distro)
        if aliases is not None:
            naked_distro.setAliases(aliases)
        if driver is not None:
            naked_distro.driver = driver
        if bug_supervisor is not None:
            naked_distro.bug_supervisor = bug_supervisor
        if oci_project_admin is not None:
            naked_distro.oci_project_admin = oci_project_admin
        # makeProduct defaults licenses to [License.OTHER_PROPRIETARY] if
        # any non-public sharing policy is set, which ensures a
        # complimentary commercial subscription.  However, Distribution
        # doesn't have a licenses field, so deal with the commercial
        # subscription directly here instead.
        if (
            (
                bug_sharing_policy is not None
                and bug_sharing_policy != BugSharingPolicy.PUBLIC
            )
            or (
                branch_sharing_policy is not None
                and branch_sharing_policy != BranchSharingPolicy.PUBLIC
            )
            or (
                specification_sharing_policy is not None
                and specification_sharing_policy
                != SpecificationSharingPolicy.PUBLIC
            )
        ):
            naked_distro._ensure_complimentary_subscription()
        if branch_sharing_policy:
            naked_distro.setBranchSharingPolicy(branch_sharing_policy)
        if bug_sharing_policy:
            naked_distro.setBugSharingPolicy(bug_sharing_policy)
        if specification_sharing_policy:
            naked_distro.setSpecificationSharingPolicy(
                specification_sharing_policy
            )
        if not no_pubconf:
            self.makePublisherConfig(
                distro,
                publish_root_dir,
                publish_base_url,
                publish_copy_base_url,
            )
        return distro

    def makeDistroSeries(
        self,
        distribution=None,
        version=None,
        status=SeriesStatus.DEVELOPMENT,
        previous_series=None,
        name=None,
        displayname=None,
        registrant=None,
        owner=None,
    ):
        """Make a new `DistroSeries`."""
        if distribution is None:
            distribution = self.makeDistribution(owner=owner)
        if name is None:
            name = self.getUniqueString(prefix="distroseries")
        if displayname is None:
            displayname = name.capitalize()
        if version is None:
            version = "%s.0" % self.getUniqueInteger()
        if registrant is None:
            registrant = distribution.owner

        # We don't want to login() as the person used to create the product,
        # so we remove the security proxy before creating the series.
        naked_distribution = removeSecurityProxy(distribution)
        series = naked_distribution.newSeries(
            version=version,
            name=name,
            display_name=displayname,
            title=self.getUniqueString(),
            summary=self.getUniqueString(),
            description=self.getUniqueString(),
            previous_series=previous_series,
            registrant=registrant,
        )
        series.status = status

        return ProxyFactory(series)

    def makeUbuntuDistroSeries(
        self,
        version=None,
        status=SeriesStatus.DEVELOPMENT,
        previous_series=None,
        name=None,
        displayname=None,
    ):
        """Short cut to use the celebrity 'ubuntu' as the distribution."""
        ubuntu = getUtility(ILaunchpadCelebrities).ubuntu
        return self.makeDistroSeries(
            ubuntu, version, status, previous_series, name, displayname
        )

    def makeDistroSeriesDifference(
        self,
        derived_series=None,
        source_package_name_str=None,
        versions=None,
        difference_type=DistroSeriesDifferenceType.DIFFERENT_VERSIONS,
        status=DistroSeriesDifferenceStatus.NEEDS_ATTENTION,
        changelogs=None,
        set_base_version=False,
        parent_series=None,
    ):
        """Create a new distro series source package difference."""
        if derived_series is None:
            dsp = self.makeDistroSeriesParent(parent_series=parent_series)
            derived_series = dsp.derived_series
            parent_series = dsp.parent_series
        else:
            if parent_series is None:
                dsp = getUtility(IDistroSeriesParentSet).getByDerivedSeries(
                    derived_series
                )
                if dsp.is_empty():
                    new_dsp = self.makeDistroSeriesParent(
                        derived_series=derived_series,
                        parent_series=parent_series,
                    )
                    parent_series = new_dsp.parent_series
                else:
                    parent_series = dsp[0].parent_series

        if source_package_name_str is None:
            source_package_name_str = self.getUniqueString("src-name")

        source_package_name = self.getOrMakeSourcePackageName(
            source_package_name_str
        )

        if versions is None:
            versions = {}
        if changelogs is None:
            changelogs = {}

        base_version = versions.get("base")
        if base_version is not None:
            for series in [derived_series, parent_series]:
                spr = self.makeSourcePackageRelease(
                    sourcepackagename=source_package_name, version=base_version
                )
                self.makeSourcePackagePublishingHistory(
                    distroseries=series,
                    sourcepackagerelease=spr,
                    status=PackagePublishingStatus.SUPERSEDED,
                )

        if difference_type is not (
            DistroSeriesDifferenceType.MISSING_FROM_DERIVED_SERIES
        ):
            spr = self.makeSourcePackageRelease(
                sourcepackagename=source_package_name,
                version=versions.get("derived"),
                changelog=changelogs.get("derived"),
            )
            self.makeSourcePackagePublishingHistory(
                distroseries=derived_series,
                sourcepackagerelease=spr,
                status=PackagePublishingStatus.PUBLISHED,
            )

        if difference_type is not (
            DistroSeriesDifferenceType.UNIQUE_TO_DERIVED_SERIES
        ):
            spr = self.makeSourcePackageRelease(
                sourcepackagename=source_package_name,
                version=versions.get("parent"),
                changelog=changelogs.get("parent"),
            )
            self.makeSourcePackagePublishingHistory(
                distroseries=parent_series,
                sourcepackagerelease=spr,
                status=PackagePublishingStatus.PUBLISHED,
            )

        diff = getUtility(IDistroSeriesDifferenceSource).new(
            derived_series, source_package_name, parent_series
        )

        removeSecurityProxy(diff).status = status

        if set_base_version:
            version = versions.get("base", "%s.0" % self.getUniqueInteger())
            removeSecurityProxy(diff).base_version = version

        # We clear the cache on the diff, returning the object as if it
        # was just loaded from the store.
        clear_property_cache(diff)
        return diff

    def makeDistroSeriesDifferenceComment(
        self, distro_series_difference=None, owner=None, comment=None
    ):
        """Create a new distro series difference comment."""
        if distro_series_difference is None:
            distro_series_difference = self.makeDistroSeriesDifference()
        if owner is None:
            owner = self.makePerson()
        if comment is None:
            comment = self.getUniqueString("dsdcomment")

        return getUtility(IDistroSeriesDifferenceCommentSource).new(
            distro_series_difference, owner, comment
        )

    def makeDistroSeriesParent(
        self,
        derived_series=None,
        parent_series=None,
        initialized=False,
        is_overlay=False,
        inherit_overrides=False,
        pocket=None,
        component=None,
    ):
        if parent_series is None:
            parent_series = self.makeDistroSeries()
        if derived_series is None:
            derived_series = self.makeDistroSeries()
        return getUtility(IDistroSeriesParentSet).new(
            derived_series,
            parent_series,
            initialized,
            is_overlay,
            inherit_overrides,
            pocket,
            component,
        )

    def makeDistroArchSeries(
        self,
        distroseries=None,
        architecturetag=None,
        processor=None,
        official=True,
        owner=None,
        enabled=True,
    ):
        """Create a new distroarchseries"""

        if distroseries is None:
            distroseries = self.makeDistroSeries()
        if processor is None:
            processor = self.makeProcessor()
        if owner is None:
            owner = self.makePerson()
        # XXX: architecturetag & processor are tightly coupled. It's
        # wrong to just make a fresh architecture tag without also making a
        # processor to go with it.
        if architecturetag is None:
            architecturetag = self.getUniqueString("arch")
        return ProxyFactory(
            distroseries.newArch(
                architecturetag, processor, official, owner, enabled
            )
        )

    def makeBuildableDistroArchSeries(
        self,
        architecturetag=None,
        processor=None,
        supports_virtualized=True,
        supports_nonvirtualized=True,
        **kwargs,
    ):
        if architecturetag is None:
            architecturetag = self.getUniqueUnicode("arch")
        if processor is None:
            try:
                processor = getUtility(IProcessorSet).getByName(
                    architecturetag
                )
            except ProcessorNotFound:
                processor = self.makeProcessor(
                    name=architecturetag,
                    supports_virtualized=supports_virtualized,
                    supports_nonvirtualized=supports_nonvirtualized,
                )
        das = self.makeDistroArchSeries(
            architecturetag=architecturetag, processor=processor, **kwargs
        )
        # Add both a chroot and a LXD image to test that
        # getAllowedArchitectures doesn't get confused by multiple
        # PocketChroot rows for a single DistroArchSeries.
        fake_chroot = self.makeLibraryFileAlias(
            filename="fake_chroot.tar.gz", db_only=True
        )
        das.addOrUpdateChroot(fake_chroot)
        fake_lxd = self.makeLibraryFileAlias(
            filename="fake_lxd.tar.gz", db_only=True
        )
        das.addOrUpdateChroot(fake_lxd, image_type=BuildBaseImageType.LXD)
        return das

    def makeComponent(self, name=None):
        """Make a new `IComponent`."""
        if name is None:
            name = self.getUniqueString()
        return getUtility(IComponentSet).ensure(name)

    def makeComponentSelection(self, distroseries=None, component=None):
        """Make a new `ComponentSelection`.

        :param distroseries: Optional `DistroSeries`.  If none is given,
            one will be created.
        :param component: Optional `Component` or a component name.  If
            none is given, one will be created.
        """
        if distroseries is None:
            distroseries = self.makeDistroSeries()

        if not IComponent.providedBy(component):
            component = self.makeComponent(component)

        selection = ComponentSelection(
            distroseries=distroseries, component=component
        )
        del get_property_cache(distroseries).components
        return ProxyFactory(selection)

    def makeArchive(
        self,
        distribution=None,
        owner=None,
        name=None,
        purpose=None,
        enabled=True,
        private=False,
        virtualized=True,
        description=None,
        displayname=None,
        suppress_subscription_notifications=False,
        processors=None,
        publishing_method=ArchivePublishingMethod.LOCAL,
        repository_format=ArchiveRepositoryFormat.DEBIAN,
        metadata_overrides=None,
    ):
        """Create and return a new arbitrary archive.

        :param distribution: Supply IDistribution, defaults to a new one
            made with makeDistribution() for non-PPAs and ubuntu for PPAs.
        :param owner: Supply IPerson, defaults to a new one made with
            makePerson().
        :param name: Name of the archive, defaults to a random string.
        :param purpose: Supply ArchivePurpose, defaults to PPA.
        :param enabled: Whether the archive is enabled.
        :param private: Whether the archive is created private.
        :param virtualized: Whether the archive is virtualized.
        :param description: A description of the archive.
        :param suppress_subscription_notifications: Whether to suppress
            subscription notifications, defaults to False.  Only useful
            for private archives.
        :param publishing_method: `ArchivePublishingMethod` for this archive
            (defaults to `LOCAL`).
        :param repository_format: `ArchiveRepositoryFormat` for this archive
            (defaults to `DEBIAN`).
        """
        if purpose is None:
            purpose = ArchivePurpose.PPA
        elif isinstance(purpose, str):
            purpose = ArchivePurpose.items[purpose.upper()]

        if distribution is None:
            # See bug #568769
            if purpose == ArchivePurpose.PPA:
                distribution = getUtility(ILaunchpadCelebrities).ubuntu
            else:
                distribution = self.makeDistribution()
        if owner is None:
            owner = self.makePerson()
        if name is None:
            if purpose != ArchivePurpose.PPA:
                name = default_name_by_purpose.get(purpose)
            if name is None:
                name = self.getUniqueString()

        # Making a distribution makes an archive, and there can be only one
        # per distribution.
        if purpose == ArchivePurpose.PRIMARY:
            return ProxyFactory(distribution.main_archive)

        admins = getUtility(ILaunchpadCelebrities).admin
        with person_logged_in(admins.teamowner):
            archive = getUtility(IArchiveSet).new(
                owner=owner,
                purpose=purpose,
                distribution=distribution,
                name=name,
                displayname=displayname,
                enabled=enabled,
                require_virtualized=virtualized,
                description=description,
                processors=processors,
                publishing_method=publishing_method,
                repository_format=repository_format,
                metadata_overrides=metadata_overrides,
            )

        if private:
            naked_archive = removeSecurityProxy(archive)
            naked_archive.private = True

        if suppress_subscription_notifications:
            naked_archive = removeSecurityProxy(archive)
            naked_archive.suppress_subscription_notifications = True

        return archive

    def makeArchiveAdmin(self, archive=None):
        """Make an Archive Admin.

        :param archive: The `IArchive`, will be auto-created if None.

        Make and return an `IPerson` who has an `ArchivePermission` to admin
        the distroseries queue.
        """
        if archive is None:
            archive = self.makeArchive()

        person = self.makePerson()
        permission_set = getUtility(IArchivePermissionSet)
        permission_set.newQueueAdmin(archive, person, "main")
        return person

    def makeArchiveFile(
        self,
        archive=None,
        container=None,
        path=None,
        library_file=None,
        date_superseded=None,
        scheduled_deletion_date=None,
        date_removed=None,
    ):
        if archive is None:
            archive = self.makeArchive()
        if container is None:
            container = self.getUniqueUnicode()
        if path is None:
            path = self.getUniqueUnicode()
        if library_file is None:
            library_file = self.makeLibraryFileAlias()
        archive_file = getUtility(IArchiveFileSet).new(
            archive=archive,
            container=container,
            path=path,
            library_file=library_file,
        )
        if date_superseded is not None:
            removeSecurityProxy(archive_file).date_superseded = date_superseded
        if scheduled_deletion_date is not None:
            removeSecurityProxy(archive_file).scheduled_deletion_date = (
                scheduled_deletion_date
            )
        if date_removed is not None:
            removeSecurityProxy(archive_file).date_removed = date_removed
        return archive_file

    def makeBuilder(
        self,
        processors=None,
        url=None,
        name=None,
        title=None,
        owner=None,
        active=True,
        virtualized=True,
        vm_host=None,
        vm_reset_protocol=None,
        open_resources=None,
        restricted_resources=None,
        manual=False,
    ):
        """Make a new builder for i386 virtualized builds by default.

        Note: the builder returned will not be able to actually build -
        we currently have a build worker setup for 'bob' only in the
        test environment.
        """
        if processors is None:
            processors = [getUtility(IProcessorSet).getByName("386")]
        if url is None:
            url = "http://%s:8221/" % self.getUniqueUnicode()
        if name is None:
            name = self.getUniqueUnicode("builder-name")
        if title is None:
            title = self.getUniqueUnicode("builder-title")
        if owner is None:
            owner = self.makePerson()
        if virtualized and vm_reset_protocol is None:
            vm_reset_protocol = BuilderResetProtocol.PROTO_1_1

        with admin_logged_in():
            return getUtility(IBuilderSet).new(
                processors,
                url,
                name,
                title,
                owner,
                active,
                virtualized,
                vm_host,
                manual=manual,
                vm_reset_protocol=vm_reset_protocol,
                open_resources=open_resources,
                restricted_resources=restricted_resources,
            )

    def makeRecipeText(self, *branches):
        if len(branches) == 0:
            branches = (self.makeAnyBranch(),)
        base_branch = branches[0]
        other_branches = branches[1:]
        if IBranch.providedBy(base_branch):
            text = MINIMAL_RECIPE_TEXT_BZR % base_branch.identity
        elif IGitRepository.providedBy(base_branch):
            # The UI normally guides people towards using an explicit branch
            # name, but it's also possible to leave the branch name empty
            # which is equivalent to the repository's default branch.  This
            # makes that mode easier to test.
            text = "%s\n%s\n" % (
                MINIMAL_RECIPE_TEXT_GIT.splitlines()[0],
                base_branch.identity,
            )
        elif IGitRef.providedBy(base_branch):
            text = MINIMAL_RECIPE_TEXT_GIT % (
                base_branch.repository.identity,
                base_branch.name,
            )
        else:
            raise AssertionError(
                "Unsupported base_branch: %r" % (base_branch,)
            )
        for i, branch in enumerate(other_branches):
            if IBranch.providedBy(branch) or IGitRepository.providedBy(branch):
                text += "merge dummy-%s %s\n" % (i, branch.identity)
            elif IGitRef.providedBy(branch):
                text += "merge dummy-%s %s %s\n" % (
                    i,
                    branch.repository.identity,
                    branch.name,
                )
            else:
                raise AssertionError("Unsupported branch: %r" % (branch,))
        return text

    def makeRecipe(self, *branches):
        """Make a builder recipe that references `branches`.

        If no branches are passed, return a recipe text that references an
        arbitrary branch.
        """
        from brzbuildrecipe.recipe import RecipeParser

        parser = RecipeParser(self.makeRecipeText(*branches))
        return parser.parse()

    def makeSourcePackageRecipeDistroseries(self, name="warty"):
        """Return a supported Distroseries to use with Source Package Recipes.

        Ew.  This uses sampledata currently, which is the ONLY reason this
        method exists: it gives us a migration path away from sampledata.
        """
        ubuntu = getUtility(IDistributionSet).getByName("ubuntu")
        return ubuntu.getSeries(name)

    def makeSourcePackageRecipe(
        self,
        registrant=None,
        owner=None,
        distroseries=None,
        name=None,
        description=None,
        branches=(),
        build_daily=False,
        daily_build_archive=None,
        is_stale=None,
        recipe=None,
        date_created=DEFAULT,
    ):
        """Make a `SourcePackageRecipe`."""
        if registrant is None:
            registrant = self.makePerson()
        if owner is None:
            owner = self.makePerson()
        if distroseries is None:
            distroseries = self.makeSourcePackageRecipeDistroseries()

        if name is None:
            name = self.getUniqueUnicode("spr-name")
        if description is None:
            description = self.getUniqueUnicode("spr-description")
        if daily_build_archive is None:
            daily_build_archive = self.makeArchive(
                distribution=distroseries.distribution, owner=owner
            )
        if recipe is None:
            recipe = self.makeRecipeText(*branches)
        else:
            assert branches == ()
        source_package_recipe = getUtility(ISourcePackageRecipeSource).new(
            registrant,
            owner,
            name,
            recipe,
            description,
            [distroseries],
            daily_build_archive,
            build_daily,
            date_created,
        )
        if is_stale is not None:
            removeSecurityProxy(source_package_recipe).is_stale = is_stale
        IStore(source_package_recipe).flush()
        return source_package_recipe

    def makeSourcePackageRecipeBuild(
        self,
        sourcepackage=None,
        recipe=None,
        requester=None,
        archive=None,
        sourcename=None,
        distroseries=None,
        pocket=None,
        date_created=None,
        status=BuildStatus.NEEDSBUILD,
        duration=None,
    ):
        """Make a new SourcePackageRecipeBuild."""
        if recipe is None:
            recipe = self.makeSourcePackageRecipe(name=sourcename)
        if archive is None:
            archive = self.makeArchive()
        if distroseries is None:
            distroseries = self.makeDistroSeries(
                distribution=archive.distribution
            )
            arch = self.makeDistroArchSeries(distroseries=distroseries)
            removeSecurityProxy(distroseries).nominatedarchindep = arch
        if requester is None:
            requester = self.makePerson()
        spr_build = getUtility(ISourcePackageRecipeBuildSource).new(
            distroseries=distroseries,
            recipe=recipe,
            archive=archive,
            requester=requester,
            pocket=pocket,
            date_created=date_created,
        )
        if duration is not None:
            removeSecurityProxy(spr_build).updateStatus(
                BuildStatus.BUILDING, date_started=spr_build.date_created
            )
            removeSecurityProxy(spr_build).updateStatus(
                status, date_finished=spr_build.date_started + duration
            )
        else:
            removeSecurityProxy(spr_build).updateStatus(status)
        IStore(spr_build).flush()
        return spr_build

    def makeTranslationTemplatesBuild(self, branch=None):
        """Make a new `TranslationTemplatesBuild`.

        :param branch: The branch that the build should be for.  If none
            is given, one will be created.
        """
        if branch is None:
            branch = self.makeBranch()

        jobset = getUtility(ITranslationTemplatesBuildSource)
        return jobset.create(branch)

    def makePOTemplate(
        self,
        productseries=None,
        distroseries=None,
        sourcepackagename=None,
        owner=None,
        name=None,
        translation_domain=None,
        path=None,
        copy_pofiles=True,
        side=None,
        sourcepackage=None,
        iscurrent=True,
    ):
        """Make a new translation template."""
        if sourcepackage is not None:
            assert (
                distroseries is None
            ), "Cannot specify sourcepackage and distroseries"
            distroseries = sourcepackage.distroseries
            assert (
                sourcepackagename is None
            ), "Cannot specify sourcepackage and sourcepackagename"
            sourcepackagename = sourcepackage.sourcepackagename
        if productseries is None and distroseries is None:
            if side != TranslationSide.UBUNTU:
                # No context for this template; set up a productseries.
                productseries = self.makeProductSeries(owner=owner)
                # Make it use Translations, otherwise there's little point
                # to us creating a template for it.
                naked_series = removeSecurityProxy(productseries)
                naked_series.product.translations_usage = (
                    ServiceUsage.LAUNCHPAD
                )
            else:
                distroseries = self.makeUbuntuDistroSeries()
        if distroseries is not None and sourcepackagename is None:
            sourcepackagename = self.makeSourcePackageName()

        templateset = getUtility(IPOTemplateSet)
        subset = templateset.getSubset(
            distroseries, sourcepackagename, productseries
        )

        if name is None:
            name = self.getUniqueString()
        if translation_domain is None:
            translation_domain = self.getUniqueString()

        if owner is None:
            if productseries is None:
                owner = distroseries.owner
            else:
                owner = productseries.owner

        if path is None:
            path = "messages.pot"

        pot = subset.new(name, translation_domain, path, owner, copy_pofiles)
        removeSecurityProxy(pot).iscurrent = iscurrent
        return pot

    def makePOTemplateAndPOFiles(self, language_codes, **kwargs):
        """Create a POTemplate and associated POFiles.

        Create a POTemplate for the given distroseries/sourcepackagename or
        productseries and create a POFile for each language. Returns the
        template.
        """
        template = self.makePOTemplate(**kwargs)
        for language_code in language_codes:
            self.makePOFile(language_code, template, template.owner)
        return template

    def makePOFile(
        self,
        language_code=None,
        potemplate=None,
        owner=None,
        create_sharing=False,
        language=None,
        side=None,
    ):
        """Make a new translation file."""
        assert (
            language_code is None or language is None
        ), "Please specify only one of language_code and language."
        if language_code is None:
            if language is None:
                language = self.makeLanguage()
            language_code = language.code
        if potemplate is None:
            potemplate = self.makePOTemplate(owner=owner, side=side)
        else:
            assert side is None, "Cannot specify both side and potemplate."
        return ProxyFactory(
            potemplate.newPOFile(language_code, create_sharing=create_sharing)
        )

    def makePOTMsgSet(
        self,
        potemplate=None,
        singular=None,
        plural=None,
        context=None,
        sequence=None,
        commenttext=None,
        filereferences=None,
        sourcecomment=None,
        flagscomment=None,
    ):
        """Make a new `POTMsgSet` in the given template."""
        if potemplate is None:
            potemplate = self.makePOTemplate()
        if singular is None and plural is None:
            singular = self.getUniqueUnicode()
        if sequence is None:
            sequence = self.getUniqueInteger()
        potmsgset = potemplate.createMessageSetFromText(
            singular, plural, context, sequence
        )
        if commenttext is not None:
            potmsgset.commenttext = commenttext
        if filereferences is not None:
            potmsgset.filereferences = filereferences
        if sourcecomment is not None:
            potmsgset.sourcecomment = sourcecomment
        if flagscomment is not None:
            potmsgset.flagscomment = flagscomment
        IStore(potmsgset).flush()
        return ProxyFactory(potmsgset)

    def makePOFileAndPOTMsgSet(
        self, language_code=None, msgid=None, with_plural=False, side=None
    ):
        """Make a `POFile` with a `POTMsgSet`."""
        pofile = self.makePOFile(language_code, side=side)

        if with_plural:
            if msgid is None:
                msgid = self.getUniqueUnicode()
            plural = self.getUniqueUnicode()
        else:
            plural = None

        potmsgset = self.makePOTMsgSet(
            pofile.potemplate, singular=msgid, plural=plural
        )

        return pofile, potmsgset

    def makeTranslationsDict(self, translations=None):
        """Make sure translations are stored in a dict, e.g. {0: "foo"}.

        If translations is already dict, it is returned unchanged.
        If translations is a sequence, it is enumerated into a dict.
        If translations is None, an arbitrary single translation is created.
        """
        translations = removeSecurityProxy(translations)
        if translations is None:
            return {0: self.getUniqueUnicode()}
        if isinstance(translations, dict):
            return translations
        assert isinstance(
            translations, (list, tuple)
        ), "Expecting either a dict or a sequence."
        return dict(enumerate(translations))

    def makeSuggestion(
        self,
        pofile=None,
        potmsgset=None,
        translator=None,
        translations=None,
        date_created=None,
    ):
        """Make a new suggested `TranslationMessage` in the given PO file."""
        if pofile is None:
            pofile = self.makePOFile("sr")
        if potmsgset is None:
            potmsgset = self.makePOTMsgSet(pofile.potemplate)
        if translator is None:
            translator = self.makePerson()
        translations = self.makeTranslationsDict(translations)
        translation_message = potmsgset.submitSuggestion(
            pofile, translator, translations
        )
        assert (
            translation_message is not None
        ), "Cannot make suggestion on translation credits POTMsgSet."
        if date_created is not None:
            naked_translation_message = removeSecurityProxy(
                translation_message
            )
            naked_translation_message.date_created = date_created
            IStore(naked_translation_message).flush()
        return ProxyFactory(translation_message)

    def makeCurrentTranslationMessage(
        self,
        pofile=None,
        potmsgset=None,
        translator=None,
        reviewer=None,
        translations=None,
        diverged=False,
        current_other=False,
        date_created=None,
        date_reviewed=None,
        language=None,
        side=None,
        potemplate=None,
    ):
        """Create a `TranslationMessage` and make it current.

        By default the message will only be current on the side (Ubuntu
        or upstream) that `pofile` is on.

        Be careful: if the message is already translated, calling this
        method may violate database unique constraints.

        :param pofile: `POFile` to put translation in; if omitted, one
            will be created.
        :param potmsgset: `POTMsgSet` to translate; if omitted, one will
            be created (with sequence number 1).
        :param translator: `Person` who created the translation.  If
            omitted, one will be created.
        :param reviewer: `Person` who reviewed the translation.  If
            omitted, one will be created.
        :param translations: Strings to translate the `POTMsgSet`
            to.  Can be either a list, or a dict mapping plural form
            numbers to the forms' respective translations.
            If omitted, will translate to a single random string.
        :param diverged: Create a diverged message?
        :param current_other: Should the message also be current on the
            other translation side?  (Cannot be combined with `diverged`).
        :param date_created: Force a specific creation date instead of 'now'.
        :param date_reviewed: Force a specific review date instead of 'now'.
        :param language: `Language` to use for the POFile
        :param side: The `TranslationSide` this translation should be for.
        :param potemplate: If provided, the POTemplate to use when creating
            the POFile.
        """
        assert not (
            diverged and current_other
        ), "A diverged message can't be current on the other side."
        assert None in (
            language,
            pofile,
        ), "Cannot specify both language and pofile."
        assert None in (side, pofile), "Cannot specify both side and pofile."
        link_potmsgset_with_potemplate = (
            pofile is None and potemplate is None
        ) or potmsgset is None
        if pofile is None:
            pofile = self.makePOFile(
                language=language, side=side, potemplate=potemplate
            )
        else:
            assert (
                potemplate is None
            ), "Cannot specify both pofile and potemplate"
        potemplate = pofile.potemplate
        if potmsgset is None:
            potmsgset = self.makePOTMsgSet(potemplate)
        if link_potmsgset_with_potemplate:
            # If we have a new pofile or a new potmsgset, we must link
            # the potmsgset to the pofile's potemplate.
            potmsgset.setSequence(pofile.potemplate, self.getUniqueInteger())
        else:
            # Otherwise it is the duty of the callsite to ensure
            # consistency.
            store = IStore(TranslationTemplateItem)
            tti_for_message_in_template = store.find(
                TranslationTemplateItem.potmsgset == potmsgset,
                TranslationTemplateItem.potemplate == pofile.potemplate,
            ).any()
            assert tti_for_message_in_template is not None
        if translator is None:
            translator = self.makePerson()
        if reviewer is None:
            reviewer = self.makePerson()
        translations = sanitize_translations_from_webui(
            potmsgset.singular_text,
            self.makeTranslationsDict(translations),
            pofile.language.pluralforms,
        )

        if diverged:
            message = self.makeDivergedTranslationMessage(
                pofile,
                potmsgset,
                translator,
                reviewer,
                translations,
                date_created,
            )
        else:
            message = potmsgset.setCurrentTranslation(
                pofile,
                translator,
                translations,
                RosettaTranslationOrigin.ROSETTAWEB,
                share_with_other_side=current_other,
            )
            if date_created is not None:
                removeSecurityProxy(message).date_created = date_created
        message = ProxyFactory(message)

        message.markReviewed(reviewer, date_reviewed)

        return ProxyFactory(message)

    def makeDivergedTranslationMessage(
        self,
        pofile=None,
        potmsgset=None,
        translator=None,
        reviewer=None,
        translations=None,
        date_created=None,
    ):
        """Create a diverged, current `TranslationMessage`."""
        if pofile is None:
            pofile = self.makePOFile("lt")
        if reviewer is None:
            reviewer = self.makePerson()

        message = self.makeSuggestion(
            pofile=pofile,
            potmsgset=potmsgset,
            translator=translator,
            translations=translations,
            date_created=date_created,
        )
        return message.approveAsDiverged(pofile, reviewer)

    def makeTranslationImportQueueEntry(
        self,
        path=None,
        productseries=None,
        distroseries=None,
        sourcepackagename=None,
        potemplate=None,
        content=None,
        uploader=None,
        pofile=None,
        format=None,
        status=None,
        by_maintainer=False,
    ):
        """Create a `TranslationImportQueueEntry`."""
        if path is None:
            path = self.getUniqueUnicode() + ".pot"

        for_distro = not (distroseries is None and sourcepackagename is None)
        for_project = productseries is not None
        has_template = potemplate is not None
        if has_template and not for_distro and not for_project:
            # Copy target from template.
            distroseries = potemplate.distroseries
            sourcepackagename = potemplate.sourcepackagename
            productseries = potemplate.productseries

        if sourcepackagename is None and distroseries is None:
            if productseries is None:
                productseries = self.makeProductSeries()
        else:
            if sourcepackagename is None:
                sourcepackagename = self.makeSourcePackageName()
            if distroseries is None:
                distroseries = self.makeDistroSeries()

        if uploader is None:
            uploader = self.makePerson()

        if content is None:
            content = self.getUniqueBytes()

        if format is None:
            format = TranslationFileFormat.PO

        if status is None:
            status = RosettaImportStatus.NEEDS_REVIEW

        content = six.ensure_binary(content)

        entry = getUtility(ITranslationImportQueue).addOrUpdateEntry(
            path=path,
            content=content,
            by_maintainer=by_maintainer,
            importer=uploader,
            productseries=productseries,
            distroseries=distroseries,
            sourcepackagename=sourcepackagename,
            potemplate=potemplate,
            pofile=pofile,
            format=format,
        )
        entry.setStatus(
            status, getUtility(ILaunchpadCelebrities).rosetta_experts
        )
        return entry

    def makeMailingList(self, team, owner):
        """Create a mailing list for the team."""
        team_list = getUtility(IMailingListSet).new(team, owner)
        team_list.startConstructing()
        team_list.transitionToStatus(MailingListStatus.ACTIVE)
        return team_list

    def makeTeamAndMailingList(
        self,
        team_name,
        owner_name,
        visibility=None,
        membership_policy=TeamMembershipPolicy.OPEN,
    ):
        """Make a new active mailing list for the named team.

        :param team_name: The new team's name.
        :type team_name: string
        :param owner_name: The name of the team's owner.
        :type owner: string
        :param visibility: The team's visibility. If it's None, the default
            (public) will be used.
        :type visibility: `PersonVisibility`
        :param membership_policy: The membership policy of the team.
        :type membership_policy: `TeamMembershipPolicy`
        :return: The new team and mailing list.
        :rtype: (`ITeam`, `IMailingList`)
        """
        owner = getUtility(IPersonSet).getByName(owner_name)
        display_name = SPACE.join(
            word.capitalize() for word in team_name.split("-")
        )
        team = getUtility(IPersonSet).getByName(team_name)
        if team is None:
            team = self.makeTeam(
                owner,
                displayname=display_name,
                name=team_name,
                visibility=visibility,
                membership_policy=membership_policy,
            )
        team_list = self.makeMailingList(team, owner)
        return team, team_list

    def makeTeamWithMailingListSubscribers(
        self, team_name, super_team=None, auto_subscribe=True
    ):
        """Create a team, mailing list, and subscribers.

        :param team_name: The name of the team to create.
        :param super_team: Make the team a member of the super_team.
        :param auto_subscribe: Automatically subscribe members to the
            mailing list.
        :return: A tuple of team and the member user.
        """
        team = self.makeTeam(name=team_name)
        member = self.makePerson()
        with celebrity_logged_in("admin"):
            if super_team is None:
                mailing_list = self.makeMailingList(team, team.teamowner)
            else:
                super_team.addMember(
                    team, reviewer=team.teamowner, force_team_add=True
                )
                mailing_list = super_team.mailing_list
            team.addMember(member, reviewer=team.teamowner)
            if auto_subscribe:
                mailing_list.subscribe(member)
        return team, member

    def makeMirrorProbeRecord(self, mirror):
        """Create a probe record for a mirror of a distribution."""
        log_file = BytesIO()
        log_file.write(b"Fake probe, nothing useful here.")
        log_file.seek(0)

        library_alias = getUtility(ILibraryFileAliasSet).create(
            name="foo",
            size=len(log_file.getvalue()),
            file=log_file,
            contentType="text/plain",
        )

        proberecord = mirror.newProbeRecord(library_alias)
        return ProxyFactory(proberecord)

    def makeMirror(
        self,
        distribution,
        displayname=None,
        country=None,
        http_url=None,
        https_url=None,
        ftp_url=None,
        rsync_url=None,
        official_candidate=False,
    ):
        """Create a mirror for the distribution."""
        if displayname is None:
            displayname = self.getUniqueString("mirror")
        # If no URL is specified create an HTTP URL.
        if http_url is https_url is ftp_url is rsync_url is None:
            http_url = self.getUniqueURL()
        # If no country is given use Argentina.
        if country is None:
            country = getUtility(ICountrySet)["AR"]

        mirror = distribution.newMirror(
            owner=distribution.owner,
            speed=MirrorSpeed.S256K,
            country=country,
            content=MirrorContent.ARCHIVE,
            display_name=displayname,
            description=None,
            http_base_url=http_url,
            https_base_url=https_url,
            ftp_base_url=ftp_url,
            rsync_base_url=rsync_url,
            official_candidate=official_candidate,
        )
        return ProxyFactory(mirror)

    def makeUniqueRFC822MsgId(self):
        """Make a unique RFC 822 message id.

        The created message id is guaranteed not to exist in the
        `Message` table already.
        """
        msg_id = make_msgid("launchpad")
        while not IStore(Message).find(Message, rfc822msgid=msg_id).is_empty():
            msg_id = make_msgid("launchpad")
        return msg_id

    def makeSourcePackageName(self, name=None):
        """Make an `ISourcePackageName`."""
        if name is None:
            name = self.getUniqueString()
        return getUtility(ISourcePackageNameSet).new(name)

    def getOrMakeSourcePackageName(self, name=None):
        """Get an existing`ISourcePackageName` or make a new one.

        This method encapsulates getOrCreateByName so that tests can be kept
        free of the getUtility(ISourcePackageNameSet) noise.
        """
        if name is None:
            return self.makeSourcePackageName()
        return getUtility(ISourcePackageNameSet).getOrCreateByName(name)

    def makeSourcePackage(
        self,
        sourcepackagename=None,
        distroseries=None,
        publish=False,
        owner=None,
    ):
        """Make an `ISourcePackage`.

        :param publish: if true, create a corresponding
            SourcePackagePublishingHistory.
        """
        # Make sure we have a real sourcepackagename object.
        if sourcepackagename is None or isinstance(sourcepackagename, str):
            sourcepackagename = self.getOrMakeSourcePackageName(
                sourcepackagename
            )
        if distroseries is None:
            distroseries = self.makeDistroSeries(owner=owner)
        if publish:
            self.makeSourcePackagePublishingHistory(
                distroseries=distroseries, sourcepackagename=sourcepackagename
            )
            with dbuser("statistician"):
                DistributionSourcePackageCache(
                    distribution=distroseries.distribution,
                    sourcepackagename=sourcepackagename,
                    archive=distroseries.main_archive,
                    name=sourcepackagename.name,
                )
        return distroseries.getSourcePackage(sourcepackagename)

    def getAnySourcePackageUrgency(self):
        return ProxyFactory(SourcePackageUrgency.MEDIUM)

    def makePackageUpload(
        self,
        distroseries=None,
        archive=None,
        pocket=None,
        changes_filename=None,
        changes_file_content=None,
        signing_key=None,
        status=None,
        package_copy_job=None,
    ):
        if archive is None:
            archive = self.makeArchive()
        if distroseries is None:
            distroseries = self.makeDistroSeries(
                distribution=archive.distribution
            )
        if changes_filename is None:
            changes_filename = self.getUniqueString("changesfilename")
        if changes_file_content is None:
            changes_file_content = self.getUniqueBytes(b"changesfilecontent")
        if pocket is None:
            pocket = PackagePublishingPocket.RELEASE
        package_upload = distroseries.createQueueEntry(
            pocket,
            archive,
            changes_filename,
            changes_file_content,
            signing_key=signing_key,
            package_copy_job=package_copy_job,
        )
        if status is not None:
            if status is not PackageUploadStatus.NEW:
                naked_package_upload = removeSecurityProxy(package_upload)
                status_changers = {
                    PackageUploadStatus.UNAPPROVED: (
                        naked_package_upload.setUnapproved
                    ),
                    PackageUploadStatus.REJECTED: (
                        naked_package_upload.setRejected
                    ),
                    PackageUploadStatus.DONE: naked_package_upload.setDone,
                    PackageUploadStatus.ACCEPTED: (
                        naked_package_upload.setAccepted
                    ),
                }
                status_changers[status]()
        return ProxyFactory(package_upload)

    def makeSourcePackageUpload(
        self, distroseries=None, sourcepackagename=None, component=None
    ):
        """Make a `PackageUpload` with a `PackageUploadSource` attached."""
        if distroseries is None:
            distroseries = self.makeDistroSeries()
        upload = self.makePackageUpload(
            distroseries=distroseries, archive=distroseries.main_archive
        )
        upload.addSource(
            self.makeSourcePackageRelease(
                sourcepackagename=sourcepackagename, component=component
            )
        )
        return upload

    def makeBuildPackageUpload(
        self,
        distroseries=None,
        pocket=None,
        binarypackagename=None,
        source_package_release=None,
        component=None,
    ):
        """Make a `PackageUpload` with a `PackageUploadBuild` attached."""
        if distroseries is None:
            distroseries = self.makeDistroSeries()
        upload = self.makePackageUpload(
            distroseries=distroseries,
            archive=distroseries.main_archive,
            pocket=pocket,
        )
        build = self.makeBinaryPackageBuild(
            source_package_release=source_package_release, pocket=pocket
        )
        self.makeBinaryPackageRelease(
            binarypackagename=binarypackagename,
            build=build,
            component=component,
        )
        upload.addBuild(build)
        return upload

    def makeCustomPackageUpload(
        self,
        distroseries=None,
        archive=None,
        pocket=None,
        custom_type=None,
        filename=None,
    ):
        """Make a `PackageUpload` with a `PackageUploadCustom` attached."""
        if distroseries is None:
            distroseries = self.makeDistroSeries()
        if archive is None:
            archive = distroseries.main_archive
        if custom_type is None:
            custom_type = PackageUploadCustomFormat.DEBIAN_INSTALLER
        upload = self.makePackageUpload(
            distroseries=distroseries, archive=archive, pocket=pocket
        )
        file_alias = self.makeLibraryFileAlias(filename=filename)
        upload.addCustom(file_alias, custom_type)
        return upload

    def makeCopyJobPackageUpload(
        self,
        distroseries=None,
        sourcepackagename=None,
        source_archive=None,
        target_pocket=None,
        requester=None,
        include_binaries=False,
    ):
        """Make a `PackageUpload` with a `PackageCopyJob` attached."""
        if distroseries is None:
            distroseries = self.makeDistroSeries()
        spph = self.makeSourcePackagePublishingHistory(
            archive=source_archive, sourcepackagename=sourcepackagename
        )
        spr = spph.sourcepackagerelease
        job = self.makePlainPackageCopyJob(
            package_name=spr.sourcepackagename.name,
            package_version=spr.version,
            source_archive=spph.archive,
            target_pocket=target_pocket,
            target_archive=distroseries.main_archive,
            target_distroseries=distroseries,
            requester=requester,
            include_binaries=include_binaries,
        )
        job.addSourceOverride(SourceOverride(spr.component, spr.section))
        try:
            job.run()
        except SuspendJobException:
            # Expected exception.
            job.suspend()
        upload_set = getUtility(IPackageUploadSet)
        return upload_set.getByPackageCopyJobIDs([job.id]).one()

    def makeSourcePackageRelease(
        self,
        archive=None,
        sourcepackagename=None,
        distroseries=None,
        maintainer=None,
        creator=None,
        component=None,
        section_name=None,
        urgency=None,
        version=None,
        builddepends=None,
        builddependsindep=None,
        build_conflicts=None,
        build_conflicts_indep=None,
        architecturehintlist="all",
        dsc_maintainer_rfc822=None,
        dsc_standards_version="3.6.2",
        dsc_format="1.0",
        dsc_binaries="foo-bin",
        date_uploaded=UTC_NOW,
        source_package_recipe_build=None,
        ci_build=None,
        dscsigningkey=None,
        user_defined_fields=None,
        changelog_entry=None,
        homepage=None,
        changelog=None,
        copyright=None,
        format=None,
    ):
        """Make a `SourcePackageRelease`."""
        if distroseries is None:
            if source_package_recipe_build is not None:
                distroseries = source_package_recipe_build.distroseries
            elif ci_build is not None:
                distroseries = ci_build.distro_series
            else:
                if archive is None:
                    distribution = None
                else:
                    distribution = archive.distribution
                distroseries = self.makeDistroSeries(distribution=distribution)

        if archive is None:
            archive = distroseries.main_archive

        if sourcepackagename is None or isinstance(sourcepackagename, str):
            sourcepackagename = self.getOrMakeSourcePackageName(
                sourcepackagename
            )

        if component is None or isinstance(component, str):
            component = self.makeComponent(component)

        if urgency is None:
            urgency = self.getAnySourcePackageUrgency()
        elif isinstance(urgency, str):
            urgency = SourcePackageUrgency.items[urgency.upper()]

        section = self.makeSection(name=section_name)

        if maintainer is None:
            maintainer = self.makePerson()

        if dsc_maintainer_rfc822 is None:
            dsc_maintainer_rfc822 = "%s <%s>" % (
                maintainer.displayname,
                removeSecurityProxy(maintainer).preferredemail.email,
            )

        if creator is None:
            creator = self.makePerson()

        if version is None:
            version = str(self.getUniqueInteger()) + "version"

        if format is None:
            format = SourcePackageType.DPKG

        if copyright is None:
            copyright = self.getUniqueString()

        spr = distroseries.createUploadedSourcePackageRelease(
            sourcepackagename=sourcepackagename,
            format=format,
            maintainer=maintainer,
            creator=creator,
            component=component,
            section=section,
            urgency=urgency,
            version=version,
            builddepends=builddepends,
            builddependsindep=builddependsindep,
            build_conflicts=build_conflicts,
            build_conflicts_indep=build_conflicts_indep,
            architecturehintlist=architecturehintlist,
            changelog=changelog,
            changelog_entry=changelog_entry,
            dsc=None,
            copyright=copyright,
            dscsigningkey=dscsigningkey,
            dsc_maintainer_rfc822=dsc_maintainer_rfc822,
            dsc_standards_version=dsc_standards_version,
            dsc_format=dsc_format,
            dsc_binaries=dsc_binaries,
            archive=archive,
            dateuploaded=date_uploaded,
            source_package_recipe_build=source_package_recipe_build,
            ci_build=ci_build,
            user_defined_fields=user_defined_fields,
            homepage=homepage,
        )
        return ProxyFactory(spr)

    def makeSourcePackageReleaseFile(
        self, sourcepackagerelease=None, library_file=None, filetype=None
    ):
        if sourcepackagerelease is None:
            sourcepackagerelease = self.makeSourcePackageRelease()
        if library_file is None:
            library_file = self.makeLibraryFileAlias()
        if filetype is None:
            filetype = SourcePackageFileType.DSC
        return ProxyFactory(
            sourcepackagerelease.addFile(library_file, filetype=filetype)
        )

    def makeBinaryPackageBuild(
        self,
        source_package_release=None,
        distroarchseries=None,
        archive=None,
        builder=None,
        status=None,
        pocket=None,
        date_created=None,
        processor=None,
        sourcepackagename=None,
        arch_indep=None,
    ):
        """Create a BinaryPackageBuild.

        If archive is not supplied, the source_package_release is used
        to determine archive.
        :param source_package_release: The SourcePackageRelease this binary
            build uses as its source.
        :param sourcepackagename: when source_package_release is None, the
            sourcepackagename from which the build will come.
        :param distroarchseries: The DistroArchSeries to use. Defaults to the
            one from the source_package_release, or a new one if not provided.
        :param archive: The Archive to use. Defaults to the one from the
            source_package_release, or the distro arch series main archive
            otherwise.
        :param builder: An optional builder to assign.
        :param status: The BuildStatus for the build.
        """
        if distroarchseries is None:
            if processor is None:
                processor = self.makeProcessor()
            if source_package_release is not None:
                distroseries = source_package_release.upload_distroseries
            elif archive is not None:
                distroseries = self.makeDistroSeries(
                    distribution=archive.distribution
                )
            else:
                distroseries = self.makeDistroSeries()
            distroarchseries = self.makeDistroArchSeries(
                distroseries=distroseries, processor=processor
            )
        else:
            if (
                processor is not None
                and processor != distroarchseries.processor
            ):
                raise AssertionError(
                    "DistroArchSeries and Processor must match."
                )
        if arch_indep is None:
            arch_indep = distroarchseries.isNominatedArchIndep
        if archive is None:
            if source_package_release is None:
                archive = distroarchseries.main_archive
            else:
                archive = source_package_release.upload_archive
        if pocket is None:
            pocket = PackagePublishingPocket.RELEASE
        elif isinstance(pocket, str):
            pocket = PackagePublishingPocket.items[pocket.upper()]

        if source_package_release is None:
            multiverse = self.makeComponent(name="multiverse")
            source_package_release = self.makeSourcePackageRelease(
                archive,
                component=multiverse,
                distroseries=distroarchseries.distroseries,
                sourcepackagename=sourcepackagename,
            )
            self.makeSourcePackagePublishingHistory(
                distroseries=distroarchseries.distroseries,
                archive=archive,
                sourcepackagerelease=source_package_release,
                pocket=pocket,
            )
        if status is None:
            status = BuildStatus.NEEDSBUILD
        admins = getUtility(ILaunchpadCelebrities).admin
        with person_logged_in(admins.teamowner):
            binary_package_build = getUtility(IBinaryPackageBuildSet).new(
                source_package_release=source_package_release,
                distro_arch_series=distroarchseries,
                status=status,
                archive=archive,
                pocket=pocket,
                builder=builder,
                arch_indep=arch_indep,
            )
        IStore(binary_package_build).flush()
        return binary_package_build

    def makeSourcePackagePublishingHistory(
        self,
        distroseries=None,
        archive=None,
        sourcepackagerelease=None,
        pocket=None,
        status=None,
        dateremoved=None,
        date_uploaded=UTC_NOW,
        scheduleddeletiondate=None,
        ancestor=None,
        creator=None,
        packageupload=None,
        spr_creator=None,
        channel=None,
        **kwargs,
    ):
        """Make a `SourcePackagePublishingHistory`.

        :param sourcepackagerelease: The source package release to publish
            If not provided, a new one will be created.
        :param distroseries: The distro series in which to publish.
            Default to the source package release one, or a new one will
            be created when not provided.
        :param archive: The archive to publish into. Default to the
            initial source package release  upload archive, or to the
            distro series main archive.
        :param pocket: The pocket to publish into. Can be specified as a
            string. Defaults to the BACKPORTS pocket.
        :param status: The publication status. Defaults to PENDING. If
            set to PUBLISHED, the publisheddate will be set to now.
        :param dateremoved: The removal date.
        :param date_uploaded: The upload date. Defaults to now.
        :param scheduleddeletiondate: The date where the publication
            is scheduled to be removed.
        :param ancestor: The publication ancestor parameter.
        :param creator: The publication creator.
        :param channel: An optional channel to publish into, as a string.
        :param **kwargs: All other parameters are passed through to the
            makeSourcePackageRelease call if needed.
        """
        if distroseries is None:
            if sourcepackagerelease is not None:
                distroseries = sourcepackagerelease.upload_distroseries
            else:
                if archive is None:
                    distribution = None
                else:
                    distribution = archive.distribution
                distroseries = self.makeDistroSeries(distribution=distribution)
        if archive is None:
            archive = distroseries.main_archive

        if pocket is None:
            pocket = self.getAnyPocket()
        elif isinstance(pocket, str):
            pocket = PackagePublishingPocket.items[pocket.upper()]

        if status is None:
            status = PackagePublishingStatus.PENDING
        elif isinstance(status, str):
            status = PackagePublishingStatus.items[status.upper()]

        if sourcepackagerelease is None:
            sourcepackagerelease = self.makeSourcePackageRelease(
                archive=archive,
                distroseries=distroseries,
                date_uploaded=date_uploaded,
                creator=spr_creator,
                **kwargs,
            )

        admins = getUtility(ILaunchpadCelebrities).admin
        with person_logged_in(admins.teamowner):
            spph = getUtility(IPublishingSet).newSourcePublication(
                archive,
                sourcepackagerelease,
                distroseries,
                pocket,
                component=sourcepackagerelease.component,
                section=sourcepackagerelease.section,
                ancestor=ancestor,
                creator=creator,
                packageupload=packageupload,
                channel=channel,
            )

        naked_spph = removeSecurityProxy(spph)
        naked_spph.status = status
        naked_spph.datecreated = date_uploaded
        naked_spph.dateremoved = dateremoved
        naked_spph.scheduleddeletiondate = scheduleddeletiondate
        if status == PackagePublishingStatus.PUBLISHED:
            naked_spph.datepublished = UTC_NOW
        return spph

    def makeBinaryPackagePublishingHistory(
        self,
        binarypackagerelease=None,
        binarypackagename=None,
        distroarchseries=None,
        component=None,
        section_name=None,
        priority=None,
        status=None,
        scheduleddeletiondate=None,
        dateremoved=None,
        datecreated=None,
        pocket=None,
        archive=None,
        source_package_release=None,
        binpackageformat=None,
        sourcepackagename=None,
        version=None,
        architecturespecific=False,
        with_debug=False,
        with_file=False,
        creator=None,
        channel=None,
    ):
        """Make a `BinaryPackagePublishingHistory`."""
        if distroarchseries is None:
            if archive is None:
                distribution = None
            else:
                distribution = archive.distribution
            distroseries = self.makeDistroSeries(distribution=distribution)
            distroarchseries = self.makeDistroArchSeries(
                distroseries=distroseries
            )

        if archive is None:
            archive = self.makeArchive(
                distribution=distroarchseries.distroseries.distribution,
                purpose=ArchivePurpose.PRIMARY,
            )
            # XXX wgrant 2013-05-23: We need to set build_debug_symbols
            # until the guard in publishBinaries is gone.
            need_debug = (
                with_debug or binpackageformat == BinaryPackageFormat.DDEB
            )
            if archive.purpose == ArchivePurpose.PRIMARY and need_debug:
                with admin_logged_in():
                    archive.build_debug_symbols = True

        if pocket is None:
            pocket = self.getAnyPocket()
        if status is None:
            status = PackagePublishingStatus.PENDING

        if priority is None:
            priority = PackagePublishingPriority.OPTIONAL
        if binpackageformat is None:
            if binarypackagerelease is not None:
                binpackageformat = binarypackagerelease.binpackageformat
            else:
                binpackageformat = BinaryPackageFormat.DEB

        if binarypackagerelease is None:
            # Create a new BinaryPackageBuild and BinaryPackageRelease
            # in the same archive and suite.
            binarypackagebuild = self.makeBinaryPackageBuild(
                archive=archive,
                distroarchseries=distroarchseries,
                pocket=pocket,
                source_package_release=source_package_release,
                sourcepackagename=sourcepackagename,
            )
            binarypackagerelease = self.makeBinaryPackageRelease(
                binarypackagename=binarypackagename,
                version=version,
                build=binarypackagebuild,
                component=component,
                binpackageformat=binpackageformat,
                section_name=section_name,
                priority=priority,
                architecturespecific=architecturespecific,
            )
            if with_file:
                ext = {
                    BinaryPackageFormat.DEB: "deb",
                    BinaryPackageFormat.UDEB: "udeb",
                    BinaryPackageFormat.DDEB: "ddeb",
                }[binarypackagerelease.binpackageformat]
                lfa = self.makeLibraryFileAlias(
                    filename="%s_%s_%s.%s"
                    % (
                        binarypackagerelease.binarypackagename.name,
                        binarypackagerelease.version,
                        binarypackagebuild.distro_arch_series.architecturetag,
                        ext,
                    )
                )
                self.makeBinaryPackageFile(
                    binarypackagerelease=binarypackagerelease, library_file=lfa
                )

        if datecreated is None:
            datecreated = self.getUniqueDate()

        bpphs = getUtility(IPublishingSet).publishBinaries(
            archive,
            distroarchseries.distroseries,
            pocket,
            {
                binarypackagerelease: (
                    binarypackagerelease.component,
                    binarypackagerelease.section,
                    priority,
                    None,
                )
            },
            channel=channel,
        )
        for bpph in bpphs:
            naked_bpph = removeSecurityProxy(bpph)
            naked_bpph.status = status
            naked_bpph.dateremoved = dateremoved
            naked_bpph.datecreated = datecreated
            naked_bpph.scheduleddeletiondate = scheduleddeletiondate
            naked_bpph.priority = priority
            if status == PackagePublishingStatus.PUBLISHED:
                naked_bpph.datepublished = UTC_NOW
        if with_debug:
            debug_bpph = self.makeBinaryPackagePublishingHistory(
                binarypackagename=(
                    binarypackagerelease.binarypackagename.name + "-dbgsym"
                ),
                version=version,
                distroarchseries=distroarchseries,
                component=component,
                section_name=binarypackagerelease.section,
                priority=priority,
                status=status,
                scheduleddeletiondate=scheduleddeletiondate,
                dateremoved=dateremoved,
                datecreated=datecreated,
                pocket=pocket,
                archive=archive,
                source_package_release=source_package_release,
                binpackageformat=BinaryPackageFormat.DDEB,
                sourcepackagename=sourcepackagename,
                architecturespecific=architecturespecific,
                with_file=with_file,
                creator=creator,
            )
            removeSecurityProxy(bpph.binarypackagerelease).debug_package = (
                debug_bpph.binarypackagerelease
            )
            return bpphs[0], debug_bpph
        return bpphs[0]

    def makeSPPHForBPPH(self, bpph):
        """Produce a `SourcePackagePublishingHistory` to match `bpph`.

        :param bpph: A `BinaryPackagePublishingHistory`.
        :return: A `SourcePackagePublishingHistory` stemming from the same
            source package as `bpph`, published into the same distroseries,
            pocket, and archive.
        """
        bpr = bpph.binarypackagerelease
        return self.makeSourcePackagePublishingHistory(
            distroseries=bpph.distroarchseries.distroseries,
            sourcepackagerelease=bpr.build.source_package_release,
            pocket=bpph.pocket,
            archive=bpph.archive,
        )

    def makeBinaryPackageName(self, name=None):
        """Make an `IBinaryPackageName`."""
        if name is None:
            name = self.getUniqueString("binarypackage")
        return getUtility(IBinaryPackageNameSet).new(name)

    def getOrMakeBinaryPackageName(self, name=None):
        """Get an existing `IBinaryPackageName` or make a new one.

        This method encapsulates getOrCreateByName so that tests can be kept
        free of the getUtility(IBinaryPackageNameSet) noise.
        """
        if name is None:
            return self.makeBinaryPackageName()
        return getUtility(IBinaryPackageNameSet).getOrCreateByName(name)

    def makeBinaryPackageFile(
        self, binarypackagerelease=None, library_file=None, filetype=None
    ):
        if binarypackagerelease is None:
            binarypackagerelease = self.makeBinaryPackageRelease()
        if library_file is None:
            library_file = self.makeLibraryFileAlias()
        if filetype is None:
            filetype = BinaryPackageFileType.DEB
        return ProxyFactory(
            BinaryPackageFile(
                binarypackagerelease=binarypackagerelease,
                libraryfile=library_file,
                filetype=filetype,
            )
        )

    def makeBinaryPackageRelease(
        self,
        binarypackagename=None,
        version=None,
        build=None,
        ci_build=None,
        binpackageformat=None,
        component=None,
        section_name=None,
        priority=None,
        architecturespecific=False,
        summary=None,
        description=None,
        shlibdeps=None,
        depends=None,
        recommends=None,
        suggests=None,
        conflicts=None,
        replaces=None,
        provides=None,
        pre_depends=None,
        enhances=None,
        breaks=None,
        essential=False,
        installed_size=None,
        date_created=None,
        debug_package=None,
        homepage=None,
        user_defined_fields=None,
    ):
        """Make a `BinaryPackageRelease`."""
        if build is None and ci_build is None:
            build = self.makeBinaryPackageBuild()
        if binarypackagename is None or isinstance(binarypackagename, str):
            binarypackagename = self.getOrMakeBinaryPackageName(
                binarypackagename
            )
        if version is None and build is not None:
            version = build.source_package_release.version
        if binpackageformat is None:
            binpackageformat = BinaryPackageFormat.DEB
        if component is None and build is not None:
            component = build.source_package_release.component
        elif isinstance(component, str):
            component = getUtility(IComponentSet)[component]
        if isinstance(section_name, str):
            section_name = self.makeSection(section_name)
        if section_name is not None:
            section = section_name
        elif build is not None:
            section = build.source_package_release.section
        else:
            section = None
        if priority is None:
            priority = PackagePublishingPriority.OPTIONAL
        if summary is None:
            summary = self.getUniqueString("summary")
        if description is None:
            description = self.getUniqueString("description")
        if installed_size is None:
            installed_size = self.getUniqueInteger()
        kwargs = {
            "binarypackagename": binarypackagename,
            "version": version,
            "binpackageformat": binpackageformat,
            "summary": summary,
            "description": description,
            "architecturespecific": architecturespecific,
            "installedsize": installed_size,
            "homepage": homepage,
            "user_defined_fields": user_defined_fields,
        }
        if build is not None:
            kwargs.update(
                {
                    "component": component,
                    "section": section,
                    "priority": priority,
                    "shlibdeps": shlibdeps,
                    "depends": depends,
                    "recommends": recommends,
                    "suggests": suggests,
                    "conflicts": conflicts,
                    "replaces": replaces,
                    "provides": provides,
                    "pre_depends": pre_depends,
                    "enhances": enhances,
                    "breaks": breaks,
                    "essential": essential,
                    "debug_package": debug_package,
                }
            )
        bpr = (build or ci_build).createBinaryPackageRelease(**kwargs)
        if date_created is not None:
            removeSecurityProxy(bpr).datecreated = date_created
        return bpr

    def makeSigningKey(
        self,
        key_type=None,
        fingerprint=None,
        public_key=None,
        description=None,
    ):
        """Makes a SigningKey (integration with lp-signing)"""
        if key_type is None:
            key_type = SigningKeyType.UEFI
        if fingerprint is None:
            fingerprint = self.getUniqueUnicode("fingerprint")
        if public_key is None:
            public_key = self.getUniqueHexString(64).encode("ASCII")
        store = IPrimaryStore(SigningKey)
        signing_key = SigningKey(
            key_type=key_type,
            fingerprint=fingerprint,
            public_key=public_key,
            description=description,
        )
        store.add(signing_key)
        return ProxyFactory(signing_key)

    def makeArchiveSigningKey(
        self, archive=None, distro_series=None, signing_key=None
    ):
        if archive is None:
            archive = self.makeArchive()
        if signing_key is None:
            signing_key = self.makeSigningKey()
        return getUtility(IArchiveSigningKeySet).create(
            archive, distro_series, signing_key
        )

    def makeSection(self, name=None):
        """Make a `Section`."""
        if name is None:
            name = self.getUniqueString("section")
        return getUtility(ISectionSet).ensure(name)

    def makePackageset(
        self,
        name=None,
        description=None,
        owner=None,
        packages=(),
        distroseries=None,
        related_set=None,
    ):
        """Make an `IPackageset`."""
        if name is None:
            name = self.getUniqueString("package-set-name")
        if description is None:
            description = self.getUniqueString("package-set-description")
        if owner is None:
            person = self.getUniqueString("package-set-owner")
            owner = self.makePerson(name=person)
        if distroseries is None:
            distroseries = getUtility(IDistributionSet)["ubuntu"].currentseries
        techboard = getUtility(ILaunchpadCelebrities).ubuntu_techboard
        ps_set = getUtility(IPackagesetSet)
        package_set = run_with_login(
            techboard.teamowner,
            lambda: ps_set.new(
                name, description, owner, distroseries, related_set
            ),
        )
        run_with_login(owner, lambda: package_set.add(packages))
        return package_set

    def makeDistroArchSeriesFilter(
        self,
        distroarchseries=None,
        packageset=None,
        sense=DistroArchSeriesFilterSense.INCLUDE,
        creator=None,
        date_created=DEFAULT,
    ):
        """Make a new `DistroArchSeriesFilter`."""
        if distroarchseries is None:
            if packageset is not None:
                distroseries = packageset.distroseries
            else:
                distroseries = None
            distroarchseries = self.makeDistroArchSeries(
                distroseries=distroseries
            )
        if packageset is None:
            packageset = self.makePackageset(
                distroseries=distroarchseries.distroseries
            )
        if creator is None:
            creator = self.makePerson()
        return ProxyFactory(
            DistroArchSeriesFilter(
                distroarchseries=distroarchseries,
                packageset=packageset,
                sense=sense,
                creator=creator,
                date_created=date_created,
            )
        )

    def getAnyPocket(self):
        return ProxyFactory(PackagePublishingPocket.BACKPORTS)

    def makeSuiteSourcePackage(
        self, distroseries=None, sourcepackagename=None, pocket=None
    ):
        if distroseries is None:
            distroseries = self.makeDistroSeries()
        if pocket is None:
            pocket = self.getAnyPocket()
        # Make sure we have a real sourcepackagename object.
        if sourcepackagename is None or isinstance(sourcepackagename, str):
            sourcepackagename = self.getOrMakeSourcePackageName(
                sourcepackagename
            )
        return ProxyFactory(
            SuiteSourcePackage(distroseries, pocket, sourcepackagename)
        )

    def makeDistributionSourcePackage(
        self, sourcepackagename=None, distribution=None, with_db=False
    ):
        # Make sure we have a real sourcepackagename object.
        if sourcepackagename is None or isinstance(sourcepackagename, str):
            sourcepackagename = self.getOrMakeSourcePackageName(
                sourcepackagename
            )
        if distribution is None:
            distribution = self.makeDistribution()
        package = distribution.getSourcePackage(sourcepackagename)
        if with_db:
            # Create an instance with a database record, that is normally
            # done by secondary process.
            naked_package = removeSecurityProxy(package)
            if naked_package._get(distribution, sourcepackagename) is None:
                naked_package._new(distribution, sourcepackagename)
        return package

    def makeDSPCache(
        self,
        distroseries=None,
        sourcepackagename=None,
        official=True,
        binary_names=None,
        archive=None,
    ):
        if distroseries is None:
            distroseries = self.makeDistroSeries()
        dsp = self.makeDistributionSourcePackage(
            distribution=distroseries.distribution,
            sourcepackagename=sourcepackagename,
            with_db=official,
        )
        if archive is None:
            archive = dsp.distribution.main_archive
        if official:
            self.makeSourcePackagePublishingHistory(
                distroseries=distroseries,
                sourcepackagename=dsp.sourcepackagename,
                archive=archive,
            )
        with dbuser("statistician"):
            DistributionSourcePackageCache(
                distribution=dsp.distribution,
                sourcepackagename=dsp.sourcepackagename,
                archive=archive,
                name=dsp.sourcepackagename.name,
                binpkgnames=binary_names,
            )
        return dsp

    def makeEmailMessage(
        self,
        body=None,
        sender=None,
        to=None,
        attachments=None,
        encode_attachments=False,
    ):
        """Make an email message with possible attachments.

        :param attachments: Should be an interable of tuples containing
           (filename, content-type, payload)
        """
        if sender is None:
            sender = self.makePerson()
        if body is None:
            body = self.getUniqueString("body")
        if to is None:
            to = self.getUniqueEmailAddress()

        msg = MIMEMultipart()
        msg["Message-Id"] = make_msgid("launchpad")
        msg["Date"] = formatdate()
        msg["To"] = to
        msg["From"] = removeSecurityProxy(sender).preferredemail.email
        msg["Subject"] = "Sample"

        if attachments is None:
            msg.set_payload(body)
        else:
            msg.attach(MIMEText(body))
            for filename, content_type, payload in attachments:
                attachment = EmailMessage()
                attachment.set_payload(payload)
                attachment["Content-Type"] = content_type
                attachment["Content-Disposition"] = (
                    'attachment; filename="%s"' % filename
                )
                if encode_attachments:
                    encode_base64(attachment)
                msg.attach(attachment)
        return msg

    def makeSSHKeyText(self, key_type="ssh-rsa", comment=None):
        """Create new SSH public key text.

        :param key_type: If specified, the type of SSH key to generate, as a
            public key algorithm name
            (https://www.iana.org/assignments/ssh-parameters/).  Must be a
            member of SSH_TEXT_TO_KEY_TYPE.  If unspecified, "ssh-rsa" is
            used.
        """
        parameters = None
        if key_type == "ssh-rsa":
            parameters = [MP(keydata.RSAData[param]) for param in ("e", "n")]
        elif key_type == "ssh-dss":
            parameters = [
                MP(keydata.DSAData[param]) for param in ("p", "q", "g", "y")
            ]
        elif key_type.startswith("ecdsa-sha2-"):
            curve = key_type[len("ecdsa-sha2-") :]
            key_size, curve_data = {
                "nistp256": (256, keydata.ECDatanistp256),
                "nistp384": (384, keydata.ECDatanistp384),
                "nistp521": (521, keydata.ECDatanistp521),
            }.get(curve, (None, None))
            if curve_data is not None:
                key_byte_length = (key_size + 7) // 8
                parameters = [
                    NS(curve_data["curve"][-8:]),
                    NS(
                        b"\x04"
                        + int_to_bytes(curve_data["x"], key_byte_length)
                        + int_to_bytes(curve_data["y"], key_byte_length)
                    ),
                ]
        elif key_type == "ssh-ed25519":
            parameters = [NS(keydata.Ed25519Data["a"])]
        if parameters is None:
            raise AssertionError(
                "key_type must be a member of SSH_TEXT_TO_KEY_TYPE, not %r"
                % key_type
            )
        key_text = base64.b64encode(
            NS(key_type) + b"".join(parameters)
        ).decode("ASCII")
        if comment is None:
            comment = self.getUniqueString()
        return "%s %s %s" % (key_type, key_text, comment)

    def makeSSHKey(
        self,
        person=None,
        key_type="ssh-rsa",
        send_notification=True,
        comment=None,
    ):
        """Create a new SSHKey.

        :param person: If specified, the person to attach the key to. If
            unspecified, a person is created.
        :param key_type: If specified, the type of SSH key to generate, as a
            public key algorithm name
            (https://www.iana.org/assignments/ssh-parameters/).  Must be a
            member of SSH_TEXT_TO_KEY_TYPE.  If unspecified, "ssh-rsa" is
            used.
        """
        if person is None:
            person = self.makePerson()
        public_key = self.makeSSHKeyText(key_type=key_type, comment=comment)
        return getUtility(ISSHKeySet).new(
            person, public_key, send_notification=send_notification
        )

    def makeBlob(self, blob=None, expires=None, blob_file=None):
        """Create a new TemporaryFileStorage BLOB."""
        if blob_file is not None:
            blob_path = os.path.join(
                config.root, "lib/lp/bugs/tests/testfiles", blob_file
            )
            with open(blob_path, "rb") as blob_file:
                blob = blob_file.read()
        if blob is None:
            blob = self.getUniqueBytes()
        new_uuid = getUtility(ITemporaryStorageManager).new(blob, expires)

        return getUtility(ITemporaryStorageManager).fetch(new_uuid)

    def makeProcessedApportBlob(self, metadata):
        """Create a processed ApportJob with the specified metadata dict.

        It doesn't actually run the job. It fakes it, and uses a fake
        librarian file so as to work without the librarian.
        """
        blob = TemporaryBlobStorage(uuid=str(uuid.uuid1()), file_alias=1)
        job = getUtility(IProcessApportBlobJobSource).create(blob)
        job.job.start()
        removeSecurityProxy(job).metadata = {
            "processed_data": FileBugData(**metadata).asDict()
        }
        job.job.complete()
        return ProxyFactory(blob)

    def makeLaunchpadService(self, person=None, version="devel"):
        if person is None:
            person = self.makePerson()
        from lp.testing.layers import BaseLayer

        launchpad = launchpadlib_for(
            "test",
            person,
            service_root=BaseLayer.appserver_root_url("api"),
            version=version,
        )
        login_person(person)
        return launchpad

    def makePackageDiff(
        self,
        from_source=None,
        to_source=None,
        requester=None,
        status=None,
        date_fulfilled=None,
        diff_content=None,
        diff_filename=None,
    ):
        """Create a new `PackageDiff`."""
        if from_source is None:
            from_source = self.makeSourcePackageRelease()
        if to_source is None:
            to_source = self.makeSourcePackageRelease()
        if requester is None:
            requester = self.makePerson()
        if status is None:
            status = PackageDiffStatus.COMPLETED
        if date_fulfilled is None:
            date_fulfilled = UTC_NOW
        if diff_content is None:
            diff_content = self.getUniqueBytes("packagediff")
        lfa = self.makeLibraryFileAlias(
            filename=diff_filename, content=diff_content
        )
        package_diff = ProxyFactory(
            PackageDiff(
                requester=requester,
                from_source=from_source,
                to_source=to_source,
                date_fulfilled=date_fulfilled,
                status=status,
                diff_content=lfa,
            )
        )
        IStore(package_diff).flush()
        return package_diff

    # Factory methods for OAuth tokens.
    def makeOAuthConsumer(self, key=None, secret=None):
        if key is None:
            key = self.getUniqueUnicode("oauthconsumerkey")
        if secret is None:
            secret = ""
        return getUtility(IOAuthConsumerSet).new(key, secret)

    def makeOAuthRequestToken(
        self,
        consumer=None,
        date_created=None,
        reviewed_by=None,
        access_level=OAuthPermission.READ_PUBLIC,
    ):
        """Create a (possibly reviewed) OAuth request token."""
        if consumer is None:
            consumer = self.makeOAuthConsumer()
        token, _ = consumer.newRequestToken()

        if reviewed_by is not None:
            # Review the token before modifying the date_created,
            # since the date_created can be used to simulate an
            # expired token.
            token.review(reviewed_by, access_level)

        if date_created is not None:
            unwrapped_token = removeSecurityProxy(token)
            unwrapped_token.date_created = date_created
        return token

    def makeOAuthAccessToken(
        self,
        consumer=None,
        owner=None,
        access_level=OAuthPermission.READ_PUBLIC,
    ):
        """Create an OAuth access token."""
        if owner is None:
            owner = self.makePerson()
        request_token = self.makeOAuthRequestToken(
            consumer, reviewed_by=owner, access_level=access_level
        )
        return request_token.createAccessToken()

    def makeAccessToken(
        self,
        secret=None,
        owner=None,
        description=None,
        target=None,
        scopes=None,
        date_expires=None,
    ):
        """Create a personal access token.

        :return: A tuple of the secret for the new token and the token
            itself.
        """
        if secret is None:
            secret = create_access_token_secret()
        if owner is None:
            owner = self.makePerson()
        if description is None:
            description = self.getUniqueUnicode()
        if target is None:
            target = self.makeGitRepository()
        if scopes is None:
            scopes = []
        token = getUtility(IAccessTokenSet).new(
            secret,
            owner,
            description,
            target,
            scopes,
            date_expires=date_expires,
        )
        IStore(token).flush()
        return secret, token

    def makeCVE(
        self,
        sequence,
        description=None,
        cvestate=CveStatus.CANDIDATE,
        date_made_public=None,
        discovered_by=None,
        cvss=None,
    ):
        """Create a new CVE record."""
        if description is None:
            description = self.getUniqueUnicode()

        return getUtility(ICveSet).new(
            sequence,
            description,
            cvestate,
            date_made_public,
            discovered_by,
            cvss,
        )

    def makePublisherConfig(
        self,
        distribution=None,
        root_dir=None,
        base_url=None,
        copy_base_url=None,
    ):
        """Create a new `PublisherConfig` record."""
        if distribution is None:
            distribution = self.makeDistribution()
        if root_dir is None:
            root_dir = self.getUniqueUnicode()
        if base_url is None:
            base_url = self.getUniqueUnicode()
        if copy_base_url is None:
            copy_base_url = self.getUniqueUnicode()
        return getUtility(IPublisherConfigSet).new(
            distribution, root_dir, base_url, copy_base_url
        )

    def makePlainPackageCopyJob(
        self,
        package_name=None,
        package_version=None,
        source_archive=None,
        target_archive=None,
        target_distroseries=None,
        target_pocket=None,
        requester=None,
        include_binaries=False,
    ):
        """Create a new `PlainPackageCopyJob`."""
        if package_name is None and package_version is None:
            package_name = self.makeSourcePackageName().name
            package_version = str(self.getUniqueInteger()) + "version"
        if source_archive is None:
            source_archive = self.makeArchive()
        if target_archive is None:
            target_archive = self.makeArchive()
        if target_distroseries is None:
            target_distroseries = self.makeDistroSeries()
        if target_pocket is None:
            target_pocket = self.getAnyPocket()
        if requester is None:
            requester = self.makePerson()
        return getUtility(IPlainPackageCopyJobSource).create(
            package_name,
            source_archive,
            target_archive,
            target_distroseries,
            target_pocket,
            package_version=package_version,
            requester=requester,
            include_binaries=include_binaries,
        )

    def makeAccessPolicy(
        self,
        pillar=None,
        type=InformationType.PROPRIETARY,
        check_existing=False,
    ):
        if pillar is None:
            pillar = self.makeProduct()
        policy_source = getUtility(IAccessPolicySource)
        if check_existing:
            policy = policy_source.find([(pillar, type)]).one()
            if policy is not None:
                return policy
        policies = policy_source.create([(pillar, type)])
        return policies[0]

    def makeAccessArtifact(self, concrete=None):
        if concrete is None:
            concrete = self.makeBranch()
        artifacts = getUtility(IAccessArtifactSource).ensure([concrete])
        return artifacts[0]

    def makeAccessPolicyArtifact(self, artifact=None, policy=None):
        if artifact is None:
            artifact = self.makeAccessArtifact()
        if policy is None:
            policy = self.makeAccessPolicy()
        [link] = getUtility(IAccessPolicyArtifactSource).create(
            [(artifact, policy)]
        )
        return link

    def makeAccessArtifactGrant(
        self, artifact=None, grantee=None, grantor=None, concrete_artifact=None
    ):
        if artifact is None:
            artifact = self.makeAccessArtifact(concrete_artifact)
        if grantee is None:
            grantee = self.makePerson()
        if grantor is None:
            grantor = self.makePerson()
        [grant] = getUtility(IAccessArtifactGrantSource).grant(
            [(artifact, grantee, grantor)]
        )
        return grant

    def makeAccessPolicyGrant(self, policy=None, grantee=None, grantor=None):
        if policy is None:
            policy = self.makeAccessPolicy()
        if grantee is None:
            grantee = self.makePerson()
        if grantor is None:
            grantor = self.makePerson()
        [grant] = getUtility(IAccessPolicyGrantSource).grant(
            [(policy, grantee, grantor)]
        )
        return grant

    def makeFakeFileUpload(self, filename=None, content=None):
        """Return a zope.publisher.browser.FileUpload like object.

        This can be useful while testing multipart form submission.
        """
        if filename is None:
            filename = self.getUniqueString()
        if content is None:
            content = self.getUniqueBytes()
        fileupload = BytesIO(content)
        fileupload.filename = filename
        fileupload.headers = {
            "Content-Type": "text/plain; charset=utf-8",
            "Content-Disposition": 'attachment; filename="%s"' % filename,
        }
        return fileupload

    def makeCommercialSubscription(
        self, pillar, expired=False, voucher_id="new"
    ):
        """Create a commercial subscription for the given pillar."""
        if IProduct.providedBy(pillar):
            find_kwargs = {"product": pillar}
        elif IDistribution.providedBy(pillar):
            find_kwargs = {"distribution": pillar}
        else:
            raise AssertionError("Unknown pillar: %r" % pillar)
        if (
            IStore(CommercialSubscription)
            .find(CommercialSubscription, **find_kwargs)
            .one()
            is not None
        ):
            raise AssertionError(
                "The pillar under test already has a CommercialSubscription."
            )
        if expired:
            expiry = datetime.now(timezone.utc) - timedelta(days=1)
        else:
            expiry = datetime.now(timezone.utc) + timedelta(days=30)
        commercial_subscription = CommercialSubscription(
            pillar=pillar,
            date_starts=datetime.now(timezone.utc) - timedelta(days=90),
            date_expires=expiry,
            registrant=pillar.owner,
            purchaser=pillar.owner,
            sales_system_id=voucher_id,
            whiteboard="",
        )
        del get_property_cache(pillar).commercial_subscription
        return ProxyFactory(commercial_subscription)

    def grantCommercialSubscription(self, person):
        """Give 'person' a commercial subscription."""
        product = self.makeProduct(owner=person)
        self.makeCommercialSubscription(
            product, voucher_id=self.getUniqueUnicode()
        )

    def makeLiveFS(
        self,
        registrant=None,
        owner=None,
        distroseries=None,
        name=None,
        metadata=None,
        require_virtualized=True,
        keep_binary_files_days=1,
        date_created=DEFAULT,
    ):
        """Make a new LiveFS."""
        if registrant is None:
            registrant = self.makePerson()
        if owner is None:
            owner = self.makeTeam(registrant)
        if distroseries is None:
            distroseries = self.makeDistroSeries()
        if name is None:
            name = self.getUniqueString("livefs-name")
        if metadata is None:
            metadata = {}
        livefs = getUtility(ILiveFSSet).new(
            registrant,
            owner,
            distroseries,
            name,
            metadata,
            require_virtualized=require_virtualized,
            keep_binary_files_days=keep_binary_files_days,
            date_created=date_created,
        )
        IStore(livefs).flush()
        return livefs

    def makeLiveFSBuild(
        self,
        requester=None,
        registrant=None,
        livefs=None,
        archive=None,
        distroarchseries=None,
        pocket=None,
        unique_key=None,
        metadata_override=None,
        version=None,
        date_created=DEFAULT,
        status=BuildStatus.NEEDSBUILD,
        builder=None,
        duration=None,
        **kwargs,
    ):
        """Make a new LiveFSBuild."""
        if requester is None:
            requester = self.makePerson()
        if livefs is None:
            if "distroseries" in kwargs:
                distroseries = kwargs["distroseries"]
                del kwargs["distroseries"]
            elif distroarchseries is not None:
                distroseries = distroarchseries.distroseries
            elif archive is not None:
                distroseries = self.makeDistroSeries(
                    distribution=archive.distribution
                )
            else:
                distroseries = None
            if registrant is None:
                registrant = requester
            livefs = self.makeLiveFS(
                registrant=registrant, distroseries=distroseries, **kwargs
            )
        if archive is None:
            archive = livefs.distro_series.main_archive
        if distroarchseries is None:
            distroarchseries = self.makeDistroArchSeries(
                distroseries=livefs.distro_series
            )
        if pocket is None:
            pocket = PackagePublishingPocket.RELEASE
        livefsbuild = getUtility(ILiveFSBuildSet).new(
            requester,
            livefs,
            archive,
            distroarchseries,
            pocket,
            unique_key=unique_key,
            metadata_override=metadata_override,
            version=version,
            date_created=date_created,
        )
        if duration is not None:
            removeSecurityProxy(livefsbuild).updateStatus(
                BuildStatus.BUILDING,
                builder=builder,
                date_started=livefsbuild.date_created,
            )
            removeSecurityProxy(livefsbuild).updateStatus(
                status,
                builder=builder,
                date_finished=livefsbuild.date_started + duration,
            )
        else:
            removeSecurityProxy(livefsbuild).updateStatus(
                status, builder=builder
            )
        IStore(livefsbuild).flush()
        return livefsbuild

    def makeLiveFSFile(self, livefsbuild=None, libraryfile=None):
        if livefsbuild is None:
            livefsbuild = self.makeLiveFSBuild()
        if libraryfile is None:
            libraryfile = self.makeLibraryFileAlias()
        return ProxyFactory(
            LiveFSFile(livefsbuild=livefsbuild, libraryfile=libraryfile)
        )

    def makeWebhook(
        self,
        target=None,
        delivery_url=None,
        secret=None,
        active=True,
        event_types=None,
        git_ref_pattern=None,
    ):
        if target is None:
            target = self.makeGitRepository()
        if delivery_url is None:
            delivery_url = self.getUniqueURL()
        return getUtility(IWebhookSet).new(
            target,
            self.makePerson(),
            delivery_url,
            event_types or [],
            active,
            secret,
            git_ref_pattern,
        )

    def makeSnap(
        self,
        registrant=None,
        owner=None,
        distroseries=_DEFAULT,
        name=None,
        branch=None,
        git_ref=None,
        auto_build=False,
        auto_build_archive=None,
        auto_build_pocket=None,
        auto_build_channels=None,
        is_stale=None,
        require_virtualized=True,
        processors=None,
        date_created=DEFAULT,
        private=None,
        information_type=None,
        allow_internet=True,
        build_source_tarball=False,
        store_upload=False,
        store_series=None,
        store_name=None,
        store_secrets=None,
        store_channels=None,
        project=_DEFAULT,
        pro_enable=False,
        use_fetch_service=False,
        fetch_service_policy=FetchServicePolicy.STRICT,
    ):
        """Make a new Snap."""
        assert information_type is None or private is None
        if information_type is None:
            # Defaults to public information type, unless "private" flag was
            # passed.
            information_type = (
                InformationType.PUBLIC
                if not private
                else InformationType.PROPRIETARY
            )
        if private is None:
            private = information_type not in PUBLIC_INFORMATION_TYPES
        if registrant is None:
            registrant = self.makePerson()
        if owner is None:
            is_private_snap = (
                private or information_type not in PUBLIC_INFORMATION_TYPES
            )
            # Private snaps cannot be owned by non-moderated teams.
            membership_policy = (
                TeamMembershipPolicy.OPEN
                if not is_private_snap
                else TeamMembershipPolicy.MODERATED
            )
            owner = self.makeTeam(
                registrant, membership_policy=membership_policy
            )
        if distroseries is _DEFAULT:
            distroseries = self.makeDistroSeries()
        if name is None:
            name = self.getUniqueString("snap-name")
        if branch is None and git_ref is None:
            branch = self.makeAnyBranch()
        if auto_build:
            if auto_build_archive is None:
                auto_build_archive = self.makeArchive(
                    distribution=distroseries.distribution, owner=owner
                )
            if auto_build_pocket is None:
                auto_build_pocket = PackagePublishingPocket.UPDATES
        if private and project is _DEFAULT:
            # If we are creating a private snap and didn't explicitly set a
            # pillar for it, we must create a pillar.
            branch_sharing = (
                BranchSharingPolicy.PUBLIC_OR_PROPRIETARY
                if not private
                else BranchSharingPolicy.PROPRIETARY
            )
            project = self.makeProduct(
                owner=registrant,
                registrant=registrant,
                information_type=information_type,
                branch_sharing_policy=branch_sharing,
            )
        if project is _DEFAULT:
            project = None
        snap = getUtility(ISnapSet).new(
            registrant,
            owner,
            distroseries,
            name,
            require_virtualized=require_virtualized,
            processors=processors,
            date_created=date_created,
            branch=branch,
            git_ref=git_ref,
            auto_build=auto_build,
            auto_build_archive=auto_build_archive,
            auto_build_pocket=auto_build_pocket,
            auto_build_channels=auto_build_channels,
            information_type=information_type,
            allow_internet=allow_internet,
            build_source_tarball=build_source_tarball,
            store_upload=store_upload,
            store_series=store_series,
            store_name=store_name,
            store_secrets=store_secrets,
            store_channels=store_channels,
            project=project,
            pro_enable=pro_enable,
            use_fetch_service=use_fetch_service,
            fetch_service_policy=fetch_service_policy,
        )
        if is_stale is not None:
            removeSecurityProxy(snap).is_stale = is_stale
        IStore(snap).flush()
        return snap

    def makeSnapBuildRequest(
        self,
        snap=None,
        requester=None,
        archive=None,
        pocket=PackagePublishingPocket.UPDATES,
        channels=None,
    ):
        """Make a new SnapBuildRequest."""
        if snap is None:
            snap = self.makeSnap()
        if requester is None:
            requester = snap.owner.teamowner
        if archive is None:
            archive = snap.distro_series.main_archive
        return snap.requestBuilds(
            requester, archive, pocket, channels=channels
        )

    def makeSnapBuild(
        self,
        requester=None,
        registrant=None,
        snap=None,
        archive=None,
        distroarchseries=None,
        pocket=None,
        snap_base=None,
        channels=None,
        date_created=DEFAULT,
        build_request=None,
        status=BuildStatus.NEEDSBUILD,
        builder=None,
        duration=None,
        target_architectures=None,
        **kwargs,
    ):
        """Make a new SnapBuild."""
        if requester is None:
            requester = self.makePerson()
        if snap is None:
            if "distroseries" in kwargs:
                distroseries = kwargs["distroseries"]
                del kwargs["distroseries"]
            elif distroarchseries is not None:
                distroseries = distroarchseries.distroseries
            elif archive is not None:
                distroseries = self.makeDistroSeries(
                    distribution=archive.distribution
                )
            else:
                distroseries = _DEFAULT
            if registrant is None:
                registrant = requester
            snap = self.makeSnap(
                registrant=registrant, distroseries=distroseries, **kwargs
            )
        if archive is None:
            archive = snap.distro_series.main_archive
        if distroarchseries is None:
            distroarchseries = self.makeDistroArchSeries(
                distroseries=snap.distro_series
            )
        if pocket is None:
            pocket = PackagePublishingPocket.UPDATES
        snapbuild = getUtility(ISnapBuildSet).new(
            requester,
            snap,
            archive,
            distroarchseries,
            pocket,
            snap_base=snap_base,
            channels=channels,
            date_created=date_created,
            build_request=build_request,
            target_architectures=target_architectures,
        )
        if duration is not None:
            removeSecurityProxy(snapbuild).updateStatus(
                BuildStatus.BUILDING,
                builder=builder,
                date_started=snapbuild.date_created,
            )
            removeSecurityProxy(snapbuild).updateStatus(
                status,
                builder=builder,
                date_finished=snapbuild.date_started + duration,
            )
        else:
            removeSecurityProxy(snapbuild).updateStatus(
                status, builder=builder
            )
        IStore(snapbuild).flush()
        return snapbuild

    def makeSnapFile(self, snapbuild=None, libraryfile=None):
        if snapbuild is None:
            snapbuild = self.makeSnapBuild()
        if libraryfile is None:
            libraryfile = self.makeLibraryFileAlias()
        return ProxyFactory(
            SnapFile(snapbuild=snapbuild, libraryfile=libraryfile)
        )

    def makeSnappySeries(
        self,
        registrant=None,
        name=None,
        display_name=None,
        status=SeriesStatus.DEVELOPMENT,
        preferred_distro_series=None,
        date_created=DEFAULT,
        usable_distro_series=None,
        can_infer_distro_series=False,
    ):
        """Make a new SnappySeries."""
        if registrant is None:
            registrant = self.makePerson()
        if name is None:
            name = self.getUniqueString("snappy-series-name")
        if display_name is None:
            display_name = SPACE.join(
                word.capitalize() for word in name.split("-")
            )
        snappy_series = getUtility(ISnappySeriesSet).new(
            registrant,
            name,
            display_name,
            status,
            preferred_distro_series=preferred_distro_series,
            date_created=date_created,
        )
        if usable_distro_series is not None:
            snappy_series.usable_distro_series = usable_distro_series
        elif preferred_distro_series is not None:
            snappy_series.usable_distro_series = [preferred_distro_series]
        if can_infer_distro_series:
            snappy_series.can_infer_distro_series = True
        IStore(snappy_series).flush()
        return snappy_series

    def makeSnapBase(
        self,
        registrant=None,
        name=None,
        display_name=None,
        distro_series=None,
        build_channels=None,
        features=None,
        processors=None,
        date_created=DEFAULT,
    ):
        """Make a new SnapBase."""
        if registrant is None:
            registrant = self.makePerson()
        if name is None:
            name = self.getUniqueString("snap-base-name")
        if display_name is None:
            display_name = SPACE.join(
                word.capitalize() for word in name.split("-")
            )
        if distro_series is None:
            distro_series = self.makeDistroSeries()
        if build_channels is None:
            build_channels = {"snapcraft": "stable"}
        return getUtility(ISnapBaseSet).new(
            registrant,
            name,
            display_name,
            distro_series,
            build_channels,
            features=features,
            processors=processors,
            date_created=date_created,
        )

    def makeOCIProjectName(self, name=None):
        if name is None:
            name = self.getUniqueString("oci-project-name")
        return getUtility(IOCIProjectNameSet).getOrCreateByName(name)

    def makeOCIProject(
        self,
        registrant=None,
        pillar=None,
        ociprojectname=None,
        date_created=DEFAULT,
        description=None,
        bug_reporting_guidelines=None,
        content_templates=None,
        bug_reported_acknowledgement=None,
        bugfiling_duplicate_search=False,
    ):
        """Make a new OCIProject."""
        if registrant is None:
            registrant = self.makePerson()
        if pillar is None:
            pillar = self.makeDistribution()
        if ociprojectname is None or isinstance(ociprojectname, str):
            ociprojectname = self.makeOCIProjectName(ociprojectname)
        return getUtility(IOCIProjectSet).new(
            registrant,
            pillar,
            ociprojectname,
            date_created=date_created,
            description=description,
            bug_reporting_guidelines=bug_reporting_guidelines,
            content_templates=content_templates,
            bug_reported_acknowledgement=bug_reported_acknowledgement,
            bugfiling_duplicate_search=bugfiling_duplicate_search,
        )

    def makeOCIProjectSeries(
        self,
        name=None,
        summary=None,
        registrant=None,
        oci_project=None,
        **kwargs,
    ):
        """Make a new OCIProjectSeries attached to an OCIProject."""
        if name is None:
            name = self.getUniqueString("oci-project-series-name")
        if summary is None:
            summary = self.getUniqueString("oci-project-series-summary")
        if registrant is None:
            registrant = self.makePerson()
        if oci_project is None:
            oci_project = self.makeOCIProject(**kwargs)
        return ProxyFactory(oci_project.newSeries(name, summary, registrant))

    def makeOCIRecipe(
        self,
        name=None,
        registrant=None,
        owner=None,
        oci_project=None,
        git_ref=None,
        description=None,
        official=False,
        require_virtualized=True,
        build_file=None,
        date_created=DEFAULT,
        allow_internet=True,
        build_args=None,
        build_path=None,
        information_type=InformationType.PUBLIC,
    ):
        """Make a new OCIRecipe."""
        if name is None:
            name = self.getUniqueString("oci-recipe-name")
        if registrant is None:
            registrant = self.makePerson()
        if description is None:
            description = self.getUniqueString("oci-recipe-description")
        if owner is None:
            owner = self.makeTeam(members=[registrant])
        if oci_project is None:
            oci_project = self.makeOCIProject()
        if git_ref is None:
            component = self.getUniqueUnicode()
            paths = [f"refs/heads/{component}-20.04"]
            [git_ref] = self.makeGitRefs(paths=paths)
        if build_file is None:
            build_file = self.getUniqueUnicode("build_file_for")
        if build_path is None:
            build_path = self.getUniqueUnicode("build_path_for")
        return getUtility(IOCIRecipeSet).new(
            name=name,
            registrant=registrant,
            owner=owner,
            oci_project=oci_project,
            git_ref=git_ref,
            build_file=build_file,
            build_path=build_path,
            description=description,
            official=official,
            require_virtualized=require_virtualized,
            date_created=date_created,
            allow_internet=allow_internet,
            build_args=build_args,
            information_type=information_type,
        )

    def makeOCIRecipeBuild(
        self,
        requester=None,
        registrant=None,
        recipe=None,
        distro_arch_series=None,
        date_created=DEFAULT,
        status=BuildStatus.NEEDSBUILD,
        builder=None,
        duration=None,
        build_request=None,
        **kwargs,
    ):
        """Make a new OCIRecipeBuild."""
        if requester is None:
            requester = self.makePerson()
        if distro_arch_series is None:
            if recipe is not None:
                distribution = recipe.oci_project.distribution
            else:
                distribution = None
            distroseries = self.makeDistroSeries(
                distribution=distribution, status=SeriesStatus.CURRENT
            )
            processor = getUtility(IProcessorSet).getByName("386")
            distro_arch_series = self.makeDistroArchSeries(
                distroseries=distroseries,
                architecturetag="i386",
                processor=processor,
            )
        if recipe is None:
            oci_project = self.makeOCIProject(
                pillar=distro_arch_series.distroseries.distribution
            )
            if registrant is None:
                registrant = requester
            recipe = self.makeOCIRecipe(
                registrant=registrant, oci_project=oci_project, **kwargs
            )
        oci_build = getUtility(IOCIRecipeBuildSet).new(
            requester, recipe, distro_arch_series, date_created, build_request
        )
        if duration is not None:
            removeSecurityProxy(oci_build).updateStatus(
                BuildStatus.BUILDING,
                builder=builder,
                date_started=oci_build.date_created,
            )
            removeSecurityProxy(oci_build).updateStatus(
                status,
                builder=builder,
                date_finished=oci_build.date_started + duration,
            )
        else:
            removeSecurityProxy(oci_build).updateStatus(
                status, builder=builder
            )
        IStore(oci_build).flush()
        return oci_build

    def makeOCIFile(
        self,
        build=None,
        library_file=None,
        layer_file_digest=None,
        content=None,
        filename=None,
    ):
        """Make a new OCIFile."""
        if build is None:
            build = self.makeOCIRecipeBuild()
        if library_file is None:
            library_file = self.makeLibraryFileAlias(
                content=content, filename=filename
            )
        return ProxyFactory(
            OCIFile(
                build=build,
                library_file=library_file,
                layer_file_digest=layer_file_digest,
            )
        )

    def makeOCIRecipeBuildJob(self, build=None):
        store = IStore(OCIRecipeBuildJob)
        if build is None:
            build = self.makeOCIRecipeBuild()
        job = OCIRecipeBuildJob(
            build, OCIRecipeBuildJobType.REGISTRY_UPLOAD, {}
        )
        store.add(job)
        return ProxyFactory(job)

    def makeOCIRegistryCredentials(
        self, registrant=None, owner=None, url=None, credentials=None
    ):
        """Make a new OCIRegistryCredentials."""
        if registrant is None:
            registrant = self.makePerson()
        if owner is None:
            owner = self.makeTeam(registrant)
        if url is None:
            url = self.getUniqueURL()
        if credentials is None:
            credentials = {
                "username": self.getUniqueUnicode(),
                "password": self.getUniqueUnicode(),
            }
        return getUtility(IOCIRegistryCredentialsSet).new(
            registrant=registrant,
            owner=owner,
            url=url,
            credentials=credentials,
        )

    def makeOCIPushRule(
        self, recipe=None, registry_credentials=None, image_name=None
    ):
        """Make a new OCIPushRule."""
        if recipe is None:
            recipe = self.makeOCIRecipe()
        if registry_credentials is None:
            registry_credentials = self.makeOCIRegistryCredentials()
        if image_name is None:
            image_name = self.getUniqueUnicode("oci-image-name")
        return getUtility(IOCIPushRuleSet).new(
            recipe=recipe,
            registry_credentials=registry_credentials,
            image_name=image_name,
        )

    def makeCharmRecipe(
        self,
        registrant=None,
        owner=None,
        project=None,
        name=None,
        description=None,
        git_ref=None,
        build_path=None,
        require_virtualized=True,
        information_type=InformationType.PUBLIC,
        auto_build=False,
        auto_build_channels=None,
        is_stale=None,
        store_upload=False,
        store_name=None,
        store_secrets=None,
        store_channels=None,
        date_created=DEFAULT,
    ):
        """Make a new charm recipe."""
        if registrant is None:
            registrant = self.makePerson()
        private = information_type not in PUBLIC_INFORMATION_TYPES
        if owner is None:
            # Private charm recipes cannot be owned by non-moderated teams.
            membership_policy = (
                TeamMembershipPolicy.OPEN
                if private
                else TeamMembershipPolicy.MODERATED
            )
            owner = self.makeTeam(
                registrant, membership_policy=membership_policy
            )
        if project is None:
            branch_sharing_policy = (
                BranchSharingPolicy.PUBLIC
                if not private
                else BranchSharingPolicy.PROPRIETARY
            )
            project = self.makeProduct(
                owner=registrant,
                registrant=registrant,
                information_type=information_type,
                branch_sharing_policy=branch_sharing_policy,
            )
        if name is None:
            name = self.getUniqueUnicode("charm-name")
        if git_ref is None:
            git_ref = self.makeGitRefs()[0]
        recipe = getUtility(ICharmRecipeSet).new(
            registrant=registrant,
            owner=owner,
            project=project,
            name=name,
            description=description,
            git_ref=git_ref,
            build_path=build_path,
            require_virtualized=require_virtualized,
            information_type=information_type,
            auto_build=auto_build,
            auto_build_channels=auto_build_channels,
            store_upload=store_upload,
            store_name=store_name,
            store_secrets=store_secrets,
            store_channels=store_channels,
            date_created=date_created,
        )
        if is_stale is not None:
            removeSecurityProxy(recipe).is_stale = is_stale
        IStore(recipe).flush()
        return recipe

    def makeCharmRecipeBuildRequest(
        self, recipe=None, requester=None, channels=None, architectures=None
    ):
        """Make a new CharmRecipeBuildRequest."""
        if recipe is None:
            recipe = self.makeCharmRecipe()
        if requester is None:
            if recipe.owner.is_team:
                requester = recipe.owner.teamowner
            else:
                requester = recipe.owner
        return recipe.requestBuilds(
            requester, channels=channels, architectures=architectures
        )

    def makeCharmRecipeBuild(
        self,
        registrant=None,
        recipe=None,
        build_request=None,
        requester=None,
        distro_arch_series=None,
        channels=None,
        store_upload_metadata=None,
        date_created=DEFAULT,
        status=BuildStatus.NEEDSBUILD,
        builder=None,
        duration=None,
        **kwargs,
    ):
        if recipe is None:
            if registrant is None:
                if build_request is not None:
                    registrant = build_request.requester
                else:
                    registrant = requester
            recipe = self.makeCharmRecipe(registrant=registrant, **kwargs)
        if distro_arch_series is None:
            distro_arch_series = self.makeDistroArchSeries()
        if build_request is None:
            build_request = self.makeCharmRecipeBuildRequest(
                recipe=recipe, requester=requester, channels=channels
            )
        build = getUtility(ICharmRecipeBuildSet).new(
            build_request,
            recipe,
            distro_arch_series,
            channels=channels,
            store_upload_metadata=store_upload_metadata,
            date_created=date_created,
        )
        if duration is not None:
            removeSecurityProxy(build).updateStatus(
                BuildStatus.BUILDING,
                builder=builder,
                date_started=build.date_created,
            )
            removeSecurityProxy(build).updateStatus(
                status,
                builder=builder,
                date_finished=build.date_started + duration,
            )
        else:
            removeSecurityProxy(build).updateStatus(status, builder=builder)
        IStore(build).flush()
        return build

    def makeCharmFile(self, build=None, library_file=None):
        if build is None:
            build = self.makeCharmRecipeBuild()
        if library_file is None:
            library_file = self.makeLibraryFileAlias()
        return ProxyFactory(CharmFile(build=build, library_file=library_file))

    def makeCharmBase(
        self,
        registrant=None,
        distro_series=None,
        build_snap_channels=None,
        processors=None,
        date_created=DEFAULT,
    ):
        """Make a new CharmBase."""
        if registrant is None:
            registrant = self.makePerson()
        if distro_series is None:
            distro_series = self.makeDistroSeries()
        if build_snap_channels is None:
            build_snap_channels = {"charmcraft": "stable"}
        return getUtility(ICharmBaseSet).new(
            registrant,
            distro_series,
            build_snap_channels,
            processors=processors,
            date_created=date_created,
        )

    def makeCraftRecipe(
        self,
        registrant=None,
        owner=None,
        project=None,
        name=None,
        description=None,
        git_ref=None,
        build_path=None,
        require_virtualized=True,
        information_type=InformationType.PUBLIC,
        auto_build=False,
        auto_build_channels=None,
        is_stale=None,
        store_upload=False,
        store_name=None,
        store_secrets=None,
        store_channels=None,
        date_created=DEFAULT,
        use_fetch_service=False,
        fetch_service_policy=FetchServicePolicy.STRICT,
    ):
        """Make a new craft recipe."""
        if registrant is None:
            registrant = self.makePerson()
        private = information_type not in PUBLIC_INFORMATION_TYPES
        if owner is None:
            # Private craft recipes cannot be owned by non-moderated teams.
            membership_policy = (
                TeamMembershipPolicy.OPEN
                if private
                else TeamMembershipPolicy.MODERATED
            )
            owner = self.makeTeam(
                registrant, membership_policy=membership_policy
            )
        if project is None:
            branch_sharing_policy = (
                BranchSharingPolicy.PUBLIC
                if not private
                else BranchSharingPolicy.PROPRIETARY
            )
            project = self.makeProduct(
                owner=registrant,
                registrant=registrant,
                information_type=information_type,
                branch_sharing_policy=branch_sharing_policy,
            )
        if name is None:
            name = self.getUniqueUnicode("craft-name")
        if git_ref is None:
            git_ref = self.makeGitRefs()[0]
        recipe = getUtility(ICraftRecipeSet).new(
            registrant=registrant,
            owner=owner,
            project=project,
            name=name,
            description=description,
            git_ref=git_ref,
            build_path=build_path,
            require_virtualized=require_virtualized,
            information_type=information_type,
            auto_build=auto_build,
            auto_build_channels=auto_build_channels,
            store_upload=store_upload,
            store_name=store_name,
            store_secrets=store_secrets,
            store_channels=store_channels,
            date_created=date_created,
            use_fetch_service=use_fetch_service,
            fetch_service_policy=fetch_service_policy,
        )
        if is_stale is not None:
            removeSecurityProxy(recipe).is_stale = is_stale
        IStore(recipe).flush()
        return recipe

    def makeCraftRecipeBuildRequest(
        self, recipe=None, requester=None, channels=None, architectures=None
    ):
        """Make a new CraftRecipeBuildRequest."""
        if recipe is None:
            recipe = self.makeCraftRecipe()
        if requester is None:
            requester = recipe.owner.teamowner
        if recipe.owner.is_team:
            requester = recipe.owner.teamowner
        else:
            requester = recipe.owner
        return recipe.requestBuilds(
            requester, channels=channels, architectures=architectures
        )

    def makeCraftRecipeBuild(
        self,
        registrant=None,
        recipe=None,
        build_request=None,
        requester=None,
        distro_arch_series=None,
        channels=None,
        store_upload_metadata=None,
        date_created=DEFAULT,
        status=BuildStatus.NEEDSBUILD,
        builder=None,
        duration=None,
        **kwargs,
    ):
        if recipe is None:
            if registrant is None:
                if build_request is not None:
                    registrant = build_request.requester
                else:
                    registrant = requester
            recipe = self.makeCraftRecipe(registrant=registrant, **kwargs)
        if distro_arch_series is None:
            distro_arch_series = self.makeDistroArchSeries()
        if build_request is None:
            build_request = self.makeCraftRecipeBuildRequest(
                recipe=recipe, requester=requester, channels=channels
            )
        build = getUtility(ICraftRecipeBuildSet).new(
            build_request,
            recipe,
            distro_arch_series,
            channels=channels,
            store_upload_metadata=store_upload_metadata,
            date_created=date_created,
        )
        if duration is not None:
            removeSecurityProxy(build).updateStatus(
                BuildStatus.BUILDING,
                builder=builder,
                date_started=build.date_created,
            )
            removeSecurityProxy(build).updateStatus(
                status,
                builder=builder,
                date_finished=build.date_started + duration,
            )
        else:
            removeSecurityProxy(build).updateStatus(status, builder=builder)
        IStore(build).flush()
        return build

    def makeCraftFile(self, build=None, library_file=None):
        if build is None:
            build = self.makeCraftRecipeBuild()
        if library_file is None:
            library_file = self.makeLibraryFileAlias()
        return ProxyFactory(CraftFile(build=build, library_file=library_file))

    def makeRockRecipe(
        self,
        registrant=None,
        owner=None,
        project=None,
        name=None,
        description=None,
        git_ref=None,
        build_path=None,
        require_virtualized=True,
        information_type=InformationType.PUBLIC,
        auto_build=False,
        auto_build_channels=None,
        is_stale=None,
        store_upload=False,
        store_name=None,
        store_secrets=None,
        store_channels=None,
        date_created=DEFAULT,
        use_fetch_service=False,
        fetch_service_policy=FetchServicePolicy.STRICT,
    ):
        """Make a new rock recipe."""
        if registrant is None:
            registrant = self.makePerson()
        private = information_type not in PUBLIC_INFORMATION_TYPES
        if owner is None:
            # Private rock recipes cannot be owned by non-moderated teams.
            membership_policy = (
                TeamMembershipPolicy.OPEN
                if private
                else TeamMembershipPolicy.MODERATED
            )
            owner = self.makeTeam(
                registrant, membership_policy=membership_policy
            )
        if project is None:
            branch_sharing_policy = (
                BranchSharingPolicy.PUBLIC
                if not private
                else BranchSharingPolicy.PROPRIETARY
            )
            project = self.makeProduct(
                owner=registrant,
                registrant=registrant,
                information_type=information_type,
                branch_sharing_policy=branch_sharing_policy,
            )
        if name is None:
            name = self.getUniqueUnicode("rock-name")
        if git_ref is None:
            git_ref = self.makeGitRefs()[0]
        recipe = getUtility(IRockRecipeSet).new(
            registrant=registrant,
            owner=owner,
            project=project,
            name=name,
            description=description,
            git_ref=git_ref,
            build_path=build_path,
            require_virtualized=require_virtualized,
            information_type=information_type,
            auto_build=auto_build,
            auto_build_channels=auto_build_channels,
            store_upload=store_upload,
            store_name=store_name,
            store_secrets=store_secrets,
            store_channels=store_channels,
            date_created=date_created,
            use_fetch_service=use_fetch_service,
            fetch_service_policy=fetch_service_policy,
        )
        if is_stale is not None:
            removeSecurityProxy(recipe).is_stale = is_stale
        IStore(recipe).flush()
        return recipe

    def makeRockRecipeBuildRequest(
        self, recipe=None, requester=None, channels=None, architectures=None
    ):
        """Make a new RockRecipeBuildRequest."""
        if recipe is None:
            recipe = self.makeRockRecipe()
        if requester is None:
            requester = recipe.owner.teamowner
        if recipe.owner.is_team:
            requester = recipe.owner.teamowner
        else:
            requester = recipe.owner
        return recipe.requestBuilds(
            requester, channels=channels, architectures=architectures
        )

    def makeRockRecipeBuild(
        self,
        registrant=None,
        recipe=None,
        build_request=None,
        requester=None,
        distro_arch_series=None,
        channels=None,
        store_upload_metadata=None,
        date_created=DEFAULT,
        status=BuildStatus.NEEDSBUILD,
        builder=None,
        duration=None,
        **kwargs,
    ):
        if recipe is None:
            if registrant is None:
                if build_request is not None:
                    registrant = build_request.requester
                else:
                    registrant = requester
            recipe = self.makeRockRecipe(registrant=registrant, **kwargs)
        if distro_arch_series is None:
            distro_arch_series = self.makeDistroArchSeries()
        if build_request is None:
            build_request = self.makeRockRecipeBuildRequest(
                recipe=recipe, requester=requester, channels=channels
            )
        build = getUtility(IRockRecipeBuildSet).new(
            build_request,
            recipe,
            distro_arch_series,
            channels=channels,
            store_upload_metadata=store_upload_metadata,
            date_created=date_created,
        )
        if duration is not None:
            removeSecurityProxy(build).updateStatus(
                BuildStatus.BUILDING,
                builder=builder,
                date_started=build.date_created,
            )
            removeSecurityProxy(build).updateStatus(
                status,
                builder=builder,
                date_finished=build.date_started + duration,
            )
        else:
            removeSecurityProxy(build).updateStatus(status, builder=builder)
        IStore(build).flush()
        return build

    def makeRockFile(self, build=None, library_file=None):
        if build is None:
            build = self.makeRockRecipeBuild()
        if library_file is None:
            library_file = self.makeLibraryFileAlias()
        return ProxyFactory(RockFile(build=build, library_file=library_file))

    def makeRockBase(
        self,
        registrant=None,
        distro_series=None,
        build_channels=None,
        processors=None,
        date_created=DEFAULT,
    ):
        """Make a new RockBase."""
        if registrant is None:
            registrant = self.makePerson()
        if distro_series is None:
            distro_series = self.makeDistroSeries()
        if build_channels is None:
            build_channels = {"rockcraft": "stable"}
        return getUtility(IRockBaseSet).new(
            registrant,
            distro_series,
            build_channels,
            processors=processors,
            date_created=date_created,
        )

    def makeCIBuild(
        self,
        git_repository=None,
        commit_sha1=None,
        distro_arch_series=None,
        stages=None,
        date_created=DEFAULT,
        status=BuildStatus.NEEDSBUILD,
        builder=None,
        duration=None,
        git_refs=None,
    ):
        """Make a new `CIBuild`."""
        if git_repository is None:
            git_repository = self.makeGitRepository()
        if commit_sha1 is None:
            commit_sha1 = hashlib.sha1(self.getUniqueBytes()).hexdigest()
        if distro_arch_series is None:
            distro_arch_series = self.makeDistroArchSeries()
        if stages is None:
            stages = [[("test", 0)]]
        build = getUtility(ICIBuildSet).new(
            git_repository,
            commit_sha1,
            distro_arch_series,
            stages,
            date_created=date_created,
            git_refs=git_refs,
        )
        if duration is not None:
            removeSecurityProxy(build).updateStatus(
                BuildStatus.BUILDING,
                builder=builder,
                date_started=build.date_created,
            )
            removeSecurityProxy(build).updateStatus(
                status,
                builder=builder,
                date_finished=build.date_started + duration,
            )
        else:
            removeSecurityProxy(build).updateStatus(status, builder=builder)
        IStore(build).flush()
        return build

    def makeVulnerability(
        self,
        distribution=None,
        status=None,
        importance=None,
        creator=None,
        information_type=InformationType.PUBLIC,
        cve=None,
        description=None,
        notes=None,
        mitigation=None,
        importance_explanation=None,
        date_made_public=None,
    ):
        """Make a new `Vulnerability`."""
        if distribution is None:
            distribution = self.makeDistribution()
        if status is None:
            status = VulnerabilityStatus.NEEDS_TRIAGE
        if importance is None:
            importance = BugTaskImportance.UNDECIDED
        if creator is None:
            creator = self.makePerson()
        if importance_explanation is None:
            importance_explanation = self.getUniqueString(
                "vulnerability-importance-explanation"
            )
        return getUtility(IVulnerabilitySet).new(
            distribution=distribution,
            cve=cve,
            status=status,
            importance=importance,
            creator=creator,
            information_type=information_type,
            description=description,
            notes=notes,
            mitigation=mitigation,
            importance_explanation=importance_explanation,
            date_made_public=date_made_public,
        )

    def makeVulnerabilityActivity(
        self,
        vulnerability=None,
        changer=None,
        what_changed=None,
        old_value=None,
        new_value=None,
    ):
        """Make a new `VulnerabilityActivity`."""
        if vulnerability is None:
            vulnerability = self.makeVulnerability()
        if changer is None:
            changer = self.makePerson()
        if what_changed is None:
            what_changed = VulnerabilityChange.DESCRIPTION
        if old_value is None:
            old_value = self.getUniqueString("old-value")
        if new_value is None:
            new_value = self.getUniqueString("new-value")
        return getUtility(IVulnerabilityActivitySet).new(
            vulnerability=vulnerability,
            changer=changer,
            what_changed=what_changed,
            old_value=old_value,
            new_value=new_value,
        )


# Some factory methods return simple Python types. We don't add security
# wrappers for them, or for objects created by other Python libraries.
unwrapped_types = frozenset(
    {
        BaseRecipeBranch,
        BytesIO,
        BzrRevision,
        DSCFile,
        Launchpad,
        Message,
        MIMEMultipart,
        SignedMessage,
        datetime,
        int,
        str,
    }
)


def is_security_proxied_or_harmless(obj):
    """Check that the object is security wrapped or a harmless object."""
    if obj is None:
        return True
    if isinstance(obj, Proxy):
        return True
    if type(obj) in unwrapped_types:
        return True
    if isinstance(obj, (Sequence, set, frozenset)):
        return all(is_security_proxied_or_harmless(element) for element in obj)
    if isinstance(obj, Mapping):
        return all(
            (
                is_security_proxied_or_harmless(key)
                and is_security_proxied_or_harmless(obj[key])
            )
            for key in obj
        )
    return False


class UnproxiedFactoryMethodError(Exception):
    """Raised when someone calls an unproxied factory method."""

    def __init__(self, method_name):
        super().__init__(
            "LaunchpadObjectFactory.%s returns an unproxied object."
            % (method_name,)
        )


class ShouldThisBeUsingRemoveSecurityProxy(UserWarning):
    """Raised when there is a potentially bad call to removeSecurityProxy."""

    def __init__(self, obj):
        message = (
            "removeSecurityProxy(%r) called. Is this correct? "
            "Either call it directly or fix the test." % obj
        )
        super().__init__(message)


def remove_security_proxy_and_shout_at_engineer(obj):
    """Remove an object's security proxy and print a warning.

    A number of LaunchpadObjectFactory methods returned objects without
    a security proxy. This is now no longer possible, but a number of
    tests rely on unrestricted access to object attributes.

    This function should only be used in legacy tests which fail because
    they expect unproxied objects.
    """
    if os.environ.get("LP_PROXY_WARNINGS") == "1":
        warnings.warn(ShouldThisBeUsingRemoveSecurityProxy(obj), stacklevel=2)
    return removeSecurityProxy(obj)
