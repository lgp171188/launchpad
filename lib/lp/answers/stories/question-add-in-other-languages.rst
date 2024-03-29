Asking questions in languages other than English
================================================

It is possible to ask questions in a language other than English. The
'Ask a question' page has a pop-up where the user can select the language
of the question. By default, the question language is 'English'.

    >>> user_browser.open("http://launchpad.test/ubuntu/+questions")
    >>> user_browser.getLink("Ask a question").click()
    >>> user_browser.getControl("Language").value
    ['en']

The user may choose from any of their preferred languages and there is a
link to enable to change their preferred languages:

    >>> user_browser.getLink("Change your preferred languages").click()
    >>> print(user_browser.title)
    Language preferences...
    >>> user_browser.url
    '.../~no-priv/+editlanguages'

The languages that are supported are displayed with an asterisk.

    >>> browser.addHeader("Authorization", "Basic salgado@ubuntu.com:test")
    >>> browser.open("http://launchpad.test/ubuntu/+addquestion")

    >>> browser.getControl("Language").displayOptions
    ['English (en) *', 'Portuguese (Brazil) (pt_BR)']

Although it's possible to ask questions in any of the user's preferred
languages, we need to do some checks to warn the user in case they're using
a language that is not spoken/understood by any of the context's answer
contacts.

    >>> browser.getControl("Language").value = ["pt_BR"]
    >>> browser.getControl("Summary").value = (
    ...     "Abrir uma pagina que requer java quebra o firefox"
    ... )
    >>> browser.getControl("Continue").click()

At this point we'll present any similar questions (in any language)
/and/ a warning message explaining that the chosen language is not
understood by any member of the support community.

    >>> similar_questions = find_tag_by_id(
    ...     browser.contents, "similar-questions"
    ... )

    XXX: Making search fast has a significant impact on this tests' use case,
    because there are 9 terms - the query has to ignore 7 of the terms to
    permit a hit under the new & based logic (which is needed for scaling).
    When we push better relevance and cheap ordering into the core we will be
    able to test this case again. Note that in production this exact use case
    already finds nothing.

    #>>> for row in similar_questions.find_all('tr', 'noted'):
    #...     row.find('a').decode_contents()
    #'Installation of Java Runtime Environment for Mozilla'
    #'Problema al recompilar kernel con soporte smp (doble-n\xc3\xbacleo)'

    >>> for tag in find_tags_by_class(browser.contents, "warning message"):
    ...     print(tag.decode_contents())
    ...
    <strong>Portuguese (Brazil) (pt_BR)</strong> doesn't seem to be
    a language spoken by any answer contacts in this community. If you
    go ahead and ask a question in that language, no answer
    contacts will be able to read it. Currently, the languages spoken
    by at least one answer contact are: English.

The user can still use the 'Change preferred language' link to change
the list of available languages:

    >>> browser.getLink("Change your preferred languages").url
    '.../+editmylanguages'

Since we've already shown the warning, we won't try to block the user
from asking a question in the language of their choice.

    >>> browser.getControl("Language").value
    ['pt_BR']
    >>> browser.getControl("Description").value = (
    ...     "Eu uso Ubuntu em um AMD64 e instalei o plugin java blackdown. "
    ...     "O plugin \xe9 exibido em about:plugins e quando eu abro a "
    ...     "pagina http://java.com/en/download/help/testvm.xml, ela "
    ...     "carrega corretamente e mostra a minha versao do java. No "
    ...     "entanto, mover o mouse na pagina faz com que o firefox quebre."
    ... ).encode("utf-8")
    >>> browser.getControl("Post Question").click()
    >>> browser.url
    '.../ubuntu/+question/...'
    >>> print(browser.title)
    Question #... : Questions : Ubuntu

The page reports the question language both in the content and in the
markup. Search engine robots and browsers will use the lang and dir
attributes for indexing and rendering respectively. Users will find
the language in the question details portlet.

    >>> from lp.services.beautifulsoup import BeautifulSoup
    >>> soup = BeautifulSoup(browser.contents)
    >>> print(soup.find("div", id="question")["lang"])
    pt-BR
    >>> print(soup.html["dir"])
    ltr
    >>> print(extract_text(find_tag_by_id(soup, "question-lang")))
    Language: Portuguese (Brazil) ...

It's also possible that the user chose English in the first page but
then changed their mind on the second page.

    >>> browser = setupBrowser(auth="Basic daf@canonical.com:test")
    >>> browser.open("http://launchpad.test/ubuntu/+addquestion")

    >>> browser.getControl("Language").value = ["en"]
    >>> browser.getControl("Summary").value = "some random words"
    >>> browser.getControl("Continue").click()

In this case they won't be warned, because we assume all members of the
support community can understand English.

    >>> len(find_tags_by_class(browser.contents, "warning message"))
    0

If now they change their mind and decides to enter the question details in
Welsh, we'll have to warn them.

    >>> browser.getControl("Language").value = ["cy"]
    >>> browser.getControl("Summary").value = "Gofyn cymorth"
    >>> browser.getControl("Description").value = "Ghai damweiniol gair."
    >>> browser.getControl("Post Question").click()

    >>> browser.url
    'http://launchpad.test/ubuntu/+addquestion'

    >>> for tag in find_tags_by_class(browser.contents, "warning message"):
    ...     print(tag.decode_contents())
    ...
    <strong>Welsh (cy)</strong> doesn't seem to be
    a language spoken by any answer contacts in this community. If you
    go ahead and ask a question in that language, no answer
    contacts will be able to read it. Currently, the languages spoken
    by at least one answer contact are: English.

If they change the language to another unsupported language, we will
display the warning again.

    >>> browser.getControl("Language").value = ["ja"]
    >>> browser.getControl("Summary").value = (
    ...     "\u52a9\u3051\u306e\u8981\u6c42".encode("utf-8")
    ... )
    >>> browser.getControl("Description").value = (
    ...     "\u3042\u308b\u4efb\u610f\u5358\u8a9e\u3002".encode("utf-8")
    ... )
    >>> browser.getControl("Post Question").click()

    >>> for tag in find_tags_by_class(browser.contents, "warning message"):
    ...     print(tag.decode_contents())
    ...
    <strong>Japanese (ja)</strong> doesn't seem to be
    a language spoken by any answer contacts in this community. If you
    go ahead and ask a question in that language, no answer
    contacts will be able to read it. Currently, the languages spoken
    by at least one answer contact are: English.

If even after the warning they decide to go ahead, we have to accept the
new question.

    >>> browser.getControl("Post Question").click()
    >>> browser.url
    '.../ubuntu/+question/...'
    >>> print(browser.title)
    Question #... : Questions : Ubuntu
    >>> portlet = find_tag_by_id(browser.contents, "portlet-details")
