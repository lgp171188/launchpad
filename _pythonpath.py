# Copyright 2009-2017 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# This file works if the Python has been started with -S, or if bin/py
# has been used.

import os.path
import sys
from importlib.util import find_spec

# Get path to this file.
if __name__ == "__main__":
    filename = __file__
else:
    # If this is an imported module, we want the location of the .py
    # file, not the .pyc, because the .py file may have been symlinked.
    filename = find_spec(__name__).origin
# Get the full, non-symbolic-link directory for this file.  This is the
# project root.
top = os.path.dirname(os.path.abspath(os.path.realpath(filename)))

env = os.path.join(top, "env")
python_version = "%s.%s" % sys.version_info[:2]
stdlib_dir = os.path.join(env, "lib", "python%s" % python_version)

if "site" in sys.modules and "lp_sitecustomize" not in sys.modules:
    # Site initialization has been run but lp_sitecustomize was not loaded,
    # so something is set up incorrectly.  We blow up, with a hopefully
    # helpful error message.
    raise RuntimeError(
        "Python was invoked incorrectly.  Scripts should usually be "
        "started with Launchpad's bin/py, or with a Python invoked with "
        "the -S flag."
    )

# Ensure that the virtualenv's standard library directory is in sys.path;
# activate_this will not put it there.
if stdlib_dir not in sys.path and (stdlib_dir + os.sep) not in sys.path:
    sys.path.insert(0, stdlib_dir)

if not sys.executable.startswith(top + os.sep) or "site" not in sys.modules:
    # Activate the virtualenv.  Avoid importing lp_sitecustomize here, as
    # activate_this imports site before it's finished setting up sys.path.
    orig_disable_sitecustomize = os.environ.get("LP_DISABLE_SITECUSTOMIZE")
    os.environ["LP_DISABLE_SITECUSTOMIZE"] = "1"
    # This is a bit like env/bin/activate_this.py, but to help namespace
    # packages work properly we change sys.prefix before importing site
    # rather than after.
    sys.real_prefix = sys.prefix
    sys.prefix = env
    os.environ["PATH"] = (
        os.path.join(env, "bin") + os.pathsep + os.environ.get("PATH", "")
    )
    os.environ["VIRTUAL_ENV"] = env
    site_packages = os.path.join(
        env, "lib", "python%s" % python_version, "site-packages"
    )
    import site

    site.addsitedir(site_packages)
    if orig_disable_sitecustomize is not None:
        os.environ["LP_DISABLE_SITECUSTOMIZE"] = orig_disable_sitecustomize
    else:
        del os.environ["LP_DISABLE_SITECUSTOMIZE"]

# Move all our own directories to the front of the path.
new_sys_path = []
for item in list(sys.path):
    if item == top or item.startswith(top + os.sep):
        new_sys_path.append(item)
        sys.path.remove(item)
sys.path[:0] = new_sys_path

# Initialise the Launchpad environment.
if "LP_DISABLE_SITECUSTOMIZE" not in os.environ:
    if "lp_sitecustomize" not in sys.modules:
        import lp_sitecustomize

        lp_sitecustomize.main()
