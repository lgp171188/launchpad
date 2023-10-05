/* Copyright 2021 Canonical Ltd.  This software is licensed under the
 * GNU Affero General Public License version 3 (see the file LICENSE). */

YUI.add('lp.services.auth.tokens.test', function (Y) {

    var tests = Y.namespace('lp.services.auth.tokens.test');
    tests.suite = new Y.Test.Suite('lp.services.auth.tokens Tests');

    tests.suite.add(new Y.Test.Case({
        name: 'lp.services.auth.tokens_tests',

        setUp: function () {
            this.node = Y.Node.create(Y.one('#fixture-template').getContent());
            Y.one('#fixture').append(this.node);
            this.widget = new Y.lp.services.auth.tokens.CreateTokenWidget({
                srcNode: Y.one('#create-token'),
                target_uri: '/api/devel/repo'
            });
            this.mockio = new Y.lp.testing.mockio.MockIo();
            this.widget.client.io_provider = this.mockio;
            this.old_error_method = Y.lp.app.errors.display_error;
        },

        tearDown: function () {
            this.widget.destroy();
            Y.one('#fixture').empty();
            Y.lp.app.errors.display_error = this.old_error_method;
        },

        test_library_exists: function () {
            Y.Assert.isObject(Y.lp.services.auth.tokens,
                'Could not locate the lp.services.auth.tokens module');
        },

        test_widget_can_be_instantiated: function () {
            Y.Assert.isInstanceOf(
                Y.lp.services.auth.tokens.CreateTokenWidget,
                this.widget, 'Widget failed to be instantiated');
        },

        test_create_no_description: function () {
            var error_shown = false;
            Y.lp.app.errors.display_error = function(flash_node, msg) {
                Y.Assert.areEqual(
                    Y.one('[name="field.description"]'), flash_node);
                Y.Assert.areEqual(
                    'A personal access token must have a description.', msg);
                error_shown = true;
            };

            this.widget.render();
            Y.one('#create-token-button').simulate('click');
            Y.Assert.isTrue(error_shown);
        },

        test_create_no_scopes: function () {
            var error_shown = false;
            Y.lp.app.errors.display_error = function(flash_node, msg) {
                Y.Assert.isNull(flash_node);
                Y.Assert.areEqual(
                    'A personal access token must have scopes.', msg);
                error_shown = true;
            };

            Y.one('[name="field.description"]').set('value', 'Test');
            this.widget.render();
            Y.one('#create-token-button').simulate('click');
            Y.Assert.isTrue(error_shown);
        },

        test_create_failure: function () {
            var error_shown = false;
            Y.lp.app.errors.display_error = function(flash_node, msg) {
                Y.Assert.isNull(flash_node);
                Y.Assert.areEqual(
                    'Failed to create personal access token.', msg);
                error_shown = true;
            };

            Y.one('[name="field.description"]').set(
                'value', 'Test description');
            Y.all('[name="field.scopes"]').item(1).set('checked', true);
            this.widget.render();
            Y.one('#create-token-button').simulate('click');
            Y.Assert.isFalse(error_shown);

            this.mockio.failure();
            Y.Assert.isTrue(error_shown);
        },

        test_create: function () {
            var error_shown = false;
            Y.lp.app.errors.display_error = function(flash_node, msg) {
                error_shown = true;
            };

            Y.one('[name="field.description"]').set(
                'value', 'Test description');
            Y.all('[name="field.scopes"]').item(1).set('checked', true);
            this.widget.render();
            Y.one('#create-token-button').simulate('click');
            Y.Assert.isFalse(error_shown);
            Y.Assert.areEqual(1, this.mockio.requests.length);
            Y.Assert.areEqual('/api/devel/repo', this.mockio.last_request.url);
            Y.Assert.areEqual('POST', this.mockio.last_request.config.method);
            Y.Assert.areEqual(
                'ws.op=issueAccessToken' +
                '&description=Test%20description' +
                '&scopes=repository%3Apush',
                this.mockio.last_request.config.data);
            Y.Assert.isFalse(Y.one('.spinner').hasClass('hidden'));

            this.mockio.success({
                responseHeaders: {'Content-Type': 'application/json'},
                responseText: Y.JSON.stringify('test-secret')
            });
            Y.Assert.isTrue(Y.one('.spinner').hasClass('hidden'));
            Y.Assert.areEqual(
                'test-secret', Y.one('#new-token-secret').get('text'));
            Y.Assert.isFalse(
                Y.one('#new-token-information').hasClass('hidden'));
            var token_row = Y.one('#access-tokens-tbody tr');
            Y.Assert.isTrue(token_row.hasClass('yui3-lazr-even'));
            Y.ArrayAssert.itemsAreEqual(
                ['Test description', '', 'repository:push', 'a moment ago',
                 '', 'Never', ''],
                token_row.all('td').map(function (node) {
                    return node.get('text');
                }));
        },

        test_create_with_expiry: function () {
            var error_shown = false;
            Y.lp.app.errors.display_error = function(flash_node, msg) {
                error_shown = true;
            };

            Y.one('[name="field.description"]').set(
                'value', 'Test description');
            Y.all('[name="field.scopes"]').item(0).set('checked', true);
            Y.one('[name="field.date_expires"]').set('value', '2021-01-01');
            this.widget.render();
            Y.one('#create-token-button').simulate('click');
            Y.Assert.isFalse(error_shown);
            Y.Assert.areEqual(1, this.mockio.requests.length);
            Y.Assert.areEqual('/api/devel/repo', this.mockio.last_request.url);
            Y.Assert.areEqual('POST', this.mockio.last_request.config.method);
            Y.Assert.areEqual(
                'ws.op=issueAccessToken' +
                '&description=Test%20description' +
                '&scopes=repository%3Abuild_status' +
                '&date_expires=2021-01-01',
                this.mockio.last_request.config.data);
            Y.Assert.isFalse(Y.one('.spinner').hasClass('hidden'));

            this.mockio.success({
                responseHeaders: {'Content-Type': 'application/json'},
                responseText: Y.JSON.stringify('test-secret')
            });
            Y.Assert.isTrue(Y.one('.spinner').hasClass('hidden'));
            Y.Assert.areEqual(
                'test-secret', Y.one('#new-token-secret').get('text'));
            Y.Assert.isFalse(
                Y.one('#new-token-information').hasClass('hidden'));
            var token_row = Y.one('#access-tokens-tbody tr');
            Y.Assert.isTrue(token_row.hasClass('yui3-lazr-even'));
            Y.ArrayAssert.itemsAreEqual(
                ['Test description', '', 'repository:build_status',
                'a moment ago', '', '2021-01-01', ''],
                token_row.all('td').map(function (node) {
                    return node.get('text');
                }));
        }
    }));

}, '0.1', {
    requires: [
        'json-stringify', 'node-event-simulate', 'test',
        'lp.services.auth.tokens', 'lp.testing.mockio'
    ]
});
