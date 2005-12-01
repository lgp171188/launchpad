# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

__metaclass__ = type

__all__ = ['ProductSeriesNavigation',
           'ProductSeriesContextMenu',
           'ProductSeriesView',
           'ProductSeriesRdfView',
           'ProductSeriesSourceSetView',
           'ProductSeriesReviewView']

import re
import urllib

from zope.component import getUtility
from zope.exceptions import NotFoundError
from zope.app.pagetemplate.viewpagetemplatefile import ViewPageTemplateFile

from CVS.protocol import CVSRoot
import pybaz

from canonical.lp.z3batching import Batch
from canonical.lp.batching import BatchNavigator
from canonical.lp.dbschema import ImportStatus, RevisionControlSystems

from canonical.launchpad.helpers import request_languages, browserLanguages
from canonical.launchpad.interfaces import (
    IPerson, ICountry, IPOTemplateSet, ILaunchpadCelebrities, ILaunchBag,
    ISourcePackageNameSet, validate_url, IProductSeries)
from canonical.launchpad.browser.potemplate import POTemplateView
from canonical.launchpad.browser.editview import SQLObjectEditView
from canonical.launchpad.webapp import (
    ContextMenu, Link, enabled_with_permission, Navigation, GetitemNavigation,
    stepto, canonical_url)

from canonical.launchpad import _

class ProductSeriesReviewView(SQLObjectEditView):
    def changed(self):
        """Redirect to the productseries page.

        We need this because people can now change productseries'
        product and name, and this will make their canonical_url to
        change too.         
        """
        self.request.response.addInfoNotification( 
            _('This Serie has been changed'))
        self.request.response.redirect(canonical_url(self.context))

class ProductSeriesNavigation(Navigation):

    usedfor = IProductSeries

    @stepto('+pots')
    def pots(self):
        potemplateset = getUtility(IPOTemplateSet)
        return potemplateset.getSubset(productseries=self.context)

    def traverse(self, name):
        return self.context.getRelease(name)


class ProductSeriesContextMenu(ContextMenu):

    usedfor = IProductSeries
    links = ['overview', 'specs', 'edit', 'editsource', 'ubuntupkg',
             'addpackage', 'addrelease', 'download', 'addpotemplate',
             'review']

    def overview(self):
        text = 'Series Overview'
        return Link('', text, icon='info')

    def specs(self):
        text = 'Show Specifications'
        return Link('+specs', text, icon='info')

    def edit(self):
        text = 'Edit Series Details'
        return Link('+edit', text, icon='edit')

    def editsource(self):
        text = 'Edit Source'
        return Link('+source', text, icon='edit')

    def ubuntupkg(self):
        text = 'Link to Ubuntu Package'
        return Link('+ubuntupkg', text, icon='edit')

    def addpackage(self):
        text = 'Link to Any Package'
        return Link('+addpackage', text, icon='edit')

    def addrelease(self):
        text = 'Register New Release'
        return Link('+addrelease', text, icon='edit')

    def download(self):
        text = 'Download RDF Metadata'
        return Link('+rdf', text, icon='download')

    @enabled_with_permission('launchpad.Admin')
    def addpotemplate(self):
        text = 'Add Translation Template'
        return Link('+addpotemplate', text, icon='add')

    @enabled_with_permission('launchpad.Admin')
    def review(self):
        text = 'Review Series Details'
        return Link('+review', text, icon='edit')


def validate_cvs_root(cvsroot, cvsmodule):
    try:
        root = CVSRoot(cvsroot + '/' + cvsmodule)
    except ValueError:
        return False
    valid_module = re.compile('^[a-zA-Z][a-zA-Z0-9_/.+-]*$')
    if not valid_module.match(cvsmodule):
        return False
    # 'CVS' is illegal as a module name
    if cvsmodule == 'CVS':
        return False
    if root.method == 'local' or root.hostname.count('.') == 0:
        return False
    return True

def validate_cvs_branch(branch):
    if not len(branch):
        return False
    valid_branch = re.compile('^[a-zA-Z][a-zA-Z0-9_-]*$')
    if valid_branch.match(branch):
        return True
    return False

def validate_release_root(repo):
    return validate_url(repo, ["http", "https", "ftp"])

def validate_svn_repo(repo):
    return validate_url(repo, ["http", "https", "svn", "svn+ssh"])



# A View Class for ProductSeries
#
# XXX: We should be using autogenerated add forms and edit forms so that
# this becomes maintainable and form validation handled for us.
# Currently, the pages just return 'System Error' as they trigger database
# constraints. -- StuartBishop 20050502
class ProductSeriesView(object):

    def __init__(self, context, request):
        self.context = context
        self.product = context.product
        self.request = request
        self.form = request.form
        self.user = getUtility(ILaunchBag).user
        self.errormsgs = []
        self.displayname = self.context.displayname
        self.summary = self.context.summary
        self.rcstype = self.context.rcstype
        self.cvsroot = self.context.cvsroot
        self.cvsmodule = self.context.cvsmodule
        self.cvsbranch = self.context.cvsbranch
        self.svnrepository = self.context.svnrepository
        self.releaseroot = self.context.releaseroot
        self.releasefileglob = self.context.releasefileglob
        self.targetarcharchive = self.context.targetarcharchive
        self.targetarchcategory = self.context.targetarchcategory
        self.targetarchbranch = self.context.targetarchbranch
        self.targetarchversion = self.context.targetarchversion
        self.name = self.context.name
        if self.context.product.project:
            self.default_targetarcharchive = self.context.product.project.name
            self.default_targetarcharchive += '@bazaar.ubuntu.com'
        else:
            self.default_targetarcharchive = self.context.product.name
            self.default_targetarcharchive += '@bazaar.ubuntu.com'
        self.default_targetarchcategory = self.context.product.name
        if self.cvsbranch:
            self.default_targetarchbranch = self.cvsbranch
        else:
            self.default_targetarchbranch = self.context.name
        self.default_targetarchversion = '0'
        # List of languages the user is interested on based on their browser,
        # IP address and launchpad preferences.
        self.languages = request_languages(self.request)
        # Whether there is more than one PO template.
        self.has_multiple_templates = len(self.context.currentpotemplates) > 1

        # let's find out what source package is associated with this
        # productseries in the current release of ubuntu
        ubuntu = getUtility(ILaunchpadCelebrities).ubuntu
        self.curr_ubuntu_release = ubuntu.currentrelease
        self.setUpPackaging()

    def templateviews(self):
        return [POTemplateView(template, self.request)
                for template in self.context.currentpotemplates]

    def setUpPackaging(self):
        """Ensure that the View class correctly reflects the packaging of
        its product series context."""
        self.curr_ubuntu_package = None
        self.curr_ubuntu_pkgname = ''
        try:
            cr = self.curr_ubuntu_release
            self.curr_ubuntu_package = self.context.getPackage(cr)
            cp = self.curr_ubuntu_package
            self.curr_ubuntu_pkgname = cp.sourcepackagename.name
        except NotFoundError:
            pass
        ubuntu = self.curr_ubuntu_release.distribution
        self.ubuntu_history = self.context.getPackagingInDistribution(ubuntu)

    def namesReviewed(self):
        if not (self.product.active and self.product.reviewed):
            return False
        if not self.product.project:
            return True
        return self.product.project.active and self.product.project.reviewed

    def rcs_selector(self):
        html = '<select name="rcstype">\n'
        html += '  <option value="cvs" onClick="morf(\'cvs\')"'
        if self.rcstype == RevisionControlSystems.CVS:
            html += ' selected'
        html += '>CVS</option>\n'
        html += '  <option value="svn" onClick="morf(\'svn\')"'
        if self.rcstype == RevisionControlSystems.SVN:
            html += ' selected'
        html += '>Subversion</option>\n'
        html += '</select>\n'
        return html

    def edit(self):
        """
        Update the contents of the ProductSeries. This method is called by a
        tal:dummy element in a page template. It checks to see if a form has
        been submitted that has a specific element, and if so it continues
        to process the form, updating the fields of the database as it goes.
        """
        # check that we are processing the correct form, and that
        # it has been POST'ed
        form = self.form
        if not form.get("Update", None)=="Update Series":
            return
        if not self.request.method == "POST":
            return
        # Extract details from the form and update the Product
        # we don't let people edit the name because it's part of the url
        self.name = form.get('name', self.name)
        self.displayname = form.get('displayname', self.displayname)
        self.summary = form.get('summary', self.summary)
        self.releaseroot = form.get("releaseroot", self.releaseroot) or None
        self.releasefileglob = form.get("releasefileglob",
                self.releasefileglob) or None
        if self.releaseroot:
            if not validate_release_root(self.releaseroot):
                self.errormsgs.append('Invalid release root URL')
                return
        self.context.name = self.name
        self.context.summary = self.summary
        self.context.displayname = self.displayname
        self.context.releaseroot = self.releaseroot
        self.context.releasefileglob = self.releasefileglob
        # now redirect to view the productseries
        self.request.response.redirect(
            '../%s' % urllib.quote(self.context.name))

    def editSource(self, fromAdmin=False):
        """This method processes the results of an attempt to edit the
        upstream revision control details for this series."""
        # see if anything was posted
        if self.request.method != "POST":
            return
        form = self.form
        if form.get("Update RCS Details", None) is None:
            return
        if self.context.syncCertified() and not fromAdmin:
            self.errormsgs.append(
                    'This Source is has been certified and is now '
                    'unmodifiable.'
                    )
            return
        # get the form content, defaulting to what was there
        rcstype=form.get("rcstype", None)
        if rcstype == 'cvs':
            self.rcstype = RevisionControlSystems.CVS
        elif rcstype == 'svn':
            self.rcstype = RevisionControlSystems.SVN
        else:
            raise NotImplementedError, 'Unknown RCS %s' % rcstype
        self.cvsroot = form.get("cvsroot", self.cvsroot).strip() or None
        self.cvsmodule = form.get("cvsmodule", self.cvsmodule).strip() or None
        self.cvsbranch = form.get("cvsbranch", self.cvsbranch).strip() or None
        self.svnrepository = form.get("svnrepository",
                self.svnrepository).strip() or None
        # make sure we at least got something for the relevant rcs
        if rcstype == 'cvs':
            if not (self.cvsroot and self.cvsmodule and self.cvsbranch):
                if not fromAdmin:
                    self.errormsgs.append('Please give valid CVS details')
                return
            if not validate_cvs_branch(self.cvsbranch):
                self.errormsgs.append('Your CVS branch name is invalid.')
                return
            if not validate_cvs_root(self.cvsroot, self.cvsmodule):
                self.errormsgs.append('Your CVS root and module are invalid.')
                return
            if self.svnrepository:
                self.errormsgs.append('Please remove the SVN repository.')
                return
        elif rcstype == 'svn':
            if not validate_svn_repo(self.svnrepository):
                self.errormsgs.append('Please give valid SVN server details')
                return
            if (self.cvsroot or self.cvsmodule or self.cvsbranch):
                self.errormsgs.append(
                    'Please remove the CVS repository details.')
                return
        oldrcstype = self.context.rcstype
        self.context.rcstype = self.rcstype
        self.context.cvsroot = self.cvsroot
        self.context.cvsmodule = self.cvsmodule
        self.context.cvsbranch = self.cvsbranch
        self.context.svnrepository = self.svnrepository
        if not fromAdmin:
            self.context.importstatus = ImportStatus.TESTING
        elif (oldrcstype is None and self.rcstype is not None):
            self.context.importstatus = ImportStatus.TESTING
        # make sure we also update the ubuntu packaging if it has been
        # modified
        self.setCurrentUbuntuPackage()

    def adminSource(self):
        """Make administrative changes to the source details of the
        upstream. Since this is a superset of the editing function we can
        call the edit method of the view class to get any editing changes,
        then continue parsing the form here, looking for admin-type
        changes."""
        # see if anything was posted
        if self.request.method != "POST":
            return
        form = self.form
        if form.get("Update RCS Details", None) is None:
            return
        # FTP release details
        self.releaseroot = form.get("releaseroot", self.releaseroot) or None
        self.releasefileglob = form.get("releasefileglob",
                self.releasefileglob) or None
        if self.releaseroot:
            if not validate_release_root(self.releaseroot):
                self.errormsgs.append('Invalid release root URL')
                return
        # look for admin changes and retrieve those
        self.cvsroot = form.get('cvsroot', self.cvsroot) or None
        self.cvsmodule = form.get('cvsmodule', self.cvsmodule) or None
        self.cvsbranch = form.get('cvsbranch', self.cvsbranch) or None
        self.svnrepository = form.get(
            'svnrepository', self.svnrepository) or None
        self.targetarcharchive = form.get(
            'targetarcharchive', self.targetarcharchive).strip() or None
        self.targetarchcategory = form.get(
            'targetarchcategory', self.targetarchcategory).strip() or None
        self.targetarchbranch = form.get(
            'targetarchbranch', self.targetarchbranch).strip() or None
        self.targetarchversion = form.get(
            'targetarchversion', self.targetarchversion).strip() or None
        # validate arch target details
        if not pybaz.NameParser.is_archive_name(self.targetarcharchive):
            self.errormsgs.append('Invalid target Arch archive name.')
        if not pybaz.NameParser.is_category_name(self.targetarchcategory):
            self.errormsgs.append('Invalid target Arch category.')
        if not pybaz.NameParser.is_branch_name(self.targetarchbranch):
            self.errormsgs.append('Invalid target Arch branch name.')
        if not pybaz.NameParser.is_version_id(self.targetarchversion):
            self.errormsgs.append('Invalid target Arch version id.')

        # possibly resubmit for testing
        if self.context.autoTestFailed() and form.get('resetToAutotest', False):
            self.context.importstatus = ImportStatus.TESTING

        # Return if there were any errors, so as not to update anything.
        if self.errormsgs:
            return
        # update the database
        self.context.targetarcharchive = self.targetarcharchive
        self.context.targetarchcategory = self.targetarchcategory
        self.context.targetarchbranch = self.targetarchbranch
        self.context.targetarchversion = self.targetarchversion
        self.context.releaseroot = self.releaseroot
        self.context.releasefileglob = self.releasefileglob
        # find and handle editing changes
        self.editSource(fromAdmin=True)
        if self.form.get('syncCertified', None):
            if not self.context.syncCertified():
                self.context.certifyForSync()
        if self.form.get('autoSyncEnabled', None):
            if not self.context.autoSyncEnabled():
                self.context.enableAutoSync()

    def setCurrentUbuntuPackage(self):
        """Sets the Packaging record for this product series in the current
        Ubuntu distrorelease to be for the source package name that is given
        in the form.
        """
        # see if anything was posted
        if self.request.method != "POST":
            return
        form = self.form
        ubuntupkg = form.get("ubuntupkg", '')
        if ubuntupkg == '':
            return
        # make sure we have a person to work with
        if self.user is None:
            self.errormsgs.append('Please log in first!')
            return
        # see if the name that is given is a real source package name
        spns = getUtility(ISourcePackageNameSet)
        try:
            spn = spns[ubuntupkg]
        except NotFoundError:
            self.errormsgs.append('Invalid source package name %s' % ubuntupkg)
            return
        # set the packaging record for this productseries in the current
        # ubuntu release. if none exists, one will be created
        self.context.setPackaging(self.curr_ubuntu_release, spn, self.user)
        self.setUpPackaging()

    def requestCountry(self):
        return ICountry(self.request, None)

    def browserLanguages(self):
        return browserLanguages(self.request)


class ProductSeriesRdfView(object):
    """A view that sets its mime-type to application/rdf+xml"""

    template = ViewPageTemplateFile(
        '../templates/productseries-rdf.pt')

    def __init__(self, context, request):
        self.context = context
        self.request = request

    def __call__(self):
        """Render RDF output, and return it as a string encoded in UTF-8.

        Render the page template to produce RDF output.
        The return value is string data encoded in UTF-8.

        As a side-effect, HTTP headers are set for the mime type
        and filename for download."""
        self.request.response.setHeader('Content-Type', 'application/rdf+xml')
        self.request.response.setHeader('Content-Disposition',
                                        'attachment; filename=%s-%s.rdf' % (
                                            self.context.product.name,
                                            self.context.name))
        unicodedata = self.template()
        encodeddata = unicodedata.encode('utf-8')
        return encodeddata


class ProductSeriesSourceSetView:
    """This is a view class that supports a page listing all the
    productseries upstream code imports. This used to be the SourceSource
    table but the functionality was largely merged into ProductSeries, hence
    the need for this View class.
    """

    def __init__(self, context, request):
        self.context = context
        self.request = request
        self.ready = request.form.get('ready', None)
        self.text = request.form.get('text', None)
        try:
            self.importstatus = int(request.form.get('state', None))
        except (ValueError, TypeError):
            self.importstatus = None
        # setup the initial values if there was no form submitted
        if request.form.get('search', None) is None:
            self.ready = 'on'
            self.importstatus = ImportStatus.TESTING.value
        self.batch = Batch(self.search(), int(request.get('batch_start', 0)))
        self.batchnav = BatchNavigator(self.batch, request)

    def search(self):
        return list(self.context.search(ready=self.ready,
                                        text=self.text,
                                        forimport=True,
                                        importstatus=self.importstatus))

    def sourcestateselector(self):
        html = '<select name="state">\n'
        html += '  <option value="ANY"'
        if self.importstatus == None:
            html += ' selected'
        html += '>Any</option>\n'
        for enum in ImportStatus.items:
            html += '<option value="'+str(enum.value)+'"'
            if self.importstatus == enum.value:
                html += ' selected'
            html += '>' + str(enum.title) + '</option>\n'
        html += '</select>\n'
        return html
        html += '  <option value="DONTSYNC"'
        if self.importstatus == 'DONTSYNC':
            html += ' selected'
        html += '>Do Not Sync</option>\n'
        html += '  <option value="TESTING"'
        if self.importstatus == 'TESTING':
            html += ' selected'
        html += '>Testing</option>\n'
        html += '  <option value="AUTOTESTED"'
        if self.importstatus == 'AUTOTESTED':
            html += ' selected'
        html += '>Auto-Tested</option>\n'
        html += '  <option value="PROCESSING"'
        if self.importstatus == 'PROCESSING':
            html += ' selected'
        html += '>Processing</option>\n'
        html += '  <option value="SYNCING"'
        if self.importstatus == 'SYNCING':
            html += ' selected'
        html += '>Syncing</option>\n'
        html += '  <option value="STOPPED"'
        if self.importstatus == 'STOPPED':
            html += ' selected'
        html += '>Stopped</option>\n'

