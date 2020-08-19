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

    module.add_new_credentials = function(e) {
        var add_new_credentials = Y.one(
            'input[name="field.add_new_credentials"]');
        var use_existing_credentials = Y.one(
            'input[name="field.use_existing_credentials"]');

        if (add_new_credentials.get('checked') === true) {
            use_existing_credentials.set('checked', false);
            Y.one('[id="field.existing_credentials"]').set('disabled', true);
            Y.one('[id="field.add_url"]').set('disabled', false);
            Y.one('[id="field.add_username"]').set('disabled', false);
            Y.one('[id="field.add_password"]').set('disabled', false);
            Y.one('[id="field.add_confirm_password"]').set('disabled', false);
        }
        else{
            use_existing_credentials.set('checked', true);
            Y.one('[id="field.existing_credentials"]').set('disabled', false);
            Y.one('[id="field.add_url"]').set('disabled', true);
            Y.one('[id="field.add_username"]').set('disabled', true);
            Y.one('[id="field.add_password"]').set('disabled', true);
            Y.one('[id="field.add_confirm_password"]').set('disabled', true);

        }
    };

    module.use_existing_credentials = function(e) {
        var add_new_credentials = Y.one(
            'input[name="field.add_new_credentials"]');
        var use_existing_credentials = Y.one(
            'input[name="field.use_existing_credentials"]');

        if (use_existing_credentials.get('checked') === true) {
            add_new_credentials.set('checked', false);
            Y.one('[id="field.existing_credentials"]').set('disabled', false);
            Y.one('[id="field.add_url"]').set('disabled', true);
            Y.one('[id="field.add_username"]').set('disabled', true);
            Y.one('[id="field.add_password"]').set('disabled', true);
            Y.one('[id="field.add_confirm_password"]').set('disabled', true);

        }
        else{
            add_new_credentials.set('checked', true);
            Y.one('[id="field.existing_credentials"]').set('disabled', true);
            Y.one('[id="field.add_url"]').set('disabled', false);
            Y.one('[id="field.add_username"]').set('disabled', false);
            Y.one('[id="field.add_password"]').set('disabled', false);
            Y.one('[id="field.add_confirm_password"]').set('disabled', false);

        }
    };

    module.setup = function() {
        Y.all('input[name="field.use_existing_credentials"]').on(
            'click', module.use_existing_credentials);
        Y.all('input[name="field.add_new_credentials"]').on(
            'click', module.add_new_credentials);
        // Set the initial state.
        module.add_new_credentials();
        module.use_existing_credentials();
    };
}, '0.1', {'requires': ['node', 'DOM']});
