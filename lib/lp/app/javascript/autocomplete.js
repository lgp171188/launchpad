/* Copyright 2017 Canonical Ltd.  This software is licensed under the
 * GNU Affero General Public License version 3 (see the file LICENSE).
 */

YUI.add('lp.app.autocomplete', function (Y) {

    var namespace = Y.namespace('lp.app.autocomplete');

    namespace.getRepositoryCompletionURI = function (repo_node) {
        var entered_uri = repo_node.get('value');
        if (entered_uri.startsWith("lp:")) {
            var split = "+code/" + entered_uri.split("lp:")[1];
            entered_uri = encodeURI(split);
        }
        else if (entered_uri.startsWith("~")) {
            entered_uri = encodeURI(entered_uri);
        }
        else if (entered_uri.includes("://")) {
            return null;
        }
        else if (entered_uri.startsWith("git@")) {
            return null;
        }
        else {
            entered_uri = encodeURI("+code/" + entered_uri);
        }

        var uri = '/';
        uri += entered_uri;
        uri += '/@@+huge-vocabulary';
        return uri;
    };

    namespace.getRepoNode = function (path_node) {
        var split = path_node._node['id'].split('.');
        split[2] = 'repository';
        var repository_target = split.join('.');
        var target_repo = Y.one('[id="' + repository_target + '"]');
        return target_repo;
    };

    namespace.getPathNode = function (path_node) {
        var split = path_node._node['id'].split('.');
        split[2] = 'path';
        var path_target = split.join('.');
        var target_path = Y.one('[id="' + path_target + '"]');
        return target_path;
    };

    namespace.setupVocabAutocomplete = function (config, node) {
        var qs = 'name=' + encodeURIComponent(config.vocabulary_name);

        /* autocomplete will substitute these with appropriate encoding. */
        /* XXX cjwatson 2017-07-24: Perhaps we should pass batch={maxResults}
         * too, but we need to make sure that it doesn't exceed max_batch_size.
         */
        qs += '&search_text={query}';

        var repo_node = namespace.getRepoNode(node);
        var uri = namespace.getRepositoryCompletionURI(repo_node);

        node.plug(Y.Plugin.AutoComplete, {
            queryDelay: 500,  // milliseconds
            requestTemplate: '?' + qs,
            resultHighlighter: 'wordMatch',
            resultListLocator: 'entries',
            resultTextLocator: 'value',
            source: uri
        });

        repo_node.updated = function () {
            var uri = namespace.getRepositoryCompletionURI(this);
            var path_node = namespace.getPathNode(this);
            path_node.ac.set("source", uri);
        };
        // ideally this should take node to rebind `this` in the function
        // but we're also calling it from the popup picker, which has a direct
        // reference to the repo_node, so maintain the local `this` binding.
        repo_node.on('valuechange', repo_node.updated);
    };

    /**
     * Add autocompletion to a text field.
     * @param {Object} config Object literal of config name/value pairs.
     *     config.vocabulary_name: the named vocabulary to select from.
     *     config.input_element: the id of the text field to update with the
     *                           selected value.
     */
    namespace.addAutocomplete = function (config) {
        var input_element = Y.one('[id="' + config.input_element + '"]');
        // The node may already have been processed.
        if (input_element.ac) {
            return;
        }
        namespace.setupVocabAutocomplete(config, input_element);
    };

}, '0.1', {
    'requires': [
        'autocomplete', 'autocomplete-sources', 'datasource', 'lp'
    ]
});
