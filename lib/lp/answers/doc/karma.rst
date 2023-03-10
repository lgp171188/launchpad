Answer Tracker Karma
====================

To promote community contributions in the Launchpad Answer Tracker, it's
very important that we acknowledge their work and give them some karma
points.

These karma points are assigned to a user when they perform one of the
actions we consider to be a reasonable contribution.

    >>> from operator import attrgetter
    >>> from lp.registry.interfaces.person import IPersonSet
    >>> from lp.registry.interfaces.product import IProductSet
    >>> from lp.registry.model.karma import KarmaCategory
    >>> from lp.services.database.interfaces import IStore
    >>> answers_category = (
    ...     IStore(KarmaCategory).find(KarmaCategory, name="answers").one()
    ... )
    >>> answers_karma_actions = answers_category.karmaactions
    >>> for action in sorted(answers_karma_actions, key=attrgetter("title")):
    ...     print(action.title)
    ...
    Answered question
    Asked question
    Comment made on a question
    FAQ created
    FAQ edited
    Gave answer on a question
    Gave more information on a question
    Question description changed
    Question linked to a bug
    Question owner accepted answer
    Question title changed
    Rejected question
    Reopened question
    Requested for information on a question
    Solved own question

    >>> person_set = getUtility(IPersonSet)
    >>> sample_person = person_set.getByEmail("test@canonical.com")
    >>> foo_bar = person_set.getByEmail("foo.bar@canonical.com")

Setup an event listener to help ensure karma is assigned when it should.

    >>> from lp.testing.karma import KarmaAssignedEventListener
    >>> karma_helper = KarmaAssignedEventListener(show_person=True)
    >>> karma_helper.register_listener()

Define a generator that always give a date higher than the previous one
to order our messages.

    >>> from datetime import datetime, timedelta, timezone
    >>> def timegenerator(origin):
    ...     now = origin
    ...     while True:
    ...         now += timedelta(seconds=5)
    ...         yield now
    ...
    >>> now = timegenerator(datetime.now(timezone.utc))


Karma Actions
-------------


Creating a question
...................

    >>> login("test@canonical.com")
    >>> firefox = getUtility(IProductSet)["firefox"]
    >>> firefox_question = firefox.newQuestion(
    ...     title="New question",
    ...     description="Question description.",
    ...     owner=sample_person,
    ...     datecreated=next(now),
    ... )
    Karma added: action=questionasked, product=firefox, person=name12


Expiring a question
...................

The expireQuestion() workflow method doesn't grant any karma because it
will usually be called by an automated script.

    >>> msg = firefox_question.expireQuestion(
    ...     foo_bar,
    ...     "Expiring because of inactivity. Reopen if you are "
    ...     "still having the problem and provide additional information.",
    ...     datecreated=next(now),
    ... )


Reopening a question
....................

    >>> msg = firefox_question.reopen(
    ...     "Firefox doesn't have any 'Quick Searches' in its bookmarks.",
    ...     datecreated=next(now),
    ... )
    Karma added: action=questionreopened, product=firefox, person=name12


Requesting for more information
...............................

    >>> msg = firefox_question.requestInfo(
    ...     foo_bar,
    ...     'What "Quick Searches" do you want?',
    ...     datecreated=next(now),
    ... )
    Karma added: action=questionrequestedinfo, product=firefox, person=name16


Giving back more information
............................

    >>> msg = firefox_question.giveInfo(
    ...     "The same one than shipped upstreams.", datecreated=next(now)
    ... )
    Karma added: action=questiongaveinfo, product=firefox, person=name12


Giving an answer to a question
..............................

    >>> msg = firefox_question.giveAnswer(
    ...     foo_bar,
    ...     "Ok, I see what you mean. You need to install them "
    ...     "manually for now.",
    ...     datecreated=next(now),
    ... )
    Karma added: action=questiongaveanswer, product=firefox, person=name16


Adding a comment
................

    >>> msg = firefox_question.addComment(
    ...     foo_bar,
    ...     "You could also fill a bug about that, if you like.",
    ...     datecreated=next(now),
    ... )
    Karma added: action=questioncommentadded, product=firefox, person=name16


Confirming that the problem is solved
.....................................

When the user confirms that their problem is solved, karma will be given
for accepting an answer. The person whose answer was accepted will also
receives karma.

    >>> msg = firefox_question.confirmAnswer(
    ...     "Ok, thanks. I'll open a bug about this then.",
    ...     answer=msg,
    ...     datecreated=next(now),
    ... )
    Karma added: action=questionansweraccepted, product=firefox, person=name12
    Karma added: action=questionanswered, product=firefox, person=name16


Rejecting a question
....................

    >>> msg = firefox_question.reject(
    ...     foo_bar, "This should really be a bug report."
    ... )
    Karma added: action=questionrejected, product=firefox, person=name16


Changing the status
...................

We do not grant karma for status change made outside of workflow:

    >>> login("foo.bar@canonical.com")
    >>> from lp.answers.enums import QuestionStatus
    >>> msg = firefox_question.setStatus(
    ...     foo_bar,
    ...     QuestionStatus.OPEN,
    ...     "That rejection was an error.",
    ...     datecreated=next(now),
    ... )


Changing the title of a question
................................

    >>> from lp.services.webapp.snapshot import notify_modified
    >>> login("test@canonical.com")
    >>> with notify_modified(firefox_question, ["title"]):
    ...     firefox_question.title = (
    ...         'Firefox 1.5.0.5 does not have any "Quick Searches" '
    ...         "installed by default"
    ...     )
    ...
    Karma added: action=questiontitlechanged, product=firefox, person=name12


Changing the description of a question
......................................

    >>> with notify_modified(firefox_question, ["description"]):
    ...     firefox_question.description = (
    ...         'Firefox 1.5.0.5 does not have any "Quick Searches" '
    ...         "installed in the bookmarks by default, like the official "
    ...         "ones do."
    ...     )
    ...
    Karma added: action=questiondescriptionchanged, product=firefox,
        person=name12


Linking to a bug
................

    >>> from lp.bugs.model.bug import Bug
    >>> questionbug = firefox_question.linkBug(Bug.get(5))
    Karma added: action=questionlinkedtobug, product=firefox, person=name12


Solving own problem
...................

There is a special karma action to cover the case when the question
owner comes back to provide an answer to their own problem. We no longer
award karma for the questionownersolved action. It remains among the
answers karma actions so that we can continue to calculate karma for
persons who were awarded it in the past.

    # This test must have no output

    >>> msg = firefox_question.giveAnswer(
    ...     sample_person,
    ...     "I was able to import some by following the "
    ...     "instructions on http://tinyurl.com/cyus4",
    ...     datecreated=next(now),
    ... )


Creating a FAQ
..............

    >>> firefox_faq = firefox.newFAQ(
    ...     sample_person, "A FAQ", "About something important"
    ... )
    Karma added: action=faqcreated, product=firefox, person=name12


Modifying a FAQ
...............

    >>> with notify_modified(firefox_faq, ["title", "content"]):
    ...     firefox_faq.title = "How can I make the Fnord appears?"
    ...     firefox_faq.content = "Install the Fnords highlighter extensions."
    ...
    Karma added: action=faqedited, product=firefox, person=name12


Final check and tear down
-------------------------

Now we do a check to make sure all current Answer Tracker related karma
actions have been tested. Only the obsolete methods remain.

    >>> added_karma_actions = karma_helper.added_karma_actions
    >>> obsolete_actions = set(answers_karma_actions) - added_karma_actions
    >>> for action in obsolete_actions:
    ...     print(action.title)
    ...
    Solved own question

    # Unregister the event listener to make sure we won't interfere in
    # other tests.

    >>> karma_helper.unregister_listener()


