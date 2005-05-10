
# zope3
from zope.app.pagetemplate.viewpagetemplatefile import ViewPageTemplateFile
from zope.component import getUtility

# launchpad
from canonical.launchpad.interfaces import IPOTemplateSet

from canonical.launchpad import helpers

from canonical.launchpad.database import ProductRelease

from canonical.launchpad.browser.potemplate import ViewPOTemplate


def traverseProductRelease(productrelease, request, name):
    if name == '+pots':
        potemplateset = getUtility(IPOTemplateSet)
        return potemplateset.getSubset(productrelease=productrelease)
    else:
        return None


def newProductRelease(form, product, owner, series=None):
    """Process a form to create a new Product Release object."""
    # Verify that the form was in fact submitted, and that it looks like
    # the right form (by checking the contents of the submit button
    # field, called "Update").
    if not form.has_key('Register'): return
    if not form['Register'] == 'Register New Release': return
    # Extract the ProductRelease details, which are in self.form
    version = form['version']
    title = form['title']
    summary = form['summary']
    description = form['description']
    releaseurl = form['releaseurl']
    # series may be passed in arguments, or in the form
    if not series:
        if form.has_key('series'):
            series = int(form['series'])
    # Create the new ProductRelease
    productrelease = ProductRelease(
                          #product=product.id,
                          version=version,
                          title=title,
                          summary=summary,
                          description=description,
                          productseries=series,
                          owner=owner)
    return productrelease


class ProductReleaseView:
    """A View class for ProductRelease objects"""

    summaryPortlet = ViewPageTemplateFile(
        '../templates/portlet-object-summary.pt')

    detailsPortlet = ViewPageTemplateFile(
        '../templates/portlet-productrelease-details.pt')

    actionsPortlet = ViewPageTemplateFile(
        '../templates/portlet-product-actions.pt')

    statusLegend = ViewPageTemplateFile(
        '../templates/portlet-rosetta-status-legend.pt')

    prefLangPortlet = ViewPageTemplateFile(
        '../templates/portlet-pref-langs.pt')

    countryPortlet = ViewPageTemplateFile(
        '../templates/portlet-country-langs.pt')

    browserLangPortlet = ViewPageTemplateFile(
        '../templates/portlet-browser-langs.pt')

    def __init__(self, context, request):
        self.context = context
        self.request = request
        self.form = request.form
        # List of languages the user is interested on based on their browser,
        # IP address and launchpad preferences.
        self.languages = helpers.request_languages(self.request)
        self.status_message = None
        # Whether there is more than one PO template.
        self.has_multiple_templates = len(self.context.potemplates) > 1

    def edit(self):
        # check that we are processing the correct form, and that
        # it has been POST'ed
        if not self.form.get("Update", None)=="Update Release Details":
            return
        if not self.request.method == "POST":
            return
        # Extract details from the form and update the Product
        self.context.title = self.form['title']
        self.context.summary = self.form['summary']
        self.context.description = self.form['description']
        self.context.changelog = self.form['changelog']
        # now redirect to view the product
        self.request.response.redirect(self.request.URL[-1])

    def templateviews(self):
        return [ViewPOTemplate(template, self.request)
                for template in self.context.potemplates]

    def requestCountry(self):
        return helpers.requestCountry(self.request)

    def browserLanguages(self):
        return helpers.browserLanguages(self.request)

