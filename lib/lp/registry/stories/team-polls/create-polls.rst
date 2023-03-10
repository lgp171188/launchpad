Let's first setup some objects that we'll need.

    >>> no_priv_browser = setupBrowser(
    ...     auth="Basic no-priv@canonical.com:test"
    ... )
    >>> team_admin_browser = setupBrowser(
    ...     "Basic jeff.waugh@ubuntulinux.com:test"
    ... )

If you're not logged in and go to the +polls page of the "Ubuntu Team"
you'll see a link to login as a team administrator.

    >>> anon_browser.open("http://launchpad.test/~ubuntu-team")
    >>> anon_browser.getLink("Show polls").click()
    >>> anon_browser.url
    'http://launchpad.test/~ubuntu-team/+polls'
    >>> anon_browser.getLink("Log in as an admin to set up a new poll").url
    'http://launchpad.test/~ubuntu-team/+login'

Try to create a new poll logged in as 'no-priv', which is not a team
administrator. There's no link leading to the +newpoll page, but the user can
easily guess it.

    >>> no_priv_browser.open("http://launchpad.test/~ubuntu-team/+newpoll")
    Traceback (most recent call last):
    ...
    zope.security.interfaces.Unauthorized: ...

Now we're logged in as Jeff Waugh which is a team administrator and thus can
create a new poll.

    >>> team_admin_browser.open("http://launchpad.test/~ubuntu-team")
    >>> team_admin_browser.getLink("Show polls").click()
    >>> team_admin_browser.getLink("Set up a new poll").click()
    >>> team_admin_browser.url
    'http://launchpad.test/~ubuntu-team/+newpoll'

    >>> team_admin_browser.title
    'New poll : ...'

First we try to create a poll with a invalid name to
test the name field validator.

    >>> team_admin_browser.getControl(
    ...     "The unique name of this poll"
    ... ).value = "election_2100"
    >>> team_admin_browser.getControl(
    ...     "The title of this poll"
    ... ).value = "Presidential Election 2100"
    >>> proposition = "Who is going to be the next president?"
    >>> team_admin_browser.getControl(
    ...     "The proposition that is going to be voted"
    ... ).value = proposition
    >>> team_admin_browser.getControl(
    ...     "Users can spoil their votes?"
    ... ).selected = True
    >>> team_admin_browser.getControl(
    ...     name="field.dateopens"
    ... ).value = "2100-06-04 02:00:00+00:00"
    >>> team_admin_browser.getControl(
    ...     name="field.datecloses"
    ... ).value = "2100-07-04 02:00:00+00:00"
    >>> team_admin_browser.getControl("Continue").click()

    >>> print_feedback_messages(team_admin_browser.contents)
    There is 1 error.
    Invalid name 'election_2100'. Names must be at least two characters ...

We fix the name, but swap the dates. Again a nice error message.

    >>> team_admin_browser.getControl(
    ...     "The unique name of this poll"
    ... ).value = "election-2100"
    >>> team_admin_browser.getControl(
    ...     name="field.dateopens"
    ... ).value = "2100-07-04 02:00:00+00:00"
    >>> team_admin_browser.getControl(
    ...     name="field.datecloses"
    ... ).value = "2100-06-04 02:00:00+00:00"
    >>> team_admin_browser.getControl("Continue").click()

    >>> print_feedback_messages(team_admin_browser.contents)
    There is 1 error.
    A poll cannot close at the time (or before) it opens.

Now we get it right.

    >>> team_admin_browser.getControl(
    ...     name="field.dateopens"
    ... ).value = "2100-06-04 02:00:00+00:00"
    >>> team_admin_browser.getControl(
    ...     name="field.datecloses"
    ... ).value = "2100-07-04 02:00:00+00:00"
    >>> team_admin_browser.getControl("Continue").click()

We're redirected to the newly created poll page.

    >>> team_admin_browser.url
    'http://launchpad.test/~ubuntu-team/+poll/election-2100'

Create a new poll that starts tomorrow and will last for ten years.

    >>> from datetime import datetime, timedelta, timezone

    >>> tomorrow = (
    ...     datetime.now(timezone.utc) + timedelta(days=1)
    ... ).isoformat()
    >>> ten_years_from_now = (
    ...     datetime.now(timezone.utc) + timedelta(days=3560)
    ... ).isoformat()
    >>> team_admin_browser.open("http://launchpad.test/~ubuntu-team/+newpoll")
    >>> team_admin_browser.getControl(
    ...     "The unique name of this poll"
    ... ).value = "dpl-2080"
    >>> title_control = team_admin_browser.getControl(
    ...     "The title of this poll"
    ... )
    >>> title_control.value = "Debian Project Leader Election 2080"
    >>> proposition = "The next debian project leader"
    >>> team_admin_browser.getControl(
    ...     "The proposition that is going to be voted"
    ... ).value = proposition
    >>> team_admin_browser.getControl(
    ...     "Users can spoil their votes?"
    ... ).selected = True
    >>> team_admin_browser.getControl(name="field.dateopens").value = tomorrow
    >>> team_admin_browser.getControl(
    ...     name="field.datecloses"
    ... ).value = ten_years_from_now
    >>> team_admin_browser.getControl("Continue").click()

We're redirected to the newly created poll

    >>> from urllib.parse import unquote

    >>> team_admin_browser.url
    'http://launchpad.test/~ubuntu-team/+poll/dpl-2080'
    >>> print(team_admin_browser.title)
    Debian Project Leader Election 2080 : “Ubuntu Team” team
    >>> print_location(team_admin_browser.contents)
    Hierarchy: “Ubuntu Team” team
    Tabs:
    * Overview (selected) - http://launchpad.test/~ubuntu-team
    * Code - http://code.launchpad.test/~ubuntu-team
    * Bugs - http://bugs.launchpad.test/~ubuntu-team
    * Blueprints - http://blueprints.launchpad.test/~ubuntu-team
    * Translations - http://translations.launchpad.test/~ubuntu-team
    * Answers - http://answers.launchpad.test/~ubuntu-team
    Main heading: Debian Project Leader Election 2080
    >>> unquote(team_admin_browser.getLink("add an option").url)
    'http://launchpad.test/~ubuntu-team/+poll/dpl-2080/+newoption'

Now lets try to insert a poll with the name of a existing one.

# XXX matsubara 2006-07-17 bug=53302:
# There's no link to get back to +polls.

    >>> team_admin_browser.open("http://launchpad.test/~ubuntu-team/+newpoll")
    >>> team_admin_browser.getControl(
    ...     "The unique name of this poll"
    ... ).value = "dpl-2080"
    >>> title_control = team_admin_browser.getControl(
    ...     "The title of this poll"
    ... )
    >>> title_control.value = "Debian Project Leader Election 2080"
    >>> proposition = "The next debian project leader"
    >>> team_admin_browser.getControl(
    ...     "The proposition that is going to be voted"
    ... ).value = proposition
    >>> team_admin_browser.getControl(
    ...     "Users can spoil their votes?"
    ... ).selected = True
    >>> team_admin_browser.getControl(name="field.dateopens").value = tomorrow
    >>> team_admin_browser.getControl(
    ...     name="field.datecloses"
    ... ).value = ten_years_from_now
    >>> team_admin_browser.getControl("Continue").click()

    >>> print_feedback_messages(team_admin_browser.contents)
    There is 1 error.
    dpl-2080 is already in use by another poll in this team.

When creating a new poll, its start date must be at least 12 hours from
now, so that the user creating it has a chance to add some options before
the poll opens -- at that point new options cannot be added.

    >>> team_admin_browser.getControl("The unique name").value = "today"
    >>> today = datetime.today().strftime("%Y-%m-%d")
    >>> team_admin_browser.getControl(name="field.dateopens").value = today
    >>> team_admin_browser.getControl("Continue").click()
    >>> print_feedback_messages(team_admin_browser.contents)
    There is 1 error.
    A poll cannot open less than 12 hours after it's created.
