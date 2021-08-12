/* Copyright 2014 Canonical Ltd.  This software is licensed under the
 * GNU Affero General Public License version 3 (see the file LICENSE). */

/*
    Specific test cases for side-by-side view of diffs
 */
YUI.add('lp.code.branchmergeproposal.ss_inlinecomments.test', function (Y) {

    var module = Y.lp.code.branchmergeproposal.inlinecomments;
    var tests = Y.namespace(
        'lp.code.branchmergeproposal.ss_inlinecomments.test');
    tests.suite = new Y.Test.Suite(
        'branchmergeproposal.ss_inlinecomments Tests');

    tests.suite.add(new Y.Test.Case({
        name: 'code.branchmergeproposal.ss_inlinecomments_comments_tests',

        setUp: function () {
            // Loads testing values into LP.cache.
            LP.cache.context = {
                self_link: ("https://code.launchpad.test/api/devel/" +
                            "~foo/bar/foobr/+merge/1")
            };
            LP.links = {
                me : 'something'
            };
        },

        tearDown: function () {},

        test_draft_handler_for_side_by_side_diff: function() {
            module.add_doubleclick_handler();

            // Overrides module LP client by one using 'mockio'.
            var mockio = new Y.lp.testing.mockio.MockIo();
            module.lp_client = new Y.lp.client.Launchpad(
                {io_provider: mockio});

            // No draft comment in line 6.
            Y.Assert.isNull(Y.one('#comments-diff-line-6 .draft'));

            // Let's try to create one
            var line  = Y.one('#diff-line-6 .ss-line-no');

            line.simulate('click');
            var ic_area = Y.one('#comments-diff-line-6 .draft');
            ic_area.one('.yui3-ieditor-input>textarea').set('value', 'Go!');
            ic_area.one('.lazr-pos').simulate('click');

            // LP was hit and a comment was created.
            Y.Assert.areEqual(1, mockio.requests.length);
            Y.Assert.areEqual(
                'Unsaved comment',
                ic_area.one('.boardCommentDetails').get('text'));
            Y.Assert.areEqual(
                'Go!', ic_area.one('.yui3-editable_text-text').get('text'));
        }
    }));

}, '0.1', {
    requires: ['node-event-simulate', 'test', 'lp.testing.helpers',
               'console', 'lp.client', 'lp.testing.mockio', 'widget',
               'lp.code.branchmergeproposal.inlinecomments', 'lp.anim',
               'lp.code.branchmergeproposal.reviewcomment']
});
