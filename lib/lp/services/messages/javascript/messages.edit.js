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

    module.showEditMessageField = function(msg_body, msg_form) {
        msg_body.setStyle('display', 'none');
        msg_form.setStyle('display', 'block');
    };

    module.hideEditMessageField = function(msg_body, msg_form) {
        msg_body.setStyle('display', 'block');
        msg_form.setStyle('display', 'none');
    };

    module.saveMessageContent = function(
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

    module.showNotification = function(container, msg, can_dismiss) {
        can_dismiss = can_dismiss || false;
        // Clean up previous notification.
        module.hideNotification(container);
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
                module.hideNotification(container);
             });
             node.append(dismiss);
         }
    };

    module.hideNotification = function(container) {
        var notification = container.one(".editable-message-notification");
        if(notification) {
            notification.remove();
        }
    };

    module.showLoading = function(container) {
        module.showNotification(
            container,
            '<img class="spinner" src="/@@/spinner" alt="Loading..." />');
    };

    module.hideLoading = function(container) {
        module.hideNotification(container);
    };

    // What to do when a user clicks a message's "edit" button.
    module.onEditClick = function(elements) {
        // When clicking edit icon, show the edit form and focus on the
        // text area.
        module.showEditMessageField(elements.msg_body, elements.msg_form);
        elements.msg_form.one('textarea').getDOMNode().focus();
    }

    // What to do when a user clicks "cancel edit" button.
    module.onEditCancelClick = function(elements) {
        module.hideEditMessageField(elements.msg_body, elements.msg_form);
    };

    // What to do when a user clicks the update button after editing a msg.
    module.onUpdateClick = function(elements, baseurl) {
        // When clicking on "update" button, disable UI elements and send a
        // request to update the message at the backend.
        module.showLoading(elements.container);
        var textarea = elements.textarea.getDOMNode();
        var new_content = textarea.value;
        textarea.disabled = true;
        elements.update_btn.getDOMNode().disabled = true;

        module.saveMessageContent(
            baseurl, new_content,
            function(err) { module.onMessageSaved(elements, new_content); },
            function(err) { module.onMessageSaveError(elements, err); }
        );
    };

    // What to do when a message is saved in the backend.
    module.onMessageSaved = function(elements, new_content) {
        // When finished updating at the backend, re-enable UI
        // elements and display the new message.
        var html_msg = module.htmlify_msg(new_content);
        elements.msg_body_text.getDOMNode().innerHTML = html_msg;
        module.hideEditMessageField(
            elements.msg_body, elements.msg_form);
        elements.textarea.getDOMNode().disabled = false;
        elements.update_btn.getDOMNode().disabled = false;
        module.hideLoading(elements.container);
        module.showNotification(
            elements.container,
            module.msg_edit_success_notification, true);
    };

    // What to do when a message fails to update on the backend.
    module.onMessageSaveError = function(elements, err) {
        // When something goes wrong at the backend, re-enable
        // UI elements and display an error.
        module.showNotification(
            elements.container,
            module.msg_edit_error_notification,  true);
        elements.textarea.getDOMNode().disabled = false;
        elements.update_btn.getDOMNode().disabled = false;
    };

    module.wireEventHandlers = function(container) {
        var node = container.getDOMNode();
        var baseurl = node.dataset.baseurl;
        var elements = {
            "container": container,
            "msg_body": container.one('.editable-message-body'),
            "msg_body_text": container.one('.editable-message-text'),
            "msg_form": container.one('.editable-message-form'),
            "edit_btn": container.one('.editable-message-edit-btn'),
            "update_btn": container.one('.editable-message-update-btn'),
            "cancel_btn": container.one('.editable-message-cancel-btn'),
            "last_edit": container.one('.editable-message-last-edit')
        };
        elements.textarea = elements.msg_form.one('textarea');

        module.hideEditMessageField(elements.msg_body, elements.msg_form);

        // If the edit button is not present, do not try to bind the
        // handlers.
        if (!elements.edit_btn || !baseurl) {
            return;
        }

        elements.edit_btn.on('click', function(e) {
            module.onEditClick(elements);
        });

        elements.update_btn.on('click', function(e) {
            module.onUpdateClick(elements, baseurl);
        });

        elements.cancel_btn.on('click', function(e) {
            module.onEditCancelClick(elements);
        });
    };

    module.setup = function() {
        this.lp_client = new Y.lp.client.Launchpad();
        Y.all('.editable-message').each(module.wireEventHandlers);
    };
}, '0.1', {'requires': ['lp.client', 'node', 'DOM']});
