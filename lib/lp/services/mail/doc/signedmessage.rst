SignedMessage extends email.message.Message in order to provide easy
access to signed content and the signature of messages.

You can create it from a byte string using signed_message_from_bytes. It
basically the same as using email.message_from_bytes and passing
SignedMessage as the _class parameter, but it also ensures that all
the attributes are correctly set.

    >>> from lp.services.mail.interfaces import ISignedMessage
    >>> from lp.services.mail.signedmessage import signed_message_from_bytes
    >>> from lp.testing import verifyObject
    >>> msg = signed_message_from_bytes(b"To: someone\n\nHello.")
    >>> verifyObject(ISignedMessage, msg)
    True
    >>> msg["To"]
    'someone'
    >>> print(msg.parsed_bytes.decode())
    To: someone
    <BLANKLINE>
    Hello.


We have some test messages that can be easily accessed by
read_test_message. Let's start with a simple message, where the
signature is inline with the signed content:

    >>> from lp.services.mail.tests.helpers import read_test_message
    >>> msg = read_test_message("signed_inline.txt")

You can access the headers of the message:

    >>> print(msg["From"])
    Sample Person <test@canonical.com>

The raw byte string that was signed is available as msg.signedContent:

    >>> isinstance(msg.signedContent, bytes)
    True
    >>> print(six.ensure_text(msg.signedContent))
    Some signed content.
    <BLANKLINE>
    With multiple paragraphs.

And to make it easier to work with, it's available as an email.message
object as well:

    >>> signed_msg = msg.signedMessage
    >>> print(signed_msg.get_payload())
    Some signed content.
    <BLANKLINE>
    With multiple paragraphs.

Finally the signature can be accessed via msg.signature:

    >>> isinstance(msg.signature, bytes)
    True
    >>> print(six.ensure_text(msg.signature))
    -----BEGIN PGP SIGNATURE-----
    Version: GnuPG v1.2.5 (GNU/Linux)
    <BLANKLINE>
    iD8DBQFCXaoOuiuTid/SBUMRAoRkAJoCuy/kSVPCN1kBTqMG+cgsbhhFbwCfeSjH
    /Uc8UVJBiA94yh4G50qgD8o=
    =lNZi
    -----END PGP SIGNATURE-----

If some lines in the signed content begin with a '-', that means that
they have been dash escaped by the client. The dash escaping is done
after the content has been signed, so the signed content should be
unescaped.

    >>> msg = read_test_message("signed_dash_escaped.txt")
    >>> print(msg.get_payload())
    -----BEGIN PGP SIGNED MESSAGE-----
    ...
    - --
    Sample Person
    ...

    >>> print(six.ensure_text(msg.signedContent))
    Some signed content.
    <BLANKLINE>
    --
    Sample Person


It also works when the signature is detached, that is the message
contains of two MIME parts, the signed text, and the signature:

    >>> msg = read_test_message("signed_detached.txt")

The signed content includes the MIME headers as well:

    >>> print(six.ensure_text(msg.signedContent))
    Content-Type: text/plain; charset=us-ascii
    Content-Disposition: inline
    <BLANKLINE>
    Some signed content.

In signedMessage you can access the headers and the content
separately:

    >>> print(msg.signedMessage["Content-Type"])
    text/plain; charset=us-ascii
    >>> print(msg.signedMessage.get_payload())
    Some signed content.


And of course the signature is accessible as well:

    >>> print(six.ensure_text(msg.signature))
    -----BEGIN PGP SIGNATURE-----
    Version: GnuPG v1.2.5 (GNU/Linux)
    <BLANKLINE>
    iD8DBQFCXah8uiuTid/SBUMRAotfAJwOYuLfnW0mV3EA67gXhuhnE/Ur7wCfRVMZ
    xIlThcNdAY9Wkd289kB5W8I=
    =fQDd
    -----END PGP SIGNATURE-----

If the message is unsigned, all attributes will be None:

    >>> msg = read_test_message("unsigned_multipart.txt")
    >>> msg.signedContent is None
    True
    >>> msg.signedMessage is None
    True
    >>> msg.signature is None
    True

It handles signed multipart messages as well:

    >>> msg = read_test_message("signed_multipart.txt")
    >>> content, attachment = msg.signedMessage.get_payload()
    >>> print(content.get_payload())
    Some signed content.
    <BLANKLINE>
    >>> print(attachment.get_payload())
    A signed attachment.
    <BLANKLINE>

    >>> print(six.ensure_text(msg.signature))
    -----BEGIN PGP SIGNATURE-----
    Version: GnuPG v1.2.5 (GNU/Linux)
    <BLANKLINE>
    iD8DBQFCXajSjn63CGxkqMURAtNPAJ4myfPemSBEMR3e4TGvg9LgqiBOJwCdHjRu
    cdC/h/xgiwwrHaUFTk/guuY=
    =fBjf
    -----END PGP SIGNATURE-----

    >>> msg = read_test_message("signed_folded_header.txt")
    >>> print(six.ensure_text(msg.signedContent))
    ... # doctest: -NORMALIZE_WHITESPACE
    Content-Type: multipart/mixed;
     boundary="--------------------EuxKj2iCbKjpUGkD"
    ...
