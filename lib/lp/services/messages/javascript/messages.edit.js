/* Copyright 2015-2020 Canonical Ltd.  This software is licensed under the
 * GNU Affero General Public License version 3 (see the file LICENSE).
 *
 * @module Y.lp.services.messages.edit
 * @requires node, DOM
 */
YUI.add('lp.services.messages.edit', function(Y) {
    var module = Y.namespace('lp.services.messages.edit');

    module.htmlify_msg = function(text) {
        return "<p>" + text.replace(/\n/g, "<br/>")    + "</p>";
    };

    module.show_edit_message_field = function(msg_body, msg_form) {
        msg_body.setStyle('display', 'none');
        msg_form.setStyle('display', 'block');
    };

    module.hide_edit_message_field = function(msg_body, msg_form) {
        msg_body.setStyle('display', 'block');
        msg_form.setStyle('display', 'none');
    };

    module.save_message_content = function(
            msg_path, new_content, on_success, on_failure) {
        var msg_url = "/api/devel" + msg_path;
        var config = {
            on: {
                 success: on_success,
                 failure: on_failure
             },
            parameters: {"new_content": new_content}
        };
        this.lp_client.named_post(msg_url, 'editContent', config);
    };

    module.setup = function() {
        this.lp_client = new Y.lp.client.Launchpad();

        Y.all('.editable-message').each(function(container) {
            var node = container.getDOMNode();
            var baseurl = node.dataset.baseurl;
            var msg_body = container.one('.editable-message-body');
            var msg_form = container.one('.editable-message-form');
            var edit_btn = container.one('.editable-message-edit-btn');
            var update_btn = msg_form.one('.editable-message-update-btn');
            var cancel_btn = msg_form.one('.editable-message-cancel-btn');

            module.hide_edit_message_field(msg_body, msg_form);

            // When clicking edit icon, show the edit form and focus on the
            // text area.
            edit_btn.on('click', function(e) {
                module.show_edit_message_field(msg_body, msg_form);
                msg_form.one('textarea').getDOMNode().focus();
            });

            // When clicking on "update" button, disable UI elements and send a
            // request to update the message at the backend.
            update_btn.on('click', function(e) {
                var textarea = msg_form.one('textarea').getDOMNode();
                var new_content = textarea.value;
                textarea.disabled = true;
                update_btn.getDOMNode().disabled = true;

                module.save_message_content(
                    baseurl, new_content, function() {
                        // When finished updating at the backend, re-enable UI
                        // elements and display the new message.
                        var html_msg = module.htmlify_msg(new_content);
                        msg_body.getDOMNode().innerHTML = html_msg;
                        module.hide_edit_message_field(msg_body, msg_form);
                        textarea.disabled = false;
                        update_btn.getDOMNode().disabled = false;
                    },
                    function(err) {
                        // When something goes wrong at the backend, re-enable
                        // UI elements and display an error.
                        alert("Something went wrong updating the comment!");
                        textarea.disabled = false;
                        update_btn.getDOMNode().disabled = false;
                    }
                );
            });

            cancel_btn.on('click', function(e) {
                module.hide_edit_message_field(msg_body, msg_form);
            });
        });
    };
}, '0.1', {'requires': ['lp.client', 'node', 'DOM']});
