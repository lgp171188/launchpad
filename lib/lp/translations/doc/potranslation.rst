POTranslation
=============

This is the class that holds the text of translations in the database.

    >>> from lp.translations.model.potranslation import POTranslation

Creating one is easy.

    >>> created = POTranslation.new("This is a launchpad test")

To get hold of a PO translation, use POTranslation.getByTranslation.

    >>> got = POTranslation.getByTranslation("This is a launchpad test")
    >>> got == created
    True
    >>> print(got.translation)
    This is a launchpad test

However, if the translation doesn't already exist, you'll get an error.

    >>> got = POTranslation.getByTranslation("In Xanadu did Kubla Khan")
    Traceback (most recent call last):
    ...
    lp.app.errors.NotFoundError: 'In Xanadu did Kubla Khan'

If you want to get hold of one, and have it automatically created if it
doesn't already exist, use POTranslation.getOrCreateTranslation.

    >>> got = POTranslation.getOrCreateTranslation("In Xanadu did Kubla Khan")
    >>> print(got.translation)
    In Xanadu did Kubla Khan
