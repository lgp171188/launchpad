/* Copyright 2025 Canonical Ltd.  This software is licensed under the
 * GNU Affero General Public License version 3 (see the file LICENSE).
 *
 * Webhook event types widget.
 *
 * @module lp.services.webhooks.event_types
 */

YUI.add("lp.services.webhooks.event_types", function(Y) {

var namespace = Y.namespace("lp.services.webhooks.event_types");

/**
 * Activate the 'parent-subscope' behaviour for the check‑boxes
 * rendered by WebhookCheckboxWidget.
 */
namespace.initScopeCheckboxes = function () {
    // Handle checkbox parent-child relationships
    var handleCheckboxChange = function (e) {
        var checkbox       = e.currentTarget;
        var value          = checkbox.get('value');
        var isChecked      = checkbox.get('checked');
        // If this is a parent checkbox, handle children
        var childCheckboxes =
            Y.all('input[type="checkbox"][data-parent="' + value + '"]');

        childCheckboxes.each(function (childCheckbox) {
            if (isChecked) {
                // If parent is checked, uncheck and disable child
                childCheckbox.set('checked', false);
                childCheckbox.set('disabled', true);
            } else {
                // If parent is unchecked, enable child
                childCheckbox.set('disabled', false);
            }
        });
    };

    // Set up event listeners for parent checkboxes
    var parentCheckboxes = Y.all('input[type="checkbox"]:not([data-parent])');
    parentCheckboxes.on('change', handleCheckboxChange)

    // Find all parent checkboxes that are checked
    var checkedParents = Y.all(
        'input[type="checkbox"]:not([data-parent]):checked'
    );
    checkedParents.each(function (parentCheckbox) {
        var value          = parentCheckbox.get('value');
        var childCheckboxes =
            Y.all('input[type="checkbox"][data-parent="' + value + '"]');
        childCheckboxes.each(function (childCheckbox) {
            childCheckbox.set('checked', false);
            childCheckbox.set('disabled', true);
        });
    });
};
}, "0.1", {"requires": ["event", "node", "widget", "lp.app.date",
                        "lp.app.listing_navigator", "lp.client",
                        "lp.mustache"]});
