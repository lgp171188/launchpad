# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Download subprocess support for buildd-manager.

To minimise subprocess memory use, this intentionally avoids importing
anything from the rest of Launchpad.
"""

__all__ = [
    "DownloadCommand",
    "RequestProcess",
    "RequestProxyTokenCommand",
]

import os.path
import tempfile
from typing import List, Tuple

from ampoule.child import AMPChild
from requests import RequestException, Session
from requests_toolbelt.downloadutils import stream
from requests_toolbelt.exceptions import StreamingError
from twisted.protocols import amp


class DownloadCommand(amp.Command):
    arguments = [
        (b"file_url", amp.Unicode()),
        (b"path_to_write", amp.Unicode()),
        (b"timeout", amp.Integer()),
    ]
    response = []  # type: List[Tuple[bytes, amp.Argument]]
    errors = {
        RequestException: b"REQUEST_ERROR",
        StreamingError: b"STREAMING_ERROR",
    }


class RequestProxyTokenCommand(amp.Command):
    arguments = [
        (b"url", amp.Unicode()),
        (b"auth_header", amp.String()),
        (b"proxy_username", amp.Unicode()),
    ]
    response = [
        (b"username", amp.Unicode()),
        (b"secret", amp.Unicode()),
        (b"timestamp", amp.Unicode()),
    ]
    errors = {
        RequestException: b"REQUEST_ERROR",
    }


class RequestProcess(AMPChild):
    """A subprocess that performs requests for buildd-manager."""

    @DownloadCommand.responder
    def downloadCommand(self, file_url, path_to_write, timeout):
        with Session() as session:
            session.trust_env = False
            response = session.get(file_url, timeout=timeout, stream=True)
            response.raise_for_status()
            try:
                os.makedirs(os.path.dirname(path_to_write))
            except FileExistsError:
                pass
            f = tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=os.path.basename(path_to_write) + "_",
                dir=os.path.dirname(path_to_write),
                delete=False,
            )
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

    @RequestProxyTokenCommand.responder
    def requestProxyTokenCommand(self, url, auth_header, proxy_username):
        with Session() as session:
            session.trust_env = False
            response = session.post(
                url,
                headers={"Authorization": auth_header},
                json={"username": proxy_username},
            )
            response.raise_for_status()
            return response.json()
