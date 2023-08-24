# Copyright 2004-2017 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Scripts for starting a Python prompt with Launchpad initialized.

The scripts provide an interactive prompt with the Launchpad Storm classes,
all interface classes and the zope3 CA-fu at your fingertips, connected to
launchpad_dev or the database specified on the command line.
One uses Python, the other iPython.
"""

__all__ = ["python", "ipython"]

# This has entry points with corresponding scripts installed by setup.py.

import os
import readline
import rlcompleter
import sys
import webbrowser

import transaction
from storm.expr import *  # noqa: F401,F403

# Bring in useful bits of Storm.
from storm.locals import *  # noqa: F401,F403
from zope.component import getUtility
from zope.interface.verify import verifyObject
from zope.security.proxy import removeSecurityProxy

from lp.answers.model.question import Question
from lp.blueprints.model.specification import Specification
from lp.bugs.model.bug import Bug
from lp.registry.model.distribution import Distribution
from lp.registry.model.distroseries import DistroSeries
from lp.registry.model.person import Person
from lp.registry.model.product import Product
from lp.registry.model.projectgroup import ProjectGroup
from lp.services.config import dbconfig
from lp.services.database.interfaces import IPrimaryStore
from lp.services.scripts import execute_zcml_for_scripts
from lp.services.webapp import canonical_url
from lp.testing.factory import LaunchpadObjectFactory

# Silence unused name warnings
(
    transaction,
    verifyObject,
    removeSecurityProxy,
    canonical_url,
    getUtility,
    rlcompleter,
)


def _get_locals():
    if len(sys.argv) > 1:
        dbuser = sys.argv[1]
    else:
        dbuser = None
    dbconfig.override(dbuser=dbuser)
    execute_zcml_for_scripts()
    readline.parse_and_bind("tab: complete")
    # Mimic the real interactive interpreter's loading of any
    # $PYTHONSTARTUP file.
    startup = os.environ.get("PYTHONSTARTUP")
    if startup:
        with open(startup) as f:
            exec(f.read(), globals())
    store = IPrimaryStore(Person)

    if dbuser == "launchpad":
        # Create a few variables "in case they come in handy."
        # Do we really use these?  Are they worth carrying around?
        d = Distribution.get(1)
        p = Person.get(1)
        ds = DistroSeries.get(1)
        prod = Product.get(1)
        proj = store.get(ProjectGroup, 1)
        b2 = store.get(Bug, 2)
        b1 = store.get(Bug, 1)
        s = store.get(Specification, 1)
        q = store.get(Question, 1)
        # Silence unused name warnings
        d, p, ds, prod, proj, b2, b1, s, q

    # Having a factory instance is handy.
    factory = LaunchpadObjectFactory()

    def browser_open(obj, *args, **kwargs):
        """Open a (possibly newly-created) object's view in a web browser.

        Accepts the same parameters as canonical_url.

        Performs a commit before invoking the browser, so
        "browser_open(factory.makeFoo())" works.
        """
        transaction.commit()
        webbrowser.open(canonical_url(obj, *args, **kwargs))

    # Silence unused name warnings
    factory, store

    res = {}
    res.update(locals())
    res.update(globals())
    del res["_get_locals"]
    return res


def python():
    import code

    code.interact(banner="", local=_get_locals())


def ipython():
    from IPython import start_ipython

    start_ipython(argv=[], user_ns=_get_locals())
