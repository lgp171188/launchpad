#!/usr/bin/env python
#
# Copyright 2009, 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import os.path
import sys
from distutils.sysconfig import get_python_lib
from importlib.machinery import PathFinder
from string import Template
from textwrap import dedent

from setuptools import setup
from setuptools.command.develop import develop
from setuptools.command.easy_install import ScriptWriter


class LPScriptWriter(ScriptWriter):
    """A modified ScriptWriter that uses Launchpad's boilerplate.

    Any script written using this class will set up its environment using
    `lp_sitecustomize` before calling its entry point.

    The standard setuptools handling of entry_points uses
    `pkg_resources.load_entry_point` to resolve requirements at run-time.
    This involves walking Launchpad's entire dependency graph, which is
    rather slow, and we always build all of our "optional" features anyway,
    so we might as well just take the simplified approach of importing the
    modules we need directly.  If we ever want to start using the "extras"
    feature of setuptools then we may want to revisit this.
    """

    template = Template(
        dedent(
            """
        import sys

        import ${module_name}

        if __name__ == '__main__':
            sys.exit(${module_name}.${attrs}())
        """
        )
    )

    @classmethod
    def get_args(cls, dist, header=None):
        """See `ScriptWriter`."""
        if header is None:
            header = cls.get_header()
        for name, ep in dist.get_entry_map("console_scripts").items():
            cls._ensure_safe_name(name)
            script_text = cls.template.substitute(
                {
                    "attrs": ".".join(ep.attrs),
                    "module_name": ep.module_name,
                }
            )
            args = cls._get_script_args("console", name, header, script_text)
            yield from args


class lp_develop(develop):
    """A modified develop command to handle LP script generation."""

    def _get_orig_sitecustomize(self):
        env_top = os.path.join(os.path.dirname(__file__), "env")
        system_paths = [
            path
            for path in sys.path
            if not path.startswith(env_top) and "pip-build-env-" not in path
        ]
        spec = PathFinder.find_spec("sitecustomize", path=system_paths)
        if spec is None:
            return ""
        orig_sitecustomize_path = spec.origin
        if orig_sitecustomize_path.endswith(".py"):
            with open(orig_sitecustomize_path) as orig_sitecustomize_file:
                orig_sitecustomize = orig_sitecustomize_file.read()
                return (
                    dedent(
                        """
                    # The following is from
                    # %s
                    """
                        % orig_sitecustomize_path
                    )
                    + orig_sitecustomize
                )
        else:
            return ""

    def install_wrapper_scripts(self, dist):
        if not self.exclude_scripts:
            for args in LPScriptWriter.get_args(dist):
                self.write_script(*args)

            # Write bin/py for compatibility.  This is much like
            # env/bin/python, but if we just symlink to it and try to
            # execute it as bin/py then the virtualenv doesn't get
            # activated.  We use -S to avoid importing sitecustomize both
            # before and after the execv.
            py_header = LPScriptWriter.get_header("#!python -S")
            py_script_text = dedent(
                """\
                import os
                import sys

                os.execv(sys.executable, [sys.executable] + sys.argv[1:])
                """
            )
            self.write_script("py", py_header + py_script_text)

            # Install site customizations for this virtualenv.  In principle
            # we just want to install sitecustomize and have site load it,
            # but this doesn't work with virtualenv 20.x
            # (https://github.com/pypa/virtualenv/issues/1703).  Note that
            # depending on the resolution of
            # https://bugs.python.org/issue33944 we may need to change this
            # again in future.
            env_top = os.path.join(os.path.dirname(__file__), "env")
            site_packages_dir = get_python_lib(prefix=env_top)
            orig_sitecustomize = self._get_orig_sitecustomize()
            sitecustomize_path = os.path.join(
                site_packages_dir, "_sitecustomize.py"
            )
            with open(sitecustomize_path, "w") as sitecustomize_file:
                sitecustomize_file.write(
                    dedent(
                        """\
                    import os
                    import sys

                    if "LP_DISABLE_SITECUSTOMIZE" not in os.environ:
                        if "lp_sitecustomize" not in sys.modules:
                            import lp_sitecustomize
                            lp_sitecustomize.main()
                    """
                    )
                )
                if orig_sitecustomize:
                    sitecustomize_file.write(orig_sitecustomize)
            # Awkward naming; this needs to come lexicographically after any
            # other .pth files.
            sitecustomize_pth_path = os.path.join(
                site_packages_dir, "zzz_run_venv_sitecustomize.pth"
            )
            with open(sitecustomize_pth_path, "w") as sitecustomize_pth_file:
                sitecustomize_pth_file.write("import _sitecustomize\n")

            # Write out the build-time value of LPCONFIG so that it can be
            # used by scripts as the default instance name.
            instance_name_path = os.path.join(env_top, "instance_name")
            with open(instance_name_path, "w") as instance_name_file:
                print(os.environ["LPCONFIG"], file=instance_name_file)


setup(
    cmdclass={
        "develop": lp_develop,
    },
)
