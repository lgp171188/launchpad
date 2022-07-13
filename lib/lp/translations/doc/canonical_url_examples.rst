Translations URLs
=================

Here we document what URLs different Translations-related objects use.

    >>> from zope.component import getUtility
    >>> from lp.services.webapp import canonical_url

Homepage
--------

The Rosetta homepage.

    >>> from lp.translations.interfaces.translations import (
    ...     IRosettaApplication)
    >>> print(canonical_url(getUtility(IRosettaApplication)))
    http://launchpad.test/translations

POTemplates and POFiles
-----------------------

    >>> from lp.translations.interfaces.potemplate import IPOTemplateSet
    >>> from lp.translations.interfaces.translationgroup import (
    ...     ITranslationGroupSet)

Most Rosetta pages hang off IPOTemplateSubset objects, of which there are two
varieties: distribution and upstream.

First, the distribution kind.  We'll need the source package name.

    >>> from lp.registry.interfaces.sourcepackagename import (
    ...     ISourcePackageNameSet)
    >>> from lp.registry.interfaces.distribution import IDistributionSet
    >>> sourcepackagenameset = getUtility(ISourcePackageNameSet)
    >>> sourcepackagename = sourcepackagenameset['evolution']
    >>> distroset = getUtility(IDistributionSet)
    >>> ubuntu = distroset['ubuntu']
    >>> hoary = ubuntu.getSeries('hoary')

And here's our subset.

    >>> potemplateset = getUtility(IPOTemplateSet)
    >>> potemplatesubset = potemplateset.getSubset(
    ...     distroseries=hoary, sourcepackagename=sourcepackagename)

    >>> print(canonical_url(potemplatesubset))
    http://launchpad.test/ubuntu/hoary/+source/evolution/+pots

We can get a particular PO template for this source package by its PO template
name.

    >>> potemplate = potemplatesubset['evolution-2.2']
    >>> print(canonical_url(potemplate))
    http://translations.../hoary/+source/evolution/+pots/evolution-2.2

And we can get a particular PO file for this PO template by its language code.

    >>> pofile = potemplate.getPOFileByLang('es')
    >>> print(canonical_url(pofile))
    http://translations.../hoary/+source/evolution/+pots/evolution-2.2/es

Also, we can get the url to a translation message.

    >>> potmsgset = potemplate.getPOTMsgSetBySequence(1)
    >>> translationmessage = potmsgset.getCurrentTranslation(
    ...     pofile.potemplate, pofile.language, potemplate.translation_side)
    >>> translationmessage.setPOFile(pofile)
    >>> print(canonical_url(translationmessage))
    http://transl.../hoary/+source/evolution/+pots/evolution-2.2/es/1

Even for a dummy one.

    >>> potmsgset = potemplate.getPOTMsgSetBySequence(20)
    >>> translationmessage = potmsgset.getCurrentTranslationMessageOrDummy(
    ...     pofile)
    >>> print(canonical_url(translationmessage))
    http://transl.../hoary/+source/evolution/+pots/evolution-2.2/es/20

Upstream POTemplateSubsets work in much the same way, except they hang off a
product series.  Let's get a product series.

Now we can get an upstream subset and do the same sorts of thing as we did
with the distro subset.

    >>> from lp.registry.interfaces.product import IProductSet
    >>> productset = getUtility(IProductSet)
    >>> evolution_product = productset['evolution']
    >>> evolution_trunk_series = evolution_product.getSeries('trunk')

    >>> potemplatesubset = potemplateset.getSubset(
    ...     productseries=evolution_trunk_series)
    >>> potemplate = potemplatesubset['evolution-2.2']
    >>> print(canonical_url(potemplate))
    http://translations.launchpad.test/evolution/trunk/+pots/evolution-2.2

    >>> pofile = potemplate.getPOFileByLang('es')
    >>> print(canonical_url(pofile))
    http://translations.../evolution/trunk/+pots/evolution-2.2/es

Also, we can get the url to a dummy one

    >>> potmsgset = potemplate.getPOTMsgSetBySequence(1)
    >>> translationmessage = potmsgset.getCurrentTranslation(
    ...     pofile.potemplate, pofile.language, potemplate.translation_side)
    >>> translationmessage.setPOFile(pofile)
    >>> print(canonical_url(translationmessage))
    http://translations.../evolution/trunk/+pots/evolution-2.2/es/1

Even for a dummy PO msgset

    >>> potmsgset = potemplate.getPOTMsgSetBySequence(20)
    >>> translationmessage = potmsgset.getCurrentTranslationMessageOrDummy(
    ...     pofile)
    >>> print(canonical_url(translationmessage))
    http://translations.../evolution/trunk/+pots/evolution-2.2/es/20


Translation groups
------------------

Rosetta also has translation groups.

    >>> print(canonical_url(getUtility(ITranslationGroupSet)))
    http://translations.launchpad.test/+groups

    >>> print(canonical_url(factory.makeTranslationGroup(name='test')))
    http://translations.launchpad.test/+groups/test


Distribution, DistroSeries and DistroSeriesLanguage
---------------------------------------------------

Distribution and distribution series default to the main vhost.

    >>> distribution = factory.makeDistribution(
    ...     name='boo')
    >>> print(canonical_url(distribution))
    http://launchpad.test/boo

    >>> distroseries = factory.makeDistroSeries(
    ...     name='bah', distribution=distribution)
    >>> print(canonical_url(distroseries))
    http://launchpad.test/boo/bah

DistroSeriesLanguage objects have their URLs on translations vhost.

    >>> from lp.services.worlddata.interfaces.language import ILanguageSet
    >>> from lp.translations.interfaces.distroserieslanguage import (
    ...     IDistroSeriesLanguageSet)
    >>> serbian = getUtility(ILanguageSet)['sr']

    >>> boo_bah_serbian = getUtility(IDistroSeriesLanguageSet).getEmpty(
    ...     distroseries, serbian)
    >>> print(canonical_url(boo_bah_serbian))
    http://translations.launchpad.test/boo/bah/+lang/sr

Product, ProductSeries and ProductSeriesLanguage
---------------------------------------------------

Product and product series default to the main vhost.

    >>> product = factory.makeProduct(
    ...     name='coo')
    >>> print(canonical_url(product))
    http://launchpad.test/coo

    >>> productseries = factory.makeProductSeries(
    ...     name='cah', product=product)
    >>> print(canonical_url(productseries))
    http://launchpad.test/coo/cah

ProductSeriesLanguage objects have their URLs on translations vhost.

    >>> from lp.translations.interfaces.productserieslanguage import (
    ...     IProductSeriesLanguageSet)

    >>> psl_set = getUtility(IProductSeriesLanguageSet)
    >>> coo_cah_serbian = psl_set.getProductSeriesLanguage(
    ...     productseries, serbian)
    >>> print(canonical_url(coo_cah_serbian))
    http://translations.launchpad.test/coo/cah/+lang/sr
