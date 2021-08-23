Bug tracker
===========

The bug tracker set is exported as a collection at /bugs/bugtrackers that
any user can access.

    >>> from lazr.restful.testing.webservice import (
    ...     pprint_collection, pprint_entry)

    >>> bug_tracker_collection = anon_webservice.get(
    ...     '/bugs/bugtrackers').jsonBody()
    >>> pprint_collection(bug_tracker_collection)
    next_collection_link:
      'http://.../bugs/bugtrackers?ws.size=5&memo=5&ws.start=5'
    resource_type_link: 'http://.../#bug_trackers'
    start: 0
    total_size: 8
    ---
    active: True
    base_url: 'https://bugzilla.mozilla.org/'
    base_url_aliases: []
    bug_tracker_type: 'Bugzilla'
    contact_details: 'Carrier pigeon only'
    has_lp_plugin: None
    name: 'mozilla.org'
    registrant_link: 'http://.../~name12'
    resource_type_link: 'http://.../#bug_tracker'
    self_link: 'http://.../bugs/bugtrackers/mozilla.org'
    summary: 'The Mozilla.org bug tracker is the grand-daddy of ...'
    title: 'The Mozilla.org Bug Tracker'
    watches_collection_link: 'http:.../bugs/bugtrackers/mozilla.org/watches'
    web_link: 'http://bugs.launchpad.test/bugs/bugtrackers/mozilla.org'
    --- ...

A bug tracker can be retrieved using the bug tracker collection's
getByName named operation.

    >>> bug_tracker = anon_webservice.named_get(
    ...     '/bugs/bugtrackers', 'getByName',
    ...     name='gnome-bugzilla').jsonBody()
    >>> print(bug_tracker['name'])
    gnome-bugzilla

A bug tracker can be retrieved using the bug tracker collection's
queryByBaseURL named operation.

    >>> bug_tracker = anon_webservice.named_get(
    ...     '/bugs/bugtrackers', 'queryByBaseURL',
    ...     base_url='https://bugzilla.mozilla.org/').jsonBody()
    >>> print(bug_tracker['name'])
    mozilla.org

The bug tracker set provides the ensureBugTracker named operation that a
logged in user can call to create a bug tracker.

    >>> params = dict(
    ...     base_url='http://wombat.zz/', bug_tracker_type='Bugzilla',
    ...     name='wombat', title='Wombat title', summary='Wombat summary',
    ...     contact_details='big-nose@wombat.zz')
    >>> print(webservice.named_post(
    ...     '/bugs/bugtrackers', 'ensureBugTracker', **params))
    HTTP/1.1 201 Created ...
    Location: http://.../bugs/bugtrackers/wombat ...

    >>> bug_tracker = webservice.get('/bugs/bugtrackers/wombat').jsonBody()
    >>> pprint_entry(bug_tracker)
    active: True
    base_url: 'http://wombat.zz/'
    base_url_aliases: []
    bug_tracker_type: 'Bugzilla'
    contact_details: 'big-nose@wombat.zz'
    has_lp_plugin: False
    name: 'wombat'
    registrant_link: 'http://.../~salgado'
    resource_type_link: 'http://.../#bug_tracker'
    self_link: 'http://.../bugs/bugtrackers/wombat'
    summary: 'Wombat summary'
    title: 'Wombat title'
    watches_collection_link: 'http://.../bugs/bugtrackers/wombat/watches'
    web_link: 'http://bugs.launchpad.test/bugs/bugtrackers/wombat'
