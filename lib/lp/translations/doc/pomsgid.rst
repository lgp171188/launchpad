POMsgID.getByMsgid()
====================

Test that getByMsgid is working:

    >>> from lp.translations.model.pomsgid import POMsgID
    >>> created = POMsgID.new("This is a launchpad test")
    >>> got = POMsgID.getByMsgid("This is a launchpad test")
    >>> got == created
    True

    >>> created = POMsgID.new("This is a very \t\n\b'?'\\ odd test")
    >>> got = POMsgID.getByMsgid("This is a very \t\n\b'?'\\ odd test")
    >>> got == created
    True
