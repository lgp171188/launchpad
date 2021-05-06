/* Copyright 2015-2020 Canonical Ltd.  This software is licensed under the
 * GNU Affero General Public License version 3 (see the file LICENSE).
 *
 * @module Y.lp.services.message.edit
 * @requires node, DOM
 */
YUI.add('lp.services.messages.edit', function(Y) {
    var module = Y.namespace('lp.services.messages.edit');

    module.format_message_content = function(text) {
        return "<p>" + text.replaceAll("\n", "<br/>")    + "</p>";
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
        var lp_client = new Y.lp.client.Launchpad();
        var config = {
            on: {
                 success: on_success,
                 failure: on_failure
             },
            parameters: {"new_content": new_content}
        };
        lp_client.named_post(msg_url, 'editContent', config);
    };

    module.setup = function() {
        Y.all('.editable-message').each(function(container) {
            var node = container.getDOMNode();
            var baseurl = node.dataset.baseurl;
            var msg_body = container.one('.editable-message-body');
            var msg_form = container.one('.editable-message-form');
            var edit_btn = container.one('.editable-message-edit-btn');
            var update_btn = msg_form.one('.editable-message-update-btn');
            var cancel_btn = msg_form.one('.editable-message-cancel-btn');

            module.hide_edit_message_field(msg_body, msg_form);
            edit_btn.on('click', function(e) {
                module.show_edit_message_field(msg_body, msg_form);
                msg_form.one('textarea').getDOMNode().focus();
            });

            update_btn.on('click', function(e) {
                var textarea = msg_form.one('textarea').getDOMNode();
                var new_content = textarea.value;
                textarea.disabled = true;

                module.save_message_content(
                    baseurl, new_content, function() {
                        msg_body.getDOMNode().innerHTML = module.format_message_content(new_content);
                        module.hide_edit_message_field(msg_body, msg_form);
                        textarea.disabled = false;
                    },
                    function(err) {
                        alert("Something went wrong!" + err);
                        textarea.disabled = false;
                    }
                );
            });

            cancel_btn.on('click', function(e) {
                module.hide_edit_message_field(msg_body, msg_form);
            });
        });
    };
}, '0.1', {'requires': ['node', 'DOM']});
