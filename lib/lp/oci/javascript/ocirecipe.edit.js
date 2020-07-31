/* Copyright 2015-2020 Canonical Ltd.  This software is licensed under the
 * GNU Affero General Public License version 3 (see the file LICENSE).
 *
 * @module Y.lp.oci.ocirecipe.edit
 * @requires node, DOM
 */
YUI.add('lp.oci.ocirecipe.edit', function(Y) {
    Y.log('loading lp.oci.ocirecipe.edit');
    var module = Y.namespace('lp.oci.ocirecipe.edit');

    module.set_enabled = function(field_id, is_enabled) {
        var field = Y.DOM.byId(field_id);
        if (field !== null) {
            field.disabled = !is_enabled;
        }
    };

    module.onclick_add_new_creds = function(e) {
        var add_new_creds = Y.one(
            'input[name="field.add_new_creds"]');
        var use_existing_creds = Y.one(
            'input[name="field.use_existing_creds"]');

        if (add_new_creds.get('checked') === true) {
            use_existing_creds.set('checked', false);
            Y.one('[id="field.existing_credentials"]').set('disabled', true);
            Y.one('[id="field.add_url"]').set('disabled', false);
            Y.one('[id="field.add_username"]').set('disabled', false);
            Y.one('[id="field.add_password"]').set('disabled', false);
            Y.one('[id="field.add_confirm_password"]').set('disabled', false);

        }
        else{
            use_existing_creds.set('checked', true);
            Y.one('[id="field.existing_credentials"]').set('disabled', false);
            Y.one('[id="field.add_url"]').set('disabled', true);
            Y.one('[id="field.add_username"]').set('disabled', true);
            Y.one('[id="field.add_password"]').set('disabled', true);
            Y.one('[id="field.add_confirm_password"]').set('disabled', true);

        }
    };

    module.use_existing_creds = function(e) {
        var add_new_creds = Y.one(
            'input[name="field.add_new_creds"]');
        var use_existing_creds = Y.one(
            'input[name="field.use_existing_creds"]');

        if (use_existing_creds.get('checked') === true) {
            add_new_creds.set('checked', false);
            Y.one('[id="field.existing_credentials"]').set('disabled', false);
            Y.one('[id="field.add_url"]').set('disabled', true);
            Y.one('[id="field.add_username"]').set('disabled', true);
            Y.one('[id="field.add_password"]').set('disabled', true);
            Y.one('[id="field.add_confirm_password"]').set('disabled', true);

        }
        else{
            add_new_creds.set('checked', true);
            Y.one('[id="field.existing_credentials"]').set('disabled', true);
            Y.one('[id="field.add_url"]').set('disabled', false);
            Y.one('[id="field.add_username"]').set('disabled', false);
            Y.one('[id="field.add_password"]').set('disabled', false);
            Y.one('[id="field.add_confirm_password"]').set('disabled', false);

        }
    };

    module.setup = function() {
        Y.all('input[name="field.use_existing_creds"]').on(
            'click', module.use_existing_creds);
        Y.all('input[name="field.add_new_creds"]').on(
            'click', module.onclick_add_new_creds);
        // Set the initial state.
        module.onclick_add_new_creds();
        module.use_existing_creds();
    };
}, '0.1', {'requires': ['node', 'DOM']});
