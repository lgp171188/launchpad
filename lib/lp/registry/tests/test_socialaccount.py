from zope.component import getUtility
from zope.interface.verify import verifyObject

from lp.registry.interfaces.role import IHasOwner
from lp.registry.interfaces.socialaccount import (
    ISocialAccount,
    ISocialAccountSet,
    SocialAccountIdentityError,
    SocialPlatformType,
)
from lp.testing import TestCaseWithFactory, login_person
from lp.testing.layers import DatabaseFunctionalLayer


class TestSocialAccount(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_social_account(self):
        # Social Account is created as expected and
        # associated to the user.
        user = self.factory.makePerson()
        login_person(user)
        attributes = {}
        attributes["homeserver"] = "abc.org"
        attributes["username"] = "test-nickname"
        social_account = getUtility(ISocialAccountSet).new(
            user, SocialPlatformType.MATRIX, attributes
        )

        self.assertTrue(verifyObject(IHasOwner, social_account))
        self.assertTrue(verifyObject(ISocialAccount, social_account))

    def test_matrix_account(self):
        # Matrix Social Account is created as expected and
        # associated to the user.
        user = self.factory.makePerson()
        attributes = {}
        attributes["homeserver"] = "abc.org"
        attributes["username"] = "test-nickname"
        social_account = getUtility(ISocialAccountSet).new(
            user, SocialPlatformType.MATRIX, attributes
        )

        self.assertEqual(len(user.social_accounts), 1)
        social_account = user.social_accounts[0]

        self.assertEqual(social_account.platform, SocialPlatformType.MATRIX)
        self.assertEqual(social_account.identity["homeserver"], "abc.org")
        self.assertEqual(social_account.identity["username"], "test-nickname")

    def test_multilevel_domain_matrix_account(self):
        # Homeserver with a multi-level domain is allowed
        # Matrix username can contain a-z, 0-9, ., _, =, -, and /
        # ref: https://spec.matrix.org/v1.1/appendices/#user-identifiers
        user = self.factory.makePerson()
        attributes = {}
        attributes["homeserver"] = "abc-def.org-com"
        attributes["username"] = "test-n/ic.kn=am_e"
        social_account = getUtility(ISocialAccountSet).new(
            user, SocialPlatformType.MATRIX, attributes
        )

        self.assertEqual(len(user.social_accounts), 1)
        social_account = user.social_accounts[0]

        self.assertEqual(social_account.platform, SocialPlatformType.MATRIX)
        self.assertEqual(
            social_account.identity["homeserver"], "abc-def.org-com"
        )
        self.assertEqual(
            social_account.identity["username"], "test-n/ic.kn=am_e"
        )

    def test_malformed_identity_matrix_account(self):
        # Matrix Identity must contain homeserver and username
        user = self.factory.makePerson()
        attributes = {}
        attributes["homeserver"] = "abc.org"
        attributes["name"] = "test-nickname"
        utility = getUtility(ISocialAccountSet)

        self.assertRaises(
            SocialAccountIdentityError,
            utility.new,
            user,
            SocialPlatformType.MATRIX,
            attributes,
        )

    def test_malformed_username_matrix_account(self):
        # Username can contain a-z, 0-9, ., _, =, -, and /
        user = self.factory.makePerson()
        attributes = {}
        attributes["homeserver"] = "abc.org"
        attributes["username"] = r"<b>test-nickname<\b>"
        utility = getUtility(ISocialAccountSet)

        self.assertRaises(
            SocialAccountIdentityError,
            utility.new,
            user,
            SocialPlatformType.MATRIX,
            attributes,
        )

    def test_malformed_multilevel_domain_matrix_account(self):
        # Homeserver cannot start with a special character
        user = self.factory.makePerson()
        attributes = {}
        attributes["homeserver"] = "-def.org-com"
        attributes["username"] = "test-nickname"
        utility = getUtility(ISocialAccountSet)

        self.assertRaises(
            SocialAccountIdentityError,
            utility.new,
            user,
            SocialPlatformType.MATRIX,
            attributes,
        )

        attributes = {}
        attributes["homeserver"] = "def.-org-com"
        attributes["username"] = "test-nickname"

        self.assertRaises(
            SocialAccountIdentityError,
            utility.new,
            user,
            SocialPlatformType.MATRIX,
            attributes,
        )

    def test_malformed_matrix_account_username(self):
        # Username must be a string
        user = self.factory.makePerson()
        attributes = {}
        attributes["homeserver"] = "abc.org"
        attributes["username"] = 123123
        utility = getUtility(ISocialAccountSet)

        self.assertRaises(
            SocialAccountIdentityError,
            utility.new,
            user,
            SocialPlatformType.MATRIX,
            attributes,
        )

    def test_malformed_matrix_account_homeserver(self):
        # Homeserver must be a valid address
        user = self.factory.makePerson()
        attributes = {}
        attributes["homeserver"] = "abc"
        attributes["username"] = "test-nickname"
        utility = getUtility(ISocialAccountSet)

        self.assertRaises(
            SocialAccountIdentityError,
            utility.new,
            user,
            SocialPlatformType.MATRIX,
            attributes,
        )

    def test_empty_fields_matrix_account(self):
        # Identity field must be not empty
        user = self.factory.makePerson()
        attributes = {}
        attributes["homeserver"] = ""
        attributes["username"] = "test-nickname"
        utility = getUtility(ISocialAccountSet)

        self.assertRaises(
            SocialAccountIdentityError,
            utility.new,
            user,
            SocialPlatformType.MATRIX,
            attributes,
        )

    def test_multiple_social_accounts(self):
        # Users can have multiple social accounts
        user = self.factory.makePerson()
        attributes = {}
        attributes["homeserver"] = "abc.org"
        attributes["username"] = "test-nickname"
        getUtility(ISocialAccountSet).new(
            user, SocialPlatformType.MATRIX, attributes
        )
        attributes = {}
        attributes["homeserver"] = "def.org"
        attributes["username"] = "test-nickname"
        getUtility(ISocialAccountSet).new(
            user, SocialPlatformType.MATRIX, attributes
        )

        self.assertEqual(len(user.social_accounts), 2)
        social_account = user.social_accounts[0]
        self.assertEqual(social_account.platform, SocialPlatformType.MATRIX)
        self.assertEqual(social_account.identity["homeserver"], "abc.org")
        self.assertEqual(social_account.identity["username"], "test-nickname")

        social_account = user.social_accounts[1]
        self.assertEqual(social_account.platform, SocialPlatformType.MATRIX)
        self.assertEqual(social_account.identity["homeserver"], "def.org")
        self.assertEqual(social_account.identity["username"], "test-nickname")

    def test_multiple_social_accounts_on_multiple_users(self):
        # Users can have multiple social accounts
        user = self.factory.makePerson()
        attributes = {}
        attributes["homeserver"] = "abc.org"
        attributes["username"] = "test-nickname"
        getUtility(ISocialAccountSet).new(
            user, SocialPlatformType.MATRIX, attributes
        )
        attributes = {}
        attributes["homeserver"] = "def.org"
        attributes["username"] = "test-nickname"
        getUtility(ISocialAccountSet).new(
            user, SocialPlatformType.MATRIX, attributes
        )

        user_two = self.factory.makePerson()
        attributes = {}
        attributes["homeserver"] = "ghi.org"
        attributes["username"] = "test-nickname"
        getUtility(ISocialAccountSet).new(
            user_two, SocialPlatformType.MATRIX, attributes
        )
        attributes = {}
        attributes["homeserver"] = "lmn.org"
        attributes["username"] = "test-nickname"
        getUtility(ISocialAccountSet).new(
            user_two, SocialPlatformType.MATRIX, attributes
        )

        self.assertEqual(len(user.social_accounts), 2)
        social_account = user.social_accounts[0]
        self.assertEqual(social_account.platform, SocialPlatformType.MATRIX)
        self.assertEqual(social_account.identity["homeserver"], "abc.org")
        self.assertEqual(social_account.identity["username"], "test-nickname")

        social_account = user.social_accounts[1]
        self.assertEqual(social_account.platform, SocialPlatformType.MATRIX)
        self.assertEqual(social_account.identity["homeserver"], "def.org")
        self.assertEqual(social_account.identity["username"], "test-nickname")

        self.assertEqual(len(user_two.social_accounts), 2)
        social_account = user_two.social_accounts[0]
        self.assertEqual(social_account.platform, SocialPlatformType.MATRIX)
        self.assertEqual(social_account.identity["homeserver"], "ghi.org")
        self.assertEqual(social_account.identity["username"], "test-nickname")

        social_account = user_two.social_accounts[1]
        self.assertEqual(social_account.platform, SocialPlatformType.MATRIX)
        self.assertEqual(social_account.identity["homeserver"], "lmn.org")
        self.assertEqual(social_account.identity["username"], "test-nickname")
