# Copyright 2011-2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""An API for messaging systems in Launchpad, e.g. RabbitMQ."""

__all__ = [
    "connect",
    "is_configured",
]

import amqp

from lp.services.config import config
from lp.services.messaging.interfaces import MessagingUnavailable


def is_configured():
    """Return True if rabbit looks to be configured."""
    return not (
        config.rabbitmq.host is None
        or config.rabbitmq.userid is None
        or config.rabbitmq.password is None
        or config.rabbitmq.virtual_host is None
    )


def connect():
    """Connect to AMQP if possible.

    :raises MessagingUnavailable: If the configuration is incomplete.
    """
    if not is_configured():
        raise MessagingUnavailable("Incomplete configuration")
    connection = amqp.Connection(
        host=config.rabbitmq.host,
        userid=config.rabbitmq.userid,
        password=config.rabbitmq.password,
        virtual_host=config.rabbitmq.virtual_host,
    )
    connection.connect()
    return connection
