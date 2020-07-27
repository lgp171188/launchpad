# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Download subprocess support for buildd-manager.

To minimise subprocess memory use, this intentionally avoids importing
anything from the rest of Launchpad.
"""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    'DownloadCommand',
    'DownloadProcess',
    ]

import os.path
import tempfile

from ampoule.child import AMPChild
from requests import (
    RequestException,
    Session,
    )
from requests_toolbelt.downloadutils import stream
from requests_toolbelt.exceptions import StreamingError
from twisted.protocols import amp


class DownloadCommand(amp.Command):

    arguments = [
        (b"file_url", amp.Unicode()),
        (b"path_to_write", amp.Unicode()),
        (b"timeout", amp.Integer()),
        ]
    response = []
    errors = {
        RequestException: b"REQUEST_ERROR",
        StreamingError: b"STREAMING_ERROR",
        }


class DownloadProcess(AMPChild):
    """A subprocess that downloads a file to disk."""

    @DownloadCommand.responder
    def downloadCommand(self, file_url, path_to_write, timeout):
        session = Session()
        session.trust_env = False
        response = session.get(file_url, timeout=timeout, stream=True)
        response.raise_for_status()
        f = tempfile.NamedTemporaryFile(
            mode="wb", prefix=os.path.basename(path_to_write) + "_",
            dir=os.path.dirname(path_to_write), delete=False)
        try:
            stream.stream_response_to_file(response, path=f)
        except Exception:
            f.close()
            os.unlink(f.name)
            raise
        else:
            f.close()
            os.rename(f.name, path_to_write)
        return {}
