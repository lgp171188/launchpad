# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Parser for go.mod files.

These are specified in https://go.dev/ref/mod#go-mod-file.
"""

__all__ = [
    "GoModParserException",
    "parse_go_mod",
]

import string
from contextlib import contextmanager
from typing import Iterator

import pyparsing as pp


@contextmanager
def pyparsing_whitespace_chars(chars: str) -> Iterator[None]:
    """Temporarily override `pyparsing`'s default whitespace characters.

    `pyparsing` lets us override the whitespace characters for a single parser
    element, or globally.  We want to override them for all the elements in
    this parser, but don't want to leave that state lying around for anything
    else in the same process that might use `pyparsing`.
    """
    original_chars = pp.ParserElement.DEFAULT_WHITE_CHARS
    try:
        pp.ParserElement.setDefaultWhitespaceChars(chars)
        yield
    finally:
        pp.ParserElement.setDefaultWhitespaceChars(original_chars)


# "\n" is significant in go.mod files, so tell pyparsing not to treat it as
# ordinary whitespace.
@pyparsing_whitespace_chars(" \t\r")
def make_go_mod_parser() -> pp.ParserElement:
    lparen = pp.Literal("(")
    rparen = pp.Literal(")")
    newline = pp.Literal("\n")

    comment = pp.dblSlashComment.copy()
    ident = pp.Word(
        # This seems very broad, but it appears to be what the specification
        # calls for and what the official lexer in
        # https://cs.opensource.google/go/x/mod/+/master:modfile/read.go
        # does.
        "".join(
            c
            for c in string.printable
            if c not in string.whitespace + '()[]{},"`'
        )
    ).setName("identifier")
    interpreted_string = pp.QuotedString(quoteChar='"', escChar="\\").setName(
        "interpreted string"
    )
    raw_string = pp.QuotedString(quoteChar="`", multiline=True).setName(
        "raw string"
    )
    quoted_string = interpreted_string | raw_string

    module_keyword = pp.Keyword("module")
    module_path = (ident | quoted_string).setResultsName("module_path")
    module_directive = (
        module_keyword
        - (module_path | (lparen + newline + module_path + newline + rparen))
        + newline
    )

    # The official EBNF for go.mod includes a number of other directives,
    # but we aren't interested in those, and relying on having a current
    # list of all the possible directives would mean that we'd have to keep
    # updating this code as the syntax for go.mod is extended.  Instead, add
    # some generic parser elements covering the general form of those other
    # directives.  (The official parser in
    # https://cs.opensource.google/go/x/mod/+/master:modfile/rule.go has a
    # similar rationale for its "ParseLax" function.)
    line_block = (
        ident
        + pp.nestedExpr(
            opener="(", closer=")", ignoreExpr=comment | quoted_string
        )
        + newline
    )
    line = ident + pp.restOfLine + newline

    return pp.ZeroOrMore(
        module_directive | line_block | line | newline
    ).ignore(comment)


go_mod_parser = make_go_mod_parser()


class GoModParserException(Exception):
    pass


def parse_go_mod(text: str) -> str:
    """Parse a `go.mod` file, returning the module path."""
    try:
        parsed = go_mod_parser.parseString(text, parseAll=True)
    except pp.ParseBaseException as e:
        # pyparsing's exceptions are excessively detailed for our purposes,
        # often including the whole grammar.  Raise something a bit more
        # concise.
        raise GoModParserException(
            "Parse failed at line %d, column %d" % (e.lineno, e.column)
        )
    if "module_path" not in parsed:
        raise GoModParserException("No 'module' directive found")
    return parsed["module_path"]
