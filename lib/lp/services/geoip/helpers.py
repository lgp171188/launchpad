# Copyright 2009-2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

import ipaddress

import six
from zope.component import getUtility

from lp.services.geoip.interfaces import IGeoIP


__all__ = [
    'request_country',
    'ipaddress_is_global',
    'ipaddress_from_request',
    ]


def request_country(request):
    """Adapt a request to the country in which the request was made.

    Return None if the remote IP address is unknown or its country is not in
    our database.

    This information is not reliable and trivially spoofable - use it only
    for selecting sane defaults.
    """
    ip_address = ipaddress_from_request(request)
    if ip_address is not None:
        return getUtility(IGeoIP).getCountryByAddr(ip_address)
    return None


def ipaddress_is_global(addr):
    """Return True iff the IP address is on a global public network."""
    try:
        return ipaddress.ip_address(six.ensure_text(addr)).is_global
    except ValueError:
        return False


def ipaddress_from_request(request):
    """Determine the IP address for this request.

    Returns None if the IP address cannot be determined or is not on a
    global public network.

    The remote IP address is determined by the X-Forwarded-For: header,
    or failing that, the REMOTE_ADDR CGI environment variable.

    Because this information is unreliable and trivially spoofable, we
    don't bother to do much error checking to ensure the IP address is at
    all valid, beyond what the ipaddress module gives us.

    >>> ipaddress_from_request({'REMOTE_ADDR': '1.1.1.1'})
    '1.1.1.1'
    >>> ipaddress_from_request({
    ...     'HTTP_X_FORWARDED_FOR': '66.66.66.66',
    ...     'REMOTE_ADDR': '1.1.1.1'
    ...     })
    '66.66.66.66'
    >>> ipaddress_from_request({'HTTP_X_FORWARDED_FOR':
    ...     'localhost, 127.0.0.1, 255.255.255.255,1.1.1.1'
    ...     })
    '1.1.1.1'
    >>> ipaddress_from_request({
    ...     'HTTP_X_FORWARDED_FOR': 'nonsense',
    ...     'REMOTE_ADDR': '1.1.1.1'
    ...     })
    """
    ipaddresses = request.get('HTTP_X_FORWARDED_FOR')

    if ipaddresses is None:
        ipaddresses = request.get('REMOTE_ADDR')

    if ipaddresses is None:
        return None

    # We actually get a comma separated list of addresses. We need to throw
    # away the obvious duds, such as loopback addresses
    ipaddresses = [addr.strip() for addr in ipaddresses.split(',')]
    ipaddresses = [addr for addr in ipaddresses if ipaddress_is_global(addr)]

    if ipaddresses:
        # If we have more than one, have a guess.
        return ipaddresses[0]
    return None
