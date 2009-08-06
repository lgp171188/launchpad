#!/usr/bin/env python2.6

from base64 import standard_b64encode
from sys import stdin, stdout, stderr
from lxml import etree


NS = "https://launchpad.net/xmlns/2006/bugs"


def norm_text(elem):
    if elem is not None:
        if elem.text is None:
            elem.text = u""
        else:
            elem.text = elem.text.strip()


def truncate(text, message=None):
    lines = text.splitlines()
    if len(lines) >= 30:
        if message is None:
            message = "[Truncated]"
        else:
            message = "[Truncated; %s]" % message
        return u"%s...\n\n%s" % (
            "\n".join(lines[:30]).strip(), message)
    else:
        return text


if __name__ == '__main__':
    tree = etree.parse(stdin)
    root = tree.getroot()

    # Scan the tree, fixing up issues.
    for bug in root.findall('{%s}bug' % NS):
        # Get or create the tags element.
        tags = bug.find('{%s}tags' % NS)
        if tags is None:
            tags = etree.SubElement(bug, '{%s}tags' % NS)

        # Add the nickname as a tag. If there is no nickname, add an
        # empty one to be filled in later.
        nickname = bug.find('{%s}nickname' % NS)
        if nickname is None:
            nickname = etree.SubElement(bug, '{%s}nickname' % NS)
        else:
            etree.SubElement(tags, '{%s}tag' % NS).text = nickname.text

        # Change the nickname.
        nickname.text = u"openfiler-%s" % bug.get('id')

        # Get the first comment and its text. We'll need these later.
        first_comment = bug.find('{%s}comment' % NS)
        first_comment_text = first_comment.find('{%s}text' % NS)
        norm_text(first_comment_text)

        # Check the description.
        description = bug.find('{%s}description' % NS)
        norm_text(description)
        if len(description.text) == 0:
            stderr.write(
                "Bug %s has no description.\n" % bug.get('id'))
            # Try and get the description from the first comment.
            if first_comment_text is None:
                stderr.write("  No comments!\n")
                stderr.write("  --> Setting description to '-'.\n")
                description.text = u'-'
            elif len(first_comment_text.text) == 0:
                stderr.write("  First comment has no text!\n")
                stderr.write("  --> Setting description to '-'.\n")
                description.text = u'-'
            else:
                stderr.write("  First comment has text.\n")
                stderr.write("  --> Removing description.\n")
                # The spec says that the description is optional, but
                # the importer treats it as optional.
                bug.remove(description)
            stderr.write('\n')
        elif len(description.text) > 50000:
            stderr.write(
                "Bug %s's description is too long (%d chars).\n" % (
                    bug.get('id'), len(description.text),))
            # Compare the description to the first comment. If it's
            # the same, we don't need the description.
            if first_comment_text is None:
                stderr.write("  No comments!\n")
                stderr.write("  --> Adding comment.\n")
                raise NotImplementedError("Add a comment.")
            elif description.text == first_comment_text.text:
                stderr.write('  Description is same as first comment.\n')
                stderr.write('  --> Trimming description.\n')
                # It's safe to point the user to an attachment here,
                # even though it has not yet been created. It will be
                # created later because the first comment is also too
                # long.
                description.text = truncate(
                    description.text, 'see "Full description" attachment')
            else:
                raise NotImplementedError("Fix overlong description.")
            stderr.write('\n')

        # Check first comment text.
        if first_comment_text is not None:
            if len(first_comment_text.text) == 0:
                stderr.write(
                    "Bug %s's first comment has no text.\n" % bug.get('id'))
                stderr.write("  --> Setting comment text to '-'.\n")
                first_comment_text.text = u'-'
                stderr.write('\n')
            elif len(first_comment_text.text) > 50000:
                stderr.write(
                    "Bug %s's first comment is too long (%d chars).\n" % (
                        bug.get('id'), len(first_comment_text.text)))
                # Save the original text as an attachment.
                stderr.write('  --> Adding attachment.\n')
                attachment = etree.SubElement(
                    first_comment, '{%s}attachment' % NS)
                etree.SubElement(attachment, '{%s}filename' % NS).text = (
                    u"openfiler-bug-%s-full-description.txt" % bug.get('id'))
                etree.SubElement(attachment, '{%s}title' % NS).text = (
                    u"Full description (text/plain, utf-8)")
                etree.SubElement(attachment, '{%s}mimetype' % NS).text = (
                    u"text/plain")
                etree.SubElement(attachment, '{%s}contents' % NS).text = (
                    standard_b64encode(
                        first_comment_text.text.encode('utf-8')))
                # Trim the comment text.
                stderr.write('  --> Trimming comment text.\n')
                first_comment_text.text = truncate(
                    first_comment_text.text,
                    'see "Full description" attachment')
                stderr.write('\n')

    # Write it back out again.
    tree.write(stdout, encoding='utf-8',
               pretty_print=True, xml_declaration=True)
