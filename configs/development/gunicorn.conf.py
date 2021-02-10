from fnmatch import fnmatch
import os


BASE_DIR = os.path.realpath(
    os.path.join(os.path.dirname(__file__), '..', '..'))
CONFIG_DIR = os.path.dirname(__file__)


def find_files(directory, pattern):
    """Find files in `directory` matching `pattern`.
    """
    result = []
    for root, dirs, files in os.walk(directory):
        for basename in files:
            matches = fnmatch(basename, pattern)
            if matches:
                filename = os.path.join(root, basename)
                result.append(filename)
    return result


bind = [":8085", ":8086", ":8087", ":8088", ":8089"]
workers = 2
threads = 10
max_requests = 1000
log_level = "DEBUG"
reload = True

# Watch config files changes from the source tree.
reload_extra_files = find_files(CONFIG_DIR, "*")
for pattern in ["*.zcml", "*.conf"]:
    reload_extra_files += find_files(os.path.join(BASE_DIR, 'lib'), pattern)
