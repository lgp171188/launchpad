# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Download subprocess support for buildd-manager.

To minimise subprocess memory use, this intentionally avoids importing
anything from the rest of Launchpad.
"""

__all__ = [
    "DownloadCommand",
    "EndFetchServiceSessionCommand",
    "RemoveResourcesFetchServiceSessionCommand",
    "RequestFetchServiceSessionCommand",
    "RequestProcess",
    "RequestProxyTokenCommand",
    "RetrieveFetchServiceSessionCommand",
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
    response: List[Tuple[bytes, amp.Argument]] = []
    errors = {
        RequestException: b"REQUEST_ERROR",
        StreamingError: b"STREAMING_ERROR",
    }


class RequestFetchServiceSessionCommand(amp.Command):
    """Fetch service API Command subclass to start a session.

    It defines arguments, response values, and error conditions.
    For reference:
    https://docs.twisted.org/en/twisted-18.7.0/core/howto/amp.html
    """

    arguments = [
        (b"url", amp.Unicode()),
        (b"auth_header", amp.String()),
    ]
    response = [
        (b"id", amp.Unicode()),
        (b"token", amp.Unicode()),
    ]
    errors = {
        RequestException: b"REQUEST_ERROR",
    }


class RetrieveFetchServiceSessionCommand(amp.Command):
    """Fetch service API Command subclass to retrieve data from a session.

    It defines arguments and error conditions. For reference:
    https://docs.twisted.org/en/twisted-18.7.0/core/howto/amp.html
    """

    arguments = [
        (b"url", amp.Unicode()),
        (b"auth_header", amp.String()),
        (b"save_content_to", amp.Unicode()),
    ]
    response: List[Tuple[bytes, amp.Argument]] = []

    errors = {
        RequestException: b"REQUEST_ERROR",
    }


class EndFetchServiceSessionCommand(amp.Command):
    """Fetch service API Command subclass to end a session.

    It defines arguments and error conditions. For reference:
    https://docs.twisted.org/en/twisted-18.7.0/core/howto/amp.html
    """

    arguments = [
        (b"url", amp.Unicode()),
        (b"auth_header", amp.String()),
    ]
    response: List[Tuple[bytes, amp.Argument]] = []
    errors = {
        RequestException: b"REQUEST_ERROR",
    }


class RemoveResourcesFetchServiceSessionCommand(amp.Command):
    """Fetch service API Command subclass to remove resources from a session.

    It defines arguments and error conditions. For reference:
    https://docs.twisted.org/en/twisted-18.7.0/core/howto/amp.html
    """

    arguments = [
        (b"url", amp.Unicode()),
        (b"auth_header", amp.String()),
    ]
    response: List[Tuple[bytes, amp.Argument]] = []
    errors = {
        RequestException: b"REQUEST_ERROR",
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

    @staticmethod
    def _saveResponseToFile(streamed_response, path_to_write):
        """Helper method to save a streamed response to a given path.

        :param streamed_response: response from a request with `stream=True`.
        :param path_to_write: os path (incl. filename) where to write data to.
        """
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
            stream.stream_response_to_file(streamed_response, path=f)
        except Exception:
            f.close()
            os.unlink(f.name)
            raise
        else:
            f.close()
            os.rename(f.name, path_to_write)
        return {}

    @DownloadCommand.responder
    def downloadCommand(self, file_url, path_to_write, timeout):
        with Session() as session:
            session.trust_env = False
            response = session.get(file_url, timeout=timeout, stream=True)
            response.raise_for_status()
            return self._saveResponseToFile(response, path_to_write)

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

    @RequestFetchServiceSessionCommand.responder
    def requestFetchServiceSessionCommand(self, url, auth_header):
        with Session() as session:
            session.trust_env = False
            # XXX pelpsi: from ST108 and from what Claudio
            # said `timeout` and `policy` are not mandatory now:
            # `timeout` will never be mandatory and we don't pass
            # it as parameter to the call.
            # `policy` could be mandatory or optional in future
            # (assuming `strict` as default), so for now it's better
            # to pass it explicitly and set it as `permissive`.
            response = session.post(
                url,
                headers={"Authorization": auth_header},
                json={"policy": "permissive"},
            )
            response.raise_for_status()
            return response.json()

    @RetrieveFetchServiceSessionCommand.responder
    def retrieveFetchServiceSessionCommand(
        self, url, auth_header, save_content_to
    ):
        with Session() as session:
            session.trust_env = False
            response = session.get(
                url,
                headers={"Authorization": auth_header},
                stream=True,
            )
            response.raise_for_status()
            return self._saveResponseToFile(response, save_content_to)

    @EndFetchServiceSessionCommand.responder
    def endFetchServiceSessionCommand(self, url, auth_header):
        with Session() as session:
            session.trust_env = False
            response = session.delete(
                url,
                headers={"Authorization": auth_header},
            )
            response.raise_for_status()
            return {}

    @RemoveResourcesFetchServiceSessionCommand.responder
    def removeResourcesFetchServiceSessionCommand(self, url, auth_header):
        with Session() as session:
            session.trust_env = False
            response = session.delete(
                url,
                headers={"Authorization": auth_header},
            )
            response.raise_for_status()
            return {}
