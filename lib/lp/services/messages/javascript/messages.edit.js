/* Copyright 2015-2021 Canonical Ltd.  This software is licensed under the
 * GNU Affero General Public License version 3 (see the file LICENSE).
 *
 * This modules controls HTML comments in order to make them editable. To do
 * so, it requires:
 *  - A div container with the class .editable-message containing everything
 *      else related to the message
 *  - A data-baseurl="/path/to/msg" on the .editable-message container
 *  - A .editable-message-body container with the original msg content
 *  - A .editable-message-edit-btn element inside the main container, that will
 *      switch the view to edit form when clicked.
 *  - A .editable-message-form, with a textarea and 2 buttons:
 *      .editable-message-update-btn and  .editable-message-cancel-btn.
 *
 * Once those HTML elements are available in the page, this module should be
 * initialized with `lp.services.messages.edit.setup()`.
 *
 * @module Y.lp.services.messages.edit
 * @requires node, DOM, lp.client
 */
YUI.add('lp.services.messages.edit', function(Y) {
    var module = Y.namespace('lp.services.messages.edit');

    module.msg_edit_success_notification = (
        "Message edited, but the original content may still be publicly " +
        "visible using the API.<br />Please, " +
        "<a href='https://launchpad.net/+apidoc/devel.html#message'>" +
        "check the API documentation</a> in case " +
        "need to remove old message revisions."
    );
    module.msg_edit_error_notification = (
        "There was an error updating the comment. " +
        "Please, try again in some minutes."
    );

    module.htmlify_msg = function(text) {
        text = text.replace(/</g, "&lt;");
        text = text.replace(/>/g, "&gt;");
        text = text.replace(/\n/g, "<br/>");
        return "<p>" + text    + "</p>";
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

    module.show_notification = function(container, msg, can_dismiss) {
        can_dismiss = can_dismiss || false;
        // Clean up previous notification.
        module.hide_notification(container);
        container.setStyle('position', 'relative');
        var node = Y.Node.create(
            "<div class='editable-message-notification'>" +
            "  <p class='block-sprite large-warning'>" +
            msg +
            "  </p>" +
            "</div>");
         container.append(node);
         if (can_dismiss) {
             var dismiss = Y.Node.create(
                "<div class='editable-message-notification-dismiss'>" +
                "  <input type='button' value=' Ok ' />" +
                "</div>");
             dismiss.on('click', function() {
                module.hide_notification(container);
             });
             node.append(dismiss);
         }
    };

    module.hide_notification = function(container) {
        var notification = container.one(".editable-message-notification");
        if(notification) {
            notification.remove();
        }
    };

    module.show_loading = function(container) {
        module.show_notification(
            container,
            '<img class="spinner" src="/@@/spinner" alt="Loading..." />');
    };

    module.hide_loading = function(container) {
        module.hide_notification(container);
    };

    module.setup = function() {
        this.lp_client = new Y.lp.client.Launchpad();

        Y.all('.editable-message').each(function(container) {
            var node = container.getDOMNode();
            var baseurl = node.dataset.baseurl;
            var msg_body = container.one('.editable-message-body');
            var msg_body_text = container.one('.editable-message-text');
            var msg_form = container.one('.editable-message-form');
            var edit_btn = container.one('.editable-message-edit-btn');
            var update_btn = msg_form.one('.editable-message-update-btn');
            var cancel_btn = msg_form.one('.editable-message-cancel-btn');

            module.hide_edit_message_field(msg_body, msg_form);

            // If the edit button is not present, do not try to bind the
            // handlers.
            if (!edit_btn) {
                return;
            }

            // When clicking edit icon, show the edit form and focus on the
            // text area.
            edit_btn.on('click', function(e) {
                module.show_edit_message_field(msg_body, msg_form);
                msg_form.one('textarea').getDOMNode().focus();
            });

            // When clicking on "update" button, disable UI elements and send a
            // request to update the message at the backend.
            update_btn.on('click', function(e) {
                module.show_loading(container);
                var textarea = msg_form.one('textarea').getDOMNode();
                var new_content = textarea.value;
                textarea.disabled = true;
                update_btn.getDOMNode().disabled = true;

                module.save_message_content(
                    baseurl, new_content, function() {
                        // When finished updating at the backend, re-enable UI
                        // elements and display the new message.
                        var html_msg = module.htmlify_msg(new_content);
                        msg_body_text.getDOMNode().innerHTML = html_msg;
                        module.hide_edit_message_field(msg_body, msg_form);
                        textarea.disabled = false;
                        update_btn.getDOMNode().disabled = false;
                        module.hide_loading(container);
                        module.show_notification(
                            container,
                            module.msg_edit_success_notification, true);
                    },
                    function(err) {
                        // When something goes wrong at the backend, re-enable
                        // UI elements and display an error.
                        module.show_notification(
                            container,
                            module.msg_edit_error_notification,  true);
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
