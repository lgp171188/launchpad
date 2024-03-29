Package branch merging with product branches
============================================

If the source package is linked to the product, then package branches for that
source package are allowed to be proposed for merging into product branches
and vice versa.

    >>> login(ANONYMOUS)
    >>> eric = factory.makePerson(name="eric", email="eric@example.com")
    >>> b1 = factory.makePackageBranch(owner=eric)
    >>> b2 = factory.makeProductBranch(owner=eric)
    >>> b1_url = canonical_url(b1)
    >>> b1_name = b1.unique_name
    >>> b2_url = canonical_url(b2)
    >>> b2_name = b2.unique_name

XXX TimPenhey 2009-05-15 bug=376851
Need more than one package and product branch to show links.

    >>> ignored = factory.makePackageBranch(sourcepackage=b1.sourcepackage)
    >>> ignored = factory.makeProductBranch(product=b1.product)
    >>> logout()

If there is no link, you are not allowed to propose a package branch to merge
with a product branch.

    >>> browser = setupBrowser(auth="Basic eric@example.com:test")
    >>> browser.open(b1_url)
    >>> browser.getLink("Propose for merging").click()
    >>> browser.getControl(name="field.target_branch.target_branch").value = (
    ...     b2_name
    ... )
    >>> browser.getControl("Propose Merge").click()

    >>> print_errors(browser.contents)
    There is 1 error.
    Target branch:
    ...
    This branch is not mergeable into lp://dev/~eric/...
    ...

Linking the packages makes this possible.

    >>> ignored = login_person(eric)
    >>> b1.sourcepackage.setPackaging(b2.product.development_focus, eric)
    >>> logout()

    >>> browser.open(b1_url)
    >>> browser.getLink("Propose for merging").click()
    >>> browser.getControl(name="field.target_branch.target_branch").value = (
    ...     b2_name
    ... )
    >>> browser.getControl("Propose Merge").click()
