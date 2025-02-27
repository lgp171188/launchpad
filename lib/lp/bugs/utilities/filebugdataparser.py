# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).
"""A parser for FileBug data BLOBs"""

__all__ = [
    "FileBugData",
    "FileBugDataParser",
]

import base64
import email
import tempfile

import six

from lp.bugs.model.bug import FileBugData


class FileBugDataParser:
    """Parser for a message containing extra bug information.

    Applications like Apport upload such messages, before filing the
    bug.
    """

    def __init__(self, blob_file):
        self.blob_file = blob_file
        self.headers = {}
        self._buffer = b""
        self.extra_description = None
        self.comments = []
        self.attachments = []
        self.BUFFER_SIZE = 8192

    # XXX: ilkeremrekoc 2025-02-26: The whole point of trying to find the "LF"
    # or "CRLF" is because the Apport package (which is used to send
    # bug-reports to Launchpad) uses LF line-breaks since its inception.
    # This is against the RFC standards, which standardized the "CRLF" as the
    # line-break for all HTTP requests. And because the main parser for zope
    # (which is the "multipart" package) started enforcing this standard
    # strictly in its newer versions, and considering we must upgrade our
    # dependencies, we had to make sure FileBugDataParser accepts the "CRLF"
    # as well. But we cannot accept only "CRLF" for now because the apport
    # package for every older version of Ubuntu would still use the "LF"
    # making it impossible to send bug-reports from older LTS versions.
    # So, until a sufficient number or all the apport packages in future,
    # current and past Ubuntu versions are patched to only send "CRLF" we
    # must use this method to ensure both "LF" and "CRLF" is accepted.
    # Once the apport package patches are done, we can revert this change,
    # get rid of this method and its tests and simply change
    # the "LF" expectance in the previous version into "CRLF" expectance.
    def _findLineBreakType(self) -> bytes:
        """Find the line-break/end_string the message is using and return it.

        Assumptions:
            - The method would be run at the start of any parsing run as this
            method doesn't open the blob file but resets the blob-stream's
            cursor.

            - The line-break can only be LF ("\n") or CRLF ("\r\n") with
            no CR ("\r") functionality.

            - The message must have at least one line-break character when
            parsing. An empty message or one without any line-breaks doesn't
            count.

            - The whole message must be made up of a single line-break type.
            If more than one type is present, something will break after this
            method.

        Reads through the message until it finds an LF character ("\n") before
        closing and reopening the file-alias/blob to reset its cursor (as the
        file-alias/blob doesn't have a "seek" functionality). Then returns
        whichever line-break type is used in the message.

        ...
        :raises AssertionError: If the method cannot find any LF linebreak on
        the message stream, it raises.
        ...
        :return: Either byte typed CRLF (b"\r\n") or byte typed LF (b"\n")
        :rtype: bytes
        """

        # The LF line break is assumed to be a part of the message as it is
        # a part of both LF and CRLF.
        lf_linebreak = b"\n"

        # A temporary buffer we don't need to save outside the scope as it is
        # only for finding the first line-break.
        temp_buffer = b""

        while lf_linebreak not in temp_buffer:
            data = self.blob_file.read(self.BUFFER_SIZE)

            # Append the data to the temp_buffer. This is to ensure any
            # CR ("\r") that is part of a CRLF isn't deleted in a preceding
            # buffer accidentally.
            temp_buffer += data

            if len(data) < self.BUFFER_SIZE:
                # End of file.

                if lf_linebreak not in temp_buffer:
                    # If the linebreak isn't present, then the message must
                    # be broken since the method must read from the start

                    if (
                        b"\r" in temp_buffer
                    ):  # If the linebreak inside the whole message is only CR
                        raise AssertionError(
                            "The wrong linebreak is used. CR isn't accepted."
                        )

                    raise AssertionError(
                        "There are no linebreaks in the blob."
                    )
                break

        # This part is for ".seek(0)" functionality that LibraryFileAlias
        # lacks, requiring the calls to close() -> open() back to back
        # to reset the stream's read cursor to the start of the file.
        self.blob_file.close()
        self.blob_file.open()

        lf_index = temp_buffer.index(lf_linebreak)

        # A slice is needed even if for a single character as bytes type acts
        # differently in slices and in single character accesses.
        if temp_buffer[lf_index - 1 : lf_index] == b"\r":
            return b"\r\n"

        return b"\n"

    def _consumeBytes(self, end_string):
        """Read bytes from the message up to the end_string.

        The end_string is included in the output.

        If end-of-file is reached, '' is returned.
        """
        while end_string not in self._buffer:
            data = self.blob_file.read(self.BUFFER_SIZE)
            self._buffer += data
            if len(data) < self.BUFFER_SIZE:
                # End of file.
                if end_string not in self._buffer:
                    # If the end string isn't present, we return
                    # everything.
                    buffer = self._buffer
                    self._buffer = b""
                    return buffer
                break
        end_index = self._buffer.index(end_string)
        bytes = self._buffer[: end_index + len(end_string)]
        self._buffer = self._buffer[end_index + len(end_string) :]
        return bytes

    def readHeaders(self, blob_linebreak):
        """Read the next set of headers of the message.

        :param bytes blob_linebreak: linebreak type used in the blob message
        in bytes format e.g. b"\n", b"\r\n" """
        header_text = self._consumeBytes(blob_linebreak + blob_linebreak)
        # Use the email package to return a dict-like object of the
        # headers, so we don't have to parse the text ourselves.
        return email.message_from_bytes(header_text)

    def readLine(self, blob_linebreak):
        """Read a line of the message.

        :param bytes blob_linebreak: linebreak type used in the blob message
        in bytes format e.g. b"\n", b"\r\n" """
        data = self._consumeBytes(blob_linebreak)
        if data == b"":
            raise AssertionError("End of file reached.")
        return data

    def _setDataFromHeaders(self, data, headers):
        """Set the data attributes from the message headers."""
        if "Subject" in headers:
            data.initial_summary = six.ensure_text(headers["Subject"])
        if "Tags" in headers:
            tags_string = six.ensure_text(headers["Tags"])
            data.initial_tags = tags_string.lower().split()
        if "Private" in headers:
            private = headers["Private"]
            if private.lower() == "yes":
                data.private = True
            elif private.lower() == "no":
                data.private = False
            else:
                # If the value is anything other than yes or no we just
                # ignore it as we cannot currently give the user an error
                pass
        if "Subscribers" in headers:
            subscribers_string = six.ensure_text(headers["Subscribers"])
            data.subscribers = subscribers_string.lower().split()

    def parse(self):
        """Parse the message and  return a FileBugData instance.

            * The Subject header is the initial bug summary.
            * The Tags header specifies the initial bug tags.
            * The Private header sets the visibility of the bug.
            * The Subscribers header specifies additional initial subscribers
            * The first inline part will be added to the description.
            * All other inline parts will be added as separate comments.
            * All attachment parts will be added as attachment.

        When parsing each part of the message is stored in a temporary
        file on the file system. After using the returned data,
        removeTemporaryFiles() must be called.
        """

        linebreak = self._findLineBreakType()

        headers = self.readHeaders(linebreak)
        data = FileBugData()
        self._setDataFromHeaders(data, headers)

        # The headers is a Message instance.
        boundary = b"--" + six.ensure_binary(headers.get_param("boundary"))
        line = self.readLine(linebreak)
        while not line.startswith(boundary + b"--"):
            part_file = tempfile.TemporaryFile()
            part_headers = self.readHeaders(linebreak)
            content_encoding = part_headers.get("Content-Transfer-Encoding")
            if content_encoding is not None and content_encoding != "base64":
                raise AssertionError(
                    "Unknown encoding: %r." % content_encoding
                )
            line = self.readLine(linebreak)
            while not line.startswith(boundary):
                # Decode the file.
                if content_encoding == "base64":
                    line = base64.b64decode(line)
                part_file.write(line)
                line = self.readLine(linebreak)
            # Prepare the file for reading.
            part_file.seek(0)
            disposition = part_headers["Content-Disposition"]
            disposition = disposition.split(";")[0]
            disposition = disposition.strip()
            if disposition == "inline":
                assert (
                    part_headers.get_content_type() == "text/plain"
                ), "Inline parts have to be plain text."
                charset = part_headers.get_content_charset()
                assert charset, "A charset has to be specified for text parts."
                inline_content = part_file.read().rstrip()
                part_file.close()
                inline_content = inline_content.decode(charset)

                if data.extra_description is None:
                    # The first inline part is extra description.
                    data.extra_description = inline_content
                else:
                    data.comments.append(inline_content)
            elif disposition == "attachment":
                attachment = dict(
                    filename=six.ensure_text(
                        part_headers.get_filename().strip("'")
                    ),
                    content_type=six.ensure_text(part_headers["Content-type"]),
                    content=part_file,
                )
                if "Content-Description" in part_headers:
                    attachment["description"] = six.ensure_text(
                        part_headers["Content-Description"]
                    )
                else:
                    attachment["description"] = attachment["filename"]
                data.attachments.append(attachment)
            else:
                # If the message include other disposition types,
                # simply ignore them. We don't want to break just
                # because some extra information is included.
                continue
        return data
