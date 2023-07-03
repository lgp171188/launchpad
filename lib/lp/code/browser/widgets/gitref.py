# Copyright 2015-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "GitRefWidget",
]

from zope.browserpage import ViewPageTemplateFile
from zope.formlib.interfaces import (
    ConversionError,
    IInputWidget,
    MissingInputError,
    WidgetInputError,
)
from zope.formlib.utility import setUpWidget
from zope.formlib.widget import BrowserWidget, InputErrors, InputWidget
from zope.interface import implementer
from zope.schema import Choice
from zope.schema.interfaces import IChoice

from lp.app.errors import UnexpectedFormData
from lp.app.validators import LaunchpadValidationError
from lp.app.widgets.popup import VocabularyPickerWidget
from lp.code.interfaces.gitrepository import IGitRepository
from lp.services.fields import URIField
from lp.services.webapp.interfaces import (
    IAlwaysSubmittedWidget,
    IMultiLineWidgetLayout,
)


class IGitRepositoryField(IChoice):
    pass


@implementer(IGitRepositoryField)
class GitRepositoryField(Choice):
    """A field identifying a Git repository.

    This may always be set to the unique name of a Launchpad-hosted
    repository.  If `allow_external` is True, then it may also be set to a
    valid external repository URL.
    """

    def __init__(self, allow_external=False, **kwargs):
        super().__init__(**kwargs)
        if allow_external:
            self._uri_field = URIField(
                __name__=self.__name__,
                title=self.title,
                allowed_schemes=["git", "http", "https"],
                allow_userinfo=True,
                allow_port=True,
                allow_query=False,
                allow_fragment=False,
                trailing_slash=False,
            )
        else:
            self._uri_field = None

    def set(self, object, value):
        if self._uri_field is not None and isinstance(value, str):
            try:
                self._uri_field.set(object, value)
                return
            except LaunchpadValidationError:
                pass
        super().set(object, value)

    def _validate(self, value):
        if self._uri_field is not None and isinstance(value, str):
            try:
                self._uri_field._validate(value)
                return
            except LaunchpadValidationError:
                pass
        super()._validate(value)


class GitRepositoryPickerWidget(VocabularyPickerWidget):
    def convertTokensToValues(self, tokens):
        if self.context._uri_field is not None:
            try:
                self.context._uri_field._validate(tokens[0])
                return [tokens[0]]
            except LaunchpadValidationError:
                pass
        return super().convertTokensToValues(tokens)


@implementer(IMultiLineWidgetLayout, IAlwaysSubmittedWidget, IInputWidget)
class GitRefWidget(BrowserWidget, InputWidget):
    template = ViewPageTemplateFile("templates/gitref.pt")
    _widgets_set_up = False

    # If True, allow entering external repository URLs.
    allow_external = False

    # If True, only allow reference paths to be branches (refs/heads/*).
    require_branch = False

    branch_validator = None

    def setUpSubWidgets(self):
        if self._widgets_set_up:
            return
        path_vocabulary = "GitBranch" if self.require_branch else "GitRef"
        fields = [
            GitRepositoryField(
                __name__="repository",
                title="Repository",
                required=self.context.required,
                vocabulary="GitRepository",
                allow_external=self.allow_external,
            ),
            Choice(
                __name__="path",
                title="Branch",
                required=self.context.required,
                vocabulary=path_vocabulary,
            ),
        ]
        for field in fields:
            setUpWidget(
                self, field.__name__, field, IInputWidget, prefix=self.name
            )
        self._widgets_set_up = True

    def setBranchFormatValidator(self, branch_validator):
        self.branch_validator = branch_validator

    def setRenderedValue(self, value, with_path=True):
        """See `IWidget`."""
        self.setUpSubWidgets()
        if value is not None:
            if self.allow_external and value.repository_url is not None:
                self.repository_widget.setRenderedValue(value.repository_url)
            else:
                self.repository_widget.setRenderedValue(value.repository)
            # if we're only talking about branches, we can deal in the
            # name, rather than the full ref/heads/* path
            if with_path:
                if self.require_branch:
                    self.path_widget.setRenderedValue(value.name)
                else:
                    self.path_widget.setRenderedValue(value.path)
        else:
            self.repository_widget.setRenderedValue(None)
            self.path_widget.setRenderedValue(None)

    def hasInput(self):
        """See `IInputWidget`."""
        return ("%s.repository" % self.name) in self.request.form or (
            "%s.path" % self.name
        ) in self.request.form

    def hasValidInput(self):
        """See `IInputWidget`."""
        try:
            self.getInputValue()
            return True
        except InputErrors:
            return False
        except UnexpectedFormData:
            return False

    def getInputValue(self):
        """See `IInputWidget`."""
        self.setUpSubWidgets()
        try:
            repository = self.repository_widget.getInputValue()
        except MissingInputError:
            if self.context.required:
                raise WidgetInputError(
                    self.name,
                    self.label,
                    LaunchpadValidationError(
                        "Please choose a Git repository."
                    ),
                )
            else:
                return None
        except ConversionError:
            entered_name = self.request.form_ng.getOne(
                "%s.repository" % self.name
            )
            raise WidgetInputError(
                self.name,
                self.label,
                LaunchpadValidationError(
                    "There is no Git repository named '%s' registered in "
                    "Launchpad." % entered_name
                ),
            )
        if self.path_widget.hasInput():
            # We've potentially just tried to change the repository that is
            # involved, or changing from a bzr branch to a git repo, so there
            # is no existing repository set up. We need to set this so we
            # can compare the ref against the 'new' repo.
            if IGitRepository.providedBy(repository):
                self.path_widget.vocabulary.setRepository(repository)
            else:
                self.path_widget.vocabulary.setRepositoryURL(repository)
            try:
                ref = self.path_widget.getInputValue()
            except ConversionError:
                raise WidgetInputError(
                    self.name,
                    self.label,
                    LaunchpadValidationError(
                        "The repository at %s does not contain a branch named "
                        "'%s'."
                        % (
                            repository.display_name,
                            self.path_widget._getFormInput(),
                        )
                    ),
                )
        else:
            ref = None
        if not ref and (repository or self.context.required):
            raise WidgetInputError(
                self.name,
                self.label,
                LaunchpadValidationError("Please enter a Git branch path."),
            )
        if self.branch_validator and ref is not None:
            valid, message = self.branch_validator(ref)
            if not valid:
                raise WidgetInputError(
                    self.name, self.label, LaunchpadValidationError(message)
                )
        return ref

    def error(self):
        """See `IBrowserWidget`."""
        try:
            if self.hasInput():
                self.getInputValue()
        except InputErrors as error:
            self._error = error
        return super().error()

    def __call__(self):
        """See `IBrowserWidget`."""
        self.setUpSubWidgets()
        return self.template()


class GitRefPickerWidget(VocabularyPickerWidget):
    __call__ = ViewPageTemplateFile("templates/gitref-picker.pt")

    @property
    def repository_id(self):
        return self._prefix + "repository"
