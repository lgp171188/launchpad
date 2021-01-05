# Copyright 2009-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from __future__ import absolute_import, print_function

__metaclass__ = type

__all__ = [
    'can_be_nominated_for_series',
    'valid_cve_sequence',
    'validate_new_team_email',
    ]

from zope.component import getUtility

from lp import _
from lp.app.validators import LaunchpadValidationError
from lp.app.validators.cve import valid_cve
from lp.app.validators.email import valid_email
from lp.services.identity.interfaces.emailaddress import IEmailAddressSet
from lp.services.webapp import canonical_url
from lp.services.webapp.escaping import (
    html_escape,
    structured,
    )
from lp.services.webapp.interfaces import ILaunchBag


def can_be_nominated_for_series(series):
    """Can the bug be nominated for these series?"""
    current_bug = getUtility(ILaunchBag).bug
    unnominatable_series = []
    for s in series:
        if not current_bug.canBeNominatedFor(s):
            unnominatable_series.append(s.name.capitalize())

    if unnominatable_series:
        series_str = ", ".join(unnominatable_series)
        raise LaunchpadValidationError(_(
            "This bug has already been nominated for these "
            "series: ${series}", mapping={'series': series_str}))

    return True


def valid_cve_sequence(value):
    """Check if the given value is a valid CVE otherwise raise an exception.
    """
    if valid_cve(value):
        return True
    else:
        raise LaunchpadValidationError(_(
            "${cve} is not a valid CVE number", mapping={'cve': value}))


def _validate_email(email):
    if not valid_email(email):
        raise LaunchpadValidationError(_(
            "${email} isn't a valid email address.",
            mapping={'email': email}))


def _check_email_availability(email):
    email_address = getUtility(IEmailAddressSet).getByEmail(email)
    if email_address is not None:
        person = email_address.person
        message = _('${email} is already registered in Launchpad and is '
                    'associated with <a href="${url}">${person}</a>.',
                    mapping={'email': html_escape(email),
                            'url': html_escape(canonical_url(person)),
                            'person': html_escape(person.displayname)})
        raise LaunchpadValidationError(structured(message))


def validate_new_team_email(email):
    """Check that the given email is valid and not registered to
    another launchpad account.
    """
    _validate_email(email)
    _check_email_availability(email)
    return True
