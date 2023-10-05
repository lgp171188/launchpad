/* Copyright 2021 Canonical Ltd.  This software is licensed under the
 * GNU Affero General Public License version 3 (see the file LICENSE).
 *
 * Personal access token widgets.
 *
 * @module lp.services.auth.tokens
 * @requires node, widget, lp.app.errors, lp.client, lp.extras, lp.ui-base
 */

YUI.add('lp.services.auth.tokens', function(Y) {
    var module = Y.namespace('lp.services.auth.tokens');

    var CreateTokenWidget = function() {
        CreateTokenWidget.superclass.constructor.apply(this, arguments);
    };

    CreateTokenWidget.NAME = 'create-token-widget';

    CreateTokenWidget.ATTRS = {
        /**
         * The URI for the target for new tokens.
         *
         * @attribute target_uri
         * @type String
         * @default null
         */
        target_uri: {
            value: null
        }
    };

    Y.extend(CreateTokenWidget, Y.Widget, {
        initializer: function(cfg) {
            this.client = new Y.lp.client.Launchpad();
            this.set('target_uri', cfg.target_uri);
        },

        /**
         * Show the spinner.
         *
         * @method showSpinner
         */
        showSpinner: function() {
            this.get('srcNode').all('.spinner').removeClass('hidden');
        },

        /**
         * Hide the spinner.
         *
         * @method hideSpinner
         */
        hideSpinner: function() {
            this.get('srcNode').all('.spinner').addClass('hidden');
        },

        /**
         * Create a new token.
         *
         * @method createToken
         */
        createToken: function() {
            var container = this.get('srcNode');
            var description_node = container.one('[name="field.description"]');
            var description = description_node.get('value');
            if (description === '') {
                Y.lp.app.errors.display_error(
                    description_node,
                    'A personal access token must have a description.');
                return;
            }
            var scopes = container.all('[name="field.scopes"]')
                .filter(':checked')
                .map(function (node) {
                    var node_id = node.get('id');
                    var label = container.one('label[for="' + node_id + '"]');
                    return label.get('text').trim();
                });
            if (scopes.length === 0) {
                Y.lp.app.errors.display_error(
                    null, 'A personal access token must have scopes.');
                return;
            }
            var date_expires = container
                .one('[name="field.date_expires"]').get('value');
            var self = this;
            var config = {
                on: {
                    start: function() {
                        self.showSpinner();
                    },
                    end: function() {
                        self.hideSpinner();
                    },
                    success: function(response) {
                        container.one('#new-token-secret')
                            .set('text', response);
                        container.one('#new-token-information')
                            .removeClass('hidden');
                        var tokens_tbody = Y.one('#access-tokens-tbody');
                        tokens_tbody.append(Y.Node.create('<tr />')
                            .addClass(
                                tokens_tbody.all('tr').size() % 2
                                    ? Y.lp.ui.CSS_ODD : Y.lp.ui.CSS_EVEN)
                            .append(Y.Node.create('<td />')
                                .set('text', description))
                            .append(Y.Node.create('<td />'))
                            .append(Y.Node.create('<td />')
                                .set('text', scopes.join(', ')))
                            .append(Y.Node.create('<td />')
                                .set('text', 'a moment ago'))
                            .append(Y.Node.create('<td />'))
                            .append(Y.Node.create('<td />')
                                .set('text',
                                     date_expires !== ''
                                        ? date_expires : 'Never'))
                            .append(Y.Node.create('<td />')));
                    },
                    failure: function(ignore, response, args) {
                        Y.lp.app.errors.display_error(
                            null, 'Failed to create personal access token.');
                    }
                },
                parameters: {
                    description: description,
                    scopes: scopes
                }
            };
            if (date_expires !== "") {
                config.parameters.date_expires = date_expires;
            }
            this.client.named_post(
                this.get('target_uri'), 'issueAccessToken', config);
        },

        bindUI: function() {
            this.constructor.superclass.bindUI.call(this);
            var create_token_button = this.get('srcNode')
                .one('#create-token-button');
            if (Y.Lang.isValue(create_token_button)) {
                var self = this;
                create_token_button.on('click', function(e) {
                    e.halt();
                    self.createToken();
                });
            }
        }
    });

    module.CreateTokenWidget = CreateTokenWidget;
}, '0.1', {'requires': [
    'node', 'widget', 'lp.app.errors', 'lp.client', 'lp.extras', 'lp.ui-base'
]});
