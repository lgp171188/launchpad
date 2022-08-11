# Copyright 2009-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""
Configuration information pulled from launchpad-lazr.conf.

The configuration section used is specified using the LPCONFIG
environment variable, and defaults to 'development'
"""

import glob
import os
import random
import sys

from lazr.config import ImplicitTypeSchema
from lazr.config.interfaces import ConfigErrors

from lp.services.osutils import open_for_writing
from lp.services.propertycache import cachedproperty, get_property_cache

__all__ = [
    "dbconfig",
    "config",
]


# The config to use can be specified in one of these files.
CONFIG_LOOKUP_FILES = ["/etc/launchpad/config"]
if os.environ.get("HOME"):
    CONFIG_LOOKUP_FILES.insert(
        0, os.path.join(os.environ["HOME"], ".lpconfig")
    )

# LPCONFIG specifies the config to use, which corresponds to a subdirectory
# of configs. It overrides any setting in the CONFIG_LOOKUP_FILES.
LPCONFIG = "LPCONFIG"

# If no CONFIG_LOOKUP_FILE is found and there is no LPCONFIG environment
# variable, we have a fallback. This is what developers normally use.
DEFAULT_CONFIG = "development"

PACKAGE_DIR = os.path.abspath(os.path.dirname(__file__))

# Root of the launchpad tree so code can stop jumping through hoops
# with __file__.
TREE_ROOT = os.path.abspath(
    os.path.join(PACKAGE_DIR, os.pardir, os.pardir, os.pardir, os.pardir)
)

# The directories containing instances configuration directories.
CONFIG_ROOT_DIRS = [
    os.path.join(TREE_ROOT, "configs"),
    os.path.join(TREE_ROOT, "production-configs"),
]


def find_instance_name():
    # Pull instance_name from the environment if possible.
    instance_name = os.environ.get(LPCONFIG, None)

    # Or pull instance_name from a disk file if no environment
    # variable is set.
    if instance_name is None:
        for config_lookup_file in CONFIG_LOOKUP_FILES:
            if os.path.exists(config_lookup_file):
                with open(config_lookup_file) as f:
                    instance_name = f.read()[:80].strip()
                break

    # Of instance_name falls back for developers.
    if instance_name is None:
        instance_name = DEFAULT_CONFIG

    return instance_name


def find_config_dir(instance_name):
    """Look through CONFIG_ROOT_DIRS for instance_name."""
    for root in CONFIG_ROOT_DIRS:
        config_dir = os.path.join(root, instance_name)
        if os.path.isdir(config_dir):
            return config_dir
    raise ValueError(
        "Can't find %s in %s" % (instance_name, ", ".join(CONFIG_ROOT_DIRS))
    )


class LaunchpadConfig:
    """
    Singleton configuration, accessed via the `config` module global.

    Cached copies are kept in thread locals ensuring the configuration
    is thread safe (not that this will be a problem if we stick with
    simple configuration).
    """

    def __init__(self, instance_name=None, process_name=None):
        """Create a new instance of LaunchpadConfig.

        :param instance_name: the configuration instance to use. Defaults to
            the value of the LPCONFIG environment variable.
        :param process_name: the process configuration name to use. Defaults
            to the basename of sys.argv[0] without any extension, or None if
            sys.argv is not available.
        """
        self._invalidateConfig()
        if instance_name is None:
            instance_name = find_instance_name()

        if process_name is None:
            self._process_name = self._make_process_name()
        else:
            self._process_name = process_name
        self._instance_name = instance_name
        self.root = TREE_ROOT

    def _make_process_name(self):
        if getattr(sys, "argv", None) is None:
            return None
        basename = os.path.basename(sys.argv[0])
        return os.path.splitext(basename)[0]

    @property
    def instance_name(self):
        """Return the config's instance name.

        This normally corresponds to the LPCONFIG environment
        variable. It is also the name of the directory the conf file is
        loaded from.
        """
        return self._instance_name

    @property
    def config_dir(self):
        """Return the directory containing this instance configuration."""
        return find_config_dir(self._instance_name)

    def setInstance(self, instance_name):
        """Set the instance name where the conf files are stored.

        This method is used to set the instance_name, which is the
        directory where the conf file is stored. The test runner
        uses this to switch on the test configuration. This
        method also sets the LPCONFIG environment
        variable so subprocesses keep the same default.
        """
        self._instance_name = instance_name
        os.environ[LPCONFIG] = instance_name
        # Need to reload the config.
        self._invalidateConfig()

    def _invalidateConfig(self):
        """Invalidate the config, causing the config to be regenerated."""
        self._config = None

    def reloadConfig(self):
        """Reload the config."""
        self._invalidateConfig()
        self._getConfig()

    def isTestRunner(self):
        """Return true if the current config is a 'testrunner' config.

        That is, if it is the testrunner config, or a unique variation of it,
        but not if its the testrunner-appserver, development or production
        config.
        """
        return (
            self.instance_name == "testrunner"
            or self.instance_name.startswith("testrunner_")
        )

    @property
    def process_name(self):
        """Return or set the current process's name to select a conf.

        LaunchpadConfig loads the conf file named for the process. When
        the conf file does not exist, it loads launchpad-lazr.conf instead.
        """
        if self._process_name is None:
            self._process_name = self._make_process_name()
        return self._process_name

    def setProcess(self, process_name):
        """Set the name of the process to select a conf file.

        This method is used to set the process_name if it should be
        different from the name obtained from sys.argv[0]. LaunchpadConfig
        will try to load <process_name>-lazr.conf if it exists. Otherwise,
        it will load launchpad-lazr.conf.
        """
        self._process_name = process_name
        # Need to reload the config.
        self._invalidateConfig()

    def _getConfig(self):
        """Get the schema and config for this environment.

        The config is will be loaded only when there is not a config.
        Repeated calls to this method will not cause the config to reload.
        """
        if self._config is not None:
            return

        schema_file = os.path.join(PACKAGE_DIR, "schema-lazr.conf")
        config_dir = self.config_dir
        config_file = os.path.join(
            config_dir, "%s-lazr.conf" % self.process_name
        )
        if not os.path.isfile(config_file):
            config_file = os.path.join(config_dir, "launchpad-lazr.conf")
        schema = ImplicitTypeSchema(schema_file)
        self._config = schema.load(config_file)
        self._loadConfigOverlays(config_file)
        try:
            self._config.validate()
        except ConfigErrors as error:
            message = "\n".join([str(e) for e in error.errors])
            raise ConfigErrors(message)

    def _loadConfigOverlays(self, config_file):
        """Apply config overlays from the launchpad.config_overlay_dir."""
        rel_dir = self._config["launchpad"]["config_overlay_dir"]
        if not rel_dir:
            return
        dir = os.path.join(
            os.path.dirname(os.path.abspath(config_file)), rel_dir
        )
        for path in sorted(glob.glob(os.path.join(dir, "*-lazr.conf"))):
            with open(path) as f:
                text = f.read()
            self._config.push(path, text)

    def generate_overrides(self):
        """Ensure correct config.zcml overrides will be called.

        Call this method before letting any ZCML processing occur.
        """
        loader_file = os.path.join(self.root, "zcml/+config-overrides.zcml")
        loader = open_for_writing(loader_file, "w")

        print(
            """
            <configure xmlns="http://namespaces.zope.org/zope">
                <!-- This file automatically generated using
                     lp.services.config.LaunchpadConfig.generate_overrides.
                     DO NOT EDIT. -->
                <include files="%s/*.zcml" />
                </configure>"""
            % self.config_dir,
            file=loader,
        )
        loader.close()

    def appserver_root_url(self, facet="mainsite", ensureSlash=False):
        """Return the correct app server root url for the given facet."""
        root_url = str(getattr(self.vhost, facet).rooturl)
        if not ensureSlash:
            return root_url.rstrip("/")
        if not root_url.endswith("/"):
            return root_url + "/"
        return root_url

    def __getattr__(self, name):
        self._getConfig()
        # Check first if it's not one of the name added directly
        # on this instance.
        if name in self.__dict__:
            return self.__dict__[name]
        return getattr(self._config, name)

    def __contains__(self, key):
        self._getConfig()
        return key in self._config

    def __getitem__(self, key):
        self._getConfig()
        return self._config[key]

    def __dir__(self):
        """List section names in addition to methods and variables."""
        self._getConfig()
        names = dir(self.__class__)
        names.extend(self.__dict__)
        names.extend(section.name for section in self._config)
        return names

    def __iter__(self):
        """Iterate through configuration sections."""
        self._getConfig()
        return iter(self._config)


config = LaunchpadConfig()


class DatabaseConfigOverrides:
    pass


class DatabaseConfig:
    """A class to provide the Launchpad database configuration."""

    _config_section = None
    _db_config_attrs = frozenset(
        [
            "dbuser",
            "rw_main_primary",
            "rw_main_standby",
            "db_statement_timeout",
            "db_statement_timeout_precision",
            "isolation_level",
            "soft_request_timeout",
            "storm_cache",
            "storm_cache_size",
        ]
    )
    _db_config_required_attrs = frozenset(
        ["dbuser", "rw_main_primary", "rw_main_standby"]
    )

    def __init__(self):
        self.reset()

    @property
    def main_primary(self):
        return self.rw_main_primary

    @cachedproperty
    def main_standby(self):
        return random.choice(self.rw_main_standby.split(","))

    # XXX cjwatson 2021-10-01: Remove these once Launchpad's store flavors
    # have been renamed.
    @property
    def main_master(self):
        return self.main_primary

    @property
    def main_slave(self):
        return self.main_standby

    def override(self, **kwargs):
        """Override one or more config attributes.

        Overriding a value to None removes the override.
        """
        for attr, value in kwargs.items():
            assert attr in self._db_config_attrs, (
                "%s cannot be overridden" % attr
            )
            if value is None:
                if hasattr(self.overrides, attr):
                    delattr(self.overrides, attr)
            else:
                setattr(self.overrides, attr, value)
                if attr == "rw_main_standby":
                    del get_property_cache(self).main_standby

    def reset(self):
        self.overrides = DatabaseConfigOverrides()
        del get_property_cache(self).main_standby

    def _getConfigSections(self):
        """Returns a list of sections to search for database configuration.

        The first section in the list has highest priority.
        """
        # config.launchpad remains here for compatibility -- production
        # appserver configs customise its dbuser. Eventually they should
        # be migrated into config.database, and this can be removed.
        return [self.overrides, config.launchpad, config.database]

    def __getattr__(self, name):
        sections = self._getConfigSections()
        if name not in self._db_config_attrs:
            raise AttributeError(name)
        value = None
        for section in sections:
            value = getattr(section, name, None)
            if value is not None:
                break
        # Some values must be provided by the config
        if value is None and name in self._db_config_required_attrs:
            raise ValueError("%s must be set" % name)
        return value


dbconfig = DatabaseConfig()
