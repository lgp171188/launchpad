/* Copyright 2015-2020 Canonical Ltd.  This software is licensed under the
 * GNU Affero General Public License version 3 (see the file LICENSE).
 *
 * @module Y.lp.oci.ocirecipe.edit
 * @requires node, DOM
 */
YUI.add('lp.oci.ocirecipe.edit', function(Y) {
    var module = Y.namespace('lp.oci.ocirecipe.edit');

    module.set_enabled = function(field_id, is_enabled) {
        var field = Y.DOM.byId(field_id);
        if (field !== null) {
            field.disabled = !is_enabled;
        }
    };

    module.onclick_add_credentials = function(e) {
        var value = '';
        Y.all('input[name="field.add_credentials"]').each(function(node) {
            if (node.get('checked')) {
                value = node.get('value');
            }
        });
        module.set_enabled('field.existing_credentials', value === 'existing');
        module.set_enabled('field.add_url', value === 'new');
        module.set_enabled('field.add_region', value === 'new');
        module.set_enabled('field.add_username', value === 'new');
        module.set_enabled('field.add_password', value === 'new');
        module.set_enabled('field.add_confirm_password', value === 'new');
    };

    module.setup = function() {
        Y.all('input[name="field.add_credentials"]').on(
            'click', module.onclick_add_credentials);

        // Set the initial state.
        module.onclick_add_credentials();
    };
}, '0.1', {'requires': ['node', 'DOM']});
