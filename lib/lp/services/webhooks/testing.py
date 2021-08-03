# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Webhook testing helpers."""

__metaclass__ = type
__all__ = [
    'LogsScheduledWebhooks',
    ]

from testtools.matchers import (
    AfterPreprocessing,
    Matcher,
    MatchesSetwise,
    StartsWith,
    )


class LogsOneScheduledWebhook(Matcher):
    """Matches a line of logger output indicating a scheduled webhook."""

    def __init__(self, webhook, event_type, payload_matcher):
        self.webhook = webhook
        self.event_type = event_type
        self.payload_matcher = payload_matcher

    def match(self, line):
        prefix = (
            "Scheduled <WebhookDeliveryJob for webhook %d on %r> (%s): " %
            (self.webhook.id, self.webhook.target, self.event_type))
        mismatch = StartsWith(prefix).match(line)
        if mismatch is not None:
            return mismatch
        return AfterPreprocessing(eval, self.payload_matcher).match(
            line[len(prefix):])


class LogsScheduledWebhooks(MatchesSetwise):
    """Matches logger output indicating at least one scheduled webhook.

    Construct this with a sequence of (webhook, event_type, payload_matcher)
    tuples.
    """

    def __init__(self, expected_webhooks):
        super(LogsScheduledWebhooks, self).__init__(*(
            LogsOneScheduledWebhook(webhook, event_type, payload_matcher)
            for webhook, event_type, payload_matcher in expected_webhooks))

    def match(self, logger_output):
        return super(LogsScheduledWebhooks, self).match(
            [line for line in logger_output.splitlines()
             if line.startswith("Scheduled <WebhookDeliveryJob ")])
