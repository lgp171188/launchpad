import unittest

from zope.interface import implementer

from lp.services.webhooks.interfaces import (
    IWebhookTarget,
    ValidWebhookEventTypeVocabulary,
)


@implementer(IWebhookTarget)
class FakeTarget:
    def __init__(self, valid_event_types):
        self.valid_webhook_event_types = valid_event_types


class TestValidWebhookEventTypeVocabulary(unittest.TestCase):
    def test_ordering_with_parent_and_subscopes(self):
        target = FakeTarget(
            [
                "merge-proposal:0.1::create",
                "merge-proposal:0.1",
                "merge-proposal:0.1::push",
                "git:push:0.1",
            ]
        )
        vocab = ValidWebhookEventTypeVocabulary(target)
        self.assertEqual(
            [term.token for term in vocab],
            [
                "merge-proposal:0.1",
                "merge-proposal:0.1::create",
                "merge-proposal:0.1::push",
                "git:push:0.1",
            ],
        )

    def test_skips_subscope_without_parent(self):
        target = FakeTarget(
            [
                "merge-proposal:0.1::review",
                "git:push:0.1",
            ]
        )
        vocab = ValidWebhookEventTypeVocabulary(target)
        self.assertEqual([term.token for term in vocab], ["git:push:0.1"])

    def test_parent_only(self):
        target = FakeTarget(
            [
                "git:push:0.1",
                "merge-proposal:0.1",
            ]
        )
        vocab = ValidWebhookEventTypeVocabulary(target)
        self.assertEqual(
            [term.token for term in vocab],
            ["git:push:0.1", "merge-proposal:0.1"],
        )
