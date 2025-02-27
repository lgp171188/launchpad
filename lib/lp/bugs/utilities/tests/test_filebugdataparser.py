# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""FileBugDataParser tests.

An application like Apport can upload data to Launchpad, and have the
information added to the bug report that the user will file.  The
information is uploaded as a MIME multipart message, where the different
headers tells Launchpad what kind of information it is.
"""

import base64
import io
from textwrap import dedent

from lp.bugs.model.bug import FileBugData
from lp.bugs.utilities.filebugdataparser import FileBugDataParser
from lp.testing import TestCase


# XXX: ilkeremrekoc 2025-02-26:
# This class is for mocking the open() method of librarian-file-alias that
# doesn't exist in BytesIO. BytesIO is only used for testing purposes as
# production only uses LibrarianFileAlias. Thus, this additional functionality
# won't affect production. Once the Apport package upgrades are done, we can
# delete this class along with the "_findLineBreakType()"" method as we
# wouldn't need the ".open()" functionality anymore.
class MockBytesIO(io.BytesIO):

    # Added a storage variable since the close() method used in
    # FileBugDataParser flushes the BytesIO completely from memory making it
    # impossible to re-open. Thus, "self.initial_bytes" let's us re-open the
    # same input later.
    def __init__(self, initial_bytes=b""):
        self.initial_bytes = initial_bytes
        super().__init__(initial_bytes)

    # open() method doesn't exist in BytesIO originally, we add it to make
    # sure tests act closer to a file/file-alias input into FileBugDataParser.
    def open(self):
        super().__init__(self.initial_bytes)


class TestFileBugDataParser(TestCase):
    def setUp(self):
        super().setUp()

        # The message used in every test for _findLineBreakType
        self.msg_for_linebreak_type = dedent(
            """\
            MIME-Version: 1.0
            Content-type: multipart/mixed; boundary=boundary

            --boundary
            Content-disposition: inline
            Content-type: text/plain; charset=utf-8

            This should be added to the description.

            Another line.

            --boundary--
            """
        )

    def test_initial_buffer(self):
        # The parser's buffer starts out empty.
        parser = FileBugDataParser(MockBytesIO(b"123456789"))
        self.assertEqual(b"", parser._buffer)

    def test__consumeBytes(self):
        # _consumeBytes reads from the file until a delimiter is
        # encountered.
        parser = FileBugDataParser(MockBytesIO(b"123456789"))
        parser.BUFFER_SIZE = 3
        self.assertEqual(b"1234", parser._consumeBytes(b"4"))
        # In order to find the delimiter string, it had to read b"123456"
        # into the buffer, so two bytes remain.
        self.assertEqual(b"56", parser._buffer)
        # The delimiter string isn't limited to one character.
        self.assertEqual(b"567", parser._consumeBytes(b"67"))
        self.assertEqual(b"89", parser._buffer)
        # If the delimiter isn't found in the file, the rest of the file is
        # returned.
        self.assertEqual(b"89", parser._consumeBytes(b"0"))
        self.assertEqual(b"", parser._buffer)
        # Subsequent reads result in the empty string.
        self.assertEqual(b"", parser._consumeBytes(b"0"))
        self.assertEqual(b"", parser._consumeBytes(b"0"))

    def test__findLineBreakType_with_LF(self):
        # _findLineBreakType reads the whole message until either an LF or
        # a CRLF is found, returns that type in bytes string format and exits.

        # Test the message with LF endings
        msg_with_lf = self.msg_for_linebreak_type.encode("ASCII")
        lf_parser = FileBugDataParser(MockBytesIO(msg_with_lf))
        lf_linebreak = lf_parser._findLineBreakType()

        self.assertEqual(lf_linebreak, b"\n")

    def test__findLineBreakType_with_CRLF(self):
        # _findLineBreakType returns a byte-string CRLF if it finds one in
        # the message.

        msg_with_crlf = self.msg_for_linebreak_type.replace(
            "\n", "\r\n"
        ).encode("ASCII")
        crlf_parser = FileBugDataParser(MockBytesIO(msg_with_crlf))
        crlf_linebreak = crlf_parser._findLineBreakType()

        self.assertEqual(crlf_linebreak, b"\r\n")

    def test__findLineBreakType_with_no_linebreaks(self):
        # _findLineBreakType does not accept a message with no linebreaks.
        # and should return an error code.

        msg_without_linebreak = self.msg_for_linebreak_type.replace(
            "\n", ""
        ).encode("ASCII")
        without_linebreak_parser = FileBugDataParser(
            MockBytesIO(msg_without_linebreak)
        )

        self.assertRaisesWithContent(
            AssertionError,
            "There are no linebreaks in the blob.",
            without_linebreak_parser._findLineBreakType,
        )

    def test__findLineBreakType_with_CR(self):
        # _findLineBreakType does not accept CR ("\r") type linebreaks
        # and should return an error.

        msg_with_cr = self.msg_for_linebreak_type.replace("\n", "\r").encode(
            "ASCII"
        )
        cr_parser = FileBugDataParser(MockBytesIO(msg_with_cr))

        self.assertRaisesWithContent(
            AssertionError,
            "The wrong linebreak is used. CR isn't accepted.",
            cr_parser._findLineBreakType,
        )

    def test_readLine(self):
        # readLine reads a single line of the file.
        parser = FileBugDataParser(MockBytesIO(b"123\n456\n789"))

        linebreak = b"\n"
        self.assertEqual(b"123\n", parser.readLine(linebreak))
        self.assertEqual(b"456\n", parser.readLine(linebreak))
        self.assertEqual(b"789", parser.readLine(linebreak))
        # If we try to read past the end of the file, an AssertionError is
        # raised.  This ensures that invalid messages don't cause an
        # infinite loop or similar.
        self.assertRaisesWithContent(
            AssertionError,
            "End of file reached.",
            parser.readLine,
            blob_linebreak=linebreak,
        )

    def test_readHeaders(self):
        # readHeaders reads the headers of a MIME message.  It reads all the
        # headers until it sees a blank line.
        msg = dedent(
            """\
            Header: value
            Space-Folded-Header: this header
             is folded with a space.
            Tab-Folded-Header: this header
            \tis folded with a tab.
            Another-header: another-value

            Not-A-Header: not-a-value
            """
        ).encode("ASCII")
        parser = FileBugDataParser(MockBytesIO(msg))

        linebreak = b"\n"
        headers = parser.readHeaders(linebreak)
        self.assertEqual("value", headers["Header"])
        self.assertEqual(
            "this header\n is folded with a space.",
            headers["Space-Folded-Header"],
        )
        self.assertEqual(
            "this header\n\tis folded with a tab.",
            headers["Tab-Folded-Header"],
        )
        self.assertEqual("another-value", headers["Another-Header"])
        self.assertNotIn("Not-A-Header", headers)

    def test__setDataFromHeaders_subject(self):
        # _setDataFromHeaders makes the Subject header available in
        # FileBugData.initial_summary.
        data = FileBugData()
        parser = FileBugDataParser(None)
        parser._setDataFromHeaders(data, {"Subject": "Bug Subject"})
        self.assertEqual("Bug Subject", data.initial_summary)

    def test__setDataFromHeaders_tags(self):
        # _setDataFromHeaders translates the Tags header into a list of
        # lower-case strings as FileBugData.initial_tags.
        data = FileBugData()
        parser = FileBugDataParser(None)
        parser._setDataFromHeaders(data, {"Tags": "Tag-One Tag-Two"})
        self.assertContentEqual(["tag-one", "tag-two"], data.initial_tags)

    def test__setDataFromHeaders_private(self):
        # _setDataFromHeaders translates the Private header into a boolean
        # as FileBugData.private.  It accepts "yes" for True and "no" for
        # False.
        data = FileBugData()
        parser = FileBugDataParser(None)
        parser._setDataFromHeaders(data, {"Private": "yes"})
        self.assertIs(True, data.private)
        data = FileBugData()
        parser._setDataFromHeaders(data, {"Private": "no"})
        self.assertIs(False, data.private)
        # We're in no position to present a good error message to the user
        # at this point, so invalid values get ignored.
        data = FileBugData()
        parser._setDataFromHeaders(data, {"Private": "not-valid"})
        self.assertIsNone(data.private)

    def test__setDataFromHeaders_subscribers(self):
        # _setDataFromHeaders translates the Subscriber header into a list
        # of lower-case strings as FileBugData.subscribers.
        data = FileBugData()
        parser = FileBugDataParser(None)
        parser._setDataFromHeaders(data, {"Subscribers": "sub-one SUB-TWO"})
        self.assertContentEqual(["sub-one", "sub-two"], data.subscribers)

    def test_parse_first_inline_part(self):
        # The first inline part is special.  Instead of being treated as a
        # comment, it gets appended to the bug description.  It's available
        # as FileBugData.extra_description.
        message = dedent(
            """\
            MIME-Version: 1.0
            Content-type: multipart/mixed; boundary=boundary

            --boundary
            Content-disposition: inline
            Content-type: text/plain; charset=utf-8

            This should be added to the description.

            Another line.

            --boundary--
            """
        ).encode("ASCII")
        parser = FileBugDataParser(MockBytesIO(message))
        data = parser.parse()
        self.assertEqual(
            "This should be added to the description.\n\nAnother line.",
            data.extra_description,
        )

    def test_parse_first_inline_part_base64(self):
        # An inline part can be base64-encoded.
        encoded_text = base64.b64encode(
            b"This should be added to the description.\n\n" b"Another line."
        ).decode("ASCII")
        message = dedent(
            """\
            MIME-Version: 1.0
            Content-type: multipart/mixed; boundary=boundary

            --boundary
            Content-disposition: inline
            Content-type: text/plain; charset=utf-8
            Content-transfer-encoding: base64

            %s

            --boundary--
            """
            % encoded_text
        ).encode("ASCII")
        parser = FileBugDataParser(MockBytesIO(message))
        data = parser.parse()
        self.assertEqual(
            "This should be added to the description.\n\nAnother line.",
            data.extra_description,
        )

    def test_parse_other_inline_parts(self):
        # If there is more than one inline part, the second and subsequent
        # parts are added as comments to the bug.  These are simple text
        # strings, available as FileBugData.comments.
        message = dedent(
            """\
            MIME-Version: 1.0
            Content-type: multipart/mixed; boundary=boundary

            --boundary
            Content-disposition: inline
            Content-type: text/plain; charset=utf-8

            This should be added to the description.

            --boundary
            Content-disposition: inline
            Content-type: text/plain; charset=utf-8

            This should be added as a comment.

            --boundary
            Content-disposition: inline
            Content-type: text/plain; charset=utf-8

            This should be added as another comment.

            Line 2.

            --boundary--
            """
        ).encode("ASCII")
        parser = FileBugDataParser(MockBytesIO(message))
        data = parser.parse()
        self.assertEqual(
            [
                "This should be added as a comment.",
                "This should be added as another comment.\n\nLine 2.",
            ],
            data.comments,
        )

    def test_parse_text_attachments(self):
        # Parts with a "Content-Disposition: attachment" header are added as
        # attachments to the bug.  The attachment description can be
        # specified using a Content-Description header, but it's not
        # required.
        message = dedent(
            """\
            MIME-Version: 1.0
            Content-type: multipart/mixed; boundary=boundary

            --boundary
            Content-disposition: attachment; filename='attachment1'
            Content-type: text/plain; charset=utf-8

            This is an attachment.

            Another line.

            --boundary
            Content-disposition: attachment; filename='attachment2'
            Content-description: Attachment description.
            Content-type: text/plain; charset=ISO-8859-1

            This is another attachment, with a description.
            --boundary--
            """
        ).encode("ASCII")
        parser = FileBugDataParser(MockBytesIO(message))
        data = parser.parse()
        self.assertEqual(2, len(data.attachments))
        # The filename is copied into the "filename" item.
        self.assertEqual("attachment1", data.attachments[0]["filename"])
        self.assertEqual("attachment2", data.attachments[1]["filename"])
        # The Content-Type header is copied as is.
        self.assertEqual(
            "text/plain; charset=utf-8", data.attachments[0]["content_type"]
        )
        self.assertEqual(
            "text/plain; charset=ISO-8859-1",
            data.attachments[1]["content_type"],
        )
        # If there is a Content-Description header, it's accessible as
        # "description".  If there isn't any, the file name is used instead.
        self.assertEqual("attachment1", data.attachments[0]["description"])
        self.assertEqual(
            "Attachment description.", data.attachments[1]["description"]
        )
        # The contents of the attachments are stored in files.
        files = [attachment["content"] for attachment in data.attachments]
        self.assertEqual(
            b"This is an attachment.\n\nAnother line.\n\n", files[0].read()
        )
        files[0].close()
        self.assertEqual(
            b"This is another attachment, with a description.\n",
            files[1].read(),
        )
        files[1].close()

    def test_parse_binary_attachments(self):
        # Binary files are base64-encoded.  They are decoded automatically.
        encoded_data = base64.b64encode(
            b"\n".join([b"\x00" * 5, b"\x01" * 5])
        ).decode("ASCII")
        message = dedent(
            """\
            MIME-Version: 1.0
            Content-type: multipart/mixed; boundary=boundary

            --boundary
            Content-disposition: attachment; filename='attachment1'
            Content-type: application/octet-stream
            Content-transfer-encoding: base64

            %s
            --boundary--
            """
            % encoded_data
        ).encode("ASCII")
        parser = FileBugDataParser(MockBytesIO(message))
        data = parser.parse()
        self.assertEqual(1, len(data.attachments))
        self.assertEqual(
            b"\x00\x00\x00\x00\x00\n\x01\x01\x01\x01\x01",
            data.attachments[0]["content"].read(),
        )
        data.attachments[0]["content"].close()

    def test_invalid_message(self):
        # If someone gives an invalid message, for example one that doesn't
        # have an end boundary, the parser raises an AssertionError.  We
        # don't care about giving the user a good error message, since the
        # format is well-known.
        message = dedent(
            """\
            MIME-Version: 1.0
            Content-type: multipart/mixed; boundary=boundary

            --boundary
            Content-disposition: attachment; filename='attachment1'
            Content-type: text/plain; charset=utf-8

            This is an attachment.

            Another line."""
        ).encode("ASCII")
        parser = FileBugDataParser(MockBytesIO(message))
        self.assertRaisesWithContent(
            AssertionError, "End of file reached.", parser.parse
        )
