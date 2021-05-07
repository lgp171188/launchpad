/**
 * Copyright 2012 Canonical Ltd. This software is licensed under the
 * GNU Affero General Public License version 3 (see the file LICENSE).
 *
 * Tests for lp.services.messages.edit.
 *
 * @module lp.services.messages.edit
 * @submodule test
 */

YUI.add('lp.services.messages.edit.test', function(Y) {

    var namespace = Y.namespace('lp.services.messages.edit.test');

    var suite = new Y.Test.Suite("lp.services.messages.edit Tests");
    var module = Y.lp.services.messages.edit;

    function assertDisplayStyles(items, visibility) {
        for(var i=items ; i<items.length ; i++) {
             Y.Assert.areSame(visibility, items[i].getStyle("display"));
        }
    }

    function assertDisplayStyle(item, visibility) {
        Y.Assert.areSame(visibility, item.getStyle("display"));
    }

    var TestMessageEdit = {
        name: "TestMessageEdit",

        setUp: function() {
            this.containers = [
                Y.one("#first-message"), Y.one("#second-message")];
            this.msg_bodies = [
                this.containers[0].one(".editable-message-body"),
                this.containers[1].one(".editable-message-body")
            ];
            this.msg_forms = [
                this.containers[0].one(".editable-message-form"),
                this.containers[1].one(".editable-message-form")
            ];
            this.edit_icons = [
                this.containers[0].one(".editable-message-edit-btn"),
                this.containers[1].one(".editable-message-edit-btn")
            ];
            this.cancel_btns = [
                this.containers[0].one(".editable-message-cancel-btn"),
                this.containers[1].one(".editable-message-cancel-btn")
            ];
            this.textareas = [
                this.msg_forms[0].one("textarea"),
                this.msg_forms[1].one("textarea")
            ];
            this.update_btns = [
                this.containers[0].one(".editable-message-update-btn"),
                this.containers[1].one(".editable-message-update-btn")
            ];

            for(var i=0 ; i<this.containers.length ; i++) {
                this.msg_bodies[i].getDOMNode().innerHTML = "Message number " + i;
                this.msg_bodies[i].setStyle('display', '');
                this.msg_forms[i].setStyle('display', '');
                this.textareas[i].getDOMNode().value = '';
            }
        },

        test_instantiation_hides_forms: function() {
            // When editable messages are initialized, the forms should be
            // hidden.
            module.setup();

            assertDisplayStyles(this.msg_bodies, 'block');
            assertDisplayStyles(this.msg_forms, 'none');
        },

        test_click_edit_icon_shows_form: function() {
            // Makes sure the form is shown when we click one of the edit icons.
            module.setup();
            this.edit_icons[1].simulate('click');

            // Form 1 should be visible...
            assertDisplayStyle(this.msg_bodies[1], 'none');
            assertDisplayStyle(this.msg_forms[1], 'block');

            // ... but form 0 should have not be affected.
            assertDisplayStyle(this.msg_bodies[0], 'block');
            assertDisplayStyle(this.msg_forms[0], 'none');
        },

        test_cancel_button_hides_form: function() {
            // Makes sure the form is hidden again if the user, after clicking
            // edit icons, decides to cancel edition.
            module.setup();
            this.edit_icons[1].simulate('click');
            this.cancel_btns[1].simulate('click');

            assertDisplayStyle(this.msg_bodies[0], 'block');
            assertDisplayStyle(this.msg_forms[0], 'none');
            assertDisplayStyle(this.msg_bodies[1], 'block');
            assertDisplayStyle(this.msg_forms[1], 'none');
        },

        test_success_save_comment_edition: function() {
            module.setup();
            module.lp_client.io_provider = new Y.lp.testing.mockio.MockIo();

            this.edit_icons[1].simulate('click');
            this.textareas[1].getDOMNode().value = 'edited\nmessage';
            this.update_btns[1].simulate('click');

            // Checks that only the current form interactions are blocked.
            Y.Assert.isTrue(this.textareas[1].getDOMNode().disabled);
            Y.Assert.isTrue(this.update_btns[1].getDOMNode().disabled);
            Y.Assert.isFalse(this.textareas[0].getDOMNode().disabled);
            Y.Assert.isFalse(this.update_btns[0].getDOMNode().disabled);

            module.lp_client.io_provider.success({
                responseText:'null',
                responseHeaders: {'Content-Type': 'application/json'}
            });
            Y.Assert.areSame(
                '<p>edited<br>message</p>',
                this.msg_bodies[1].getDOMNode().innerHTML);

            // All forms should be released.
            Y.Assert.isFalse(this.textareas[1].getDOMNode().disabled);
            Y.Assert.isFalse(this.update_btns[1].getDOMNode().disabled);
            Y.Assert.isFalse(this.textareas[0].getDOMNode().disabled);
            Y.Assert.isFalse(this.update_btns[0].getDOMNode().disabled);

            // Check forms and msg bodies visibility are back to normal.
            assertDisplayStyle(this.msg_bodies[0], 'block');
            assertDisplayStyle(this.msg_forms[0], 'none');
            assertDisplayStyle(this.msg_bodies[1], 'block');
            assertDisplayStyle(this.msg_forms[1], 'none');

            // Check that the request as made correctly.
            var last_request = module.lp_client.io_provider.last_request;
            Y.Assert.areSame("/api/devel/message/2", last_request.url);
            Y.Assert.areSame("POST", last_request.config.method);
            Y.Assert.areSame(
                "ws.op=editContent&new_content=edited%0Amessage",
                last_request.config.data);
        },

    };

    suite.add(new Y.Test.Case(TestMessageEdit));

    namespace.suite = suite;

}, "0.1", {"requires": [
               "lp.services.messages.edit", "node", "lp.testing.mockio",
               "node-event-simulate", "test", "lp.anim"]});
