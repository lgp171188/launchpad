Check to be sure that when a gettext error occurs in a "middle" form, that's a
form that is not the first or the last one to translate with the sets of
messages for this POFile, we still detect the error and notify to our users.

    >>> browser = setupBrowser(auth="Basic carlos@canonical.com:test")
    >>> browser.open(
    ...     "http://translations.launchpad.test/ubuntu/hoary/+source/"
    ...     "evolution/+pots/evolution-2.2/es/+translate?start=10&batch=5"
    ... )

Submit the form using a wrong format string. The msgid is using '%s' which
means it will be an string, but we are going to use '%i' which means an
integer.

    >>> browser.getControl(
    ...     name="msgset_142_es_translation_0_radiobutton"
    ... ).value = ["msgset_142_es_translation_0_new"]
    >>> browser.getControl(name="msgset_142_es_translation_0_new").value = (
    ...     b"Migrando \xc2\xab%i\xc2\xbb"
    ... )

We are going to add a valid translation too so we are sure that it's stored
even when there is an error in another message of the same form.

    >>> browser.getControl(
    ...     name="msgset_140_es_translation_0_radiobutton"
    ... ).value = ["msgset_140_es_translation_0_new"]
    >>> browser.getControl(name="msgset_140_es_translation_0_new").value = (
    ...     "Foo"
    ... )

And submit the form.

    >>> browser.getControl(name="submit_translations").click()

We remain at the same page:

    >>> print(browser.url)  # noqa
    http://translations.launchpad.test/ubuntu/hoary/+source/evolution/+pots/evolution-2.2/es/+translate?start=10&batch=5

The valid translation is stored:

    >>> print(
    ...     find_tag_by_id(
    ...         browser.contents, "msgset_140_es_translation_0"
    ...     ).decode_contents()
    ... )
    Foo

And the error is noted in the page.

    >>> for tag in find_tags_by_class(browser.contents, "error"):
    ...     print(tag)
    ...
    <div class="error message">There is an error in a translation you
      provided. Please correct it before continuing.</div>
    <tr class="error translation">
      <th colspan="3">
        <strong>Error in Translation:</strong>
      </th>
      <td></td>
      <td>
        <div>
          format specifications in 'msgid' and 'msgstr' for argument 1 are not
          the same
        </div>
      </td>
    </tr>
