# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Helper functions for running external commands."""

__all__ = [
    "run_command",
    "run_script",
]

import os
import subprocess
from typing import Dict, List, Optional, Union


# XXX cjwatson 2023-02-03: This type could be stricter: the type of `input`
# depends on the value of `universal_newlines`.
def run_command(
    command: str,
    args: Optional[List[str]] = None,
    env: Optional[Dict[str, str]] = None,
    cwd: Optional[str] = None,
    input: Optional[Union[bytes, str]] = None,
    universal_newlines: bool = True,
):
    """Run an external command in a separate process.

    :param command: executable to run.
    :param args: optional list of command-line arguments.
    :param input: optional text to feed to command's standard input.
    :param env: optional, passed to `subprocess.Popen`.
    :param cwd: optional, passed to `subprocess.Popen`.
    :param universal_newlines: passed to `subprocess.Popen`, defaulting to
        True.
    :return: tuple of returncode, standard output, and standard error.
    """
    command_line = [command]
    if args:
        command_line.extend(args)
    if input is not None:
        stdin = subprocess.PIPE
    else:
        stdin = None

    child = subprocess.Popen(
        command_line,
        stdin=stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        cwd=cwd,
        universal_newlines=universal_newlines,
    )
    stdout, stderr = child.communicate(input)
    returncode = child.wait()
    return (returncode, stdout, stderr)


# XXX cjwatson 2023-02-03: This type could be stricter: the type of `input`
# depends on the value of `universal_newlines`.
def run_script(
    script: str,
    args: Optional[List[str]] = None,
    env: Optional[Dict[str, str]] = None,
    cwd: Optional[str] = None,
    input: Optional[Union[bytes, str]] = None,
    universal_newlines: bool = True,
):
    """Run a Python script in a child process, using current interpreter.

    :param script: Python script to run.
    :param args: optional list of command-line arguments.
    :param env: optional environment dict; if none is given, the script will
        get a copy of the environment of the calling process.  In either
        case, `PYTHONPATH` is removed since inheriting it may break some
        scripts.
    :param env: optional, passed to `subprocess.Popen`.
    :param cwd: optional, passed to `subprocess.Popen`.
    :param input: optional string to feed to standard input.
    :param universal_newlines: passed to `subprocess.Popen`, defaulting to
        True.
    :return: tuple of return value, standard output, and standard error.
    """
    if env is None:
        env = os.environ.copy()
    env.pop("PYTHONPATH", None)

    return run_command(
        script,
        args=args,
        env=env,
        cwd=cwd,
        input=input,
        universal_newlines=universal_newlines,
    )
