from __future__ import annotations

import re
from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.tokens import TokenType


@dataclass
class SQLContext:
    prefix: str
    qualifier: str
    table_context: bool
    tables: dict[str, str]


def context_at(sql: str, cursor_position: int, dialect: str) -> SQLContext:
    before = sql[:cursor_position]
    match = re.search(r"([A-Za-z_][\w]*\.)?([\w]*)$", before)
    prefix = match[2] if match else ""
    qualifier = (match[1] or "").rstrip(".") if match else ""
    table_context = bool(re.search(r"\b(FROM|JOIN|UPDATE|INTO)\s+[\w.]*$", before, re.I))
    tables: dict[str, str] = {}
    try:
        tree = sqlglot.parse_one(sql, read=dialect)
        for table in tree.find_all(exp.Table):
            tables[table.alias_or_name] = ".".join(p.sql(dialect=dialect) for p in table.parts)
    except sqlglot.errors.ParseError:
        # Tokenize incomplete SQL, so keywords inside comments/strings are not treated as tables.
        try:
            tokens = sqlglot.tokenize(sql, read=dialect)
            for i, token in enumerate(tokens[:-1]):
                if token.token_type not in {TokenType.FROM, TokenType.JOIN, TokenType.UPDATE}:
                    continue
                j = i + 1
                if tokens[j].token_type not in {TokenType.VAR, TokenType.IDENTIFIER}:
                    continue
                parts = [tokens[j].text]
                j += 1
                while j + 1 < len(tokens) and tokens[j].token_type == TokenType.DOT:
                    parts.append(tokens[j + 1].text)
                    j += 2
                name = ".".join(parts)
                alias = parts[-1]
                if j < len(tokens) and tokens[j].token_type == TokenType.ALIAS:
                    j += 1
                if j < len(tokens) and tokens[j].token_type in {
                    TokenType.VAR,
                    TokenType.IDENTIFIER,
                }:
                    alias = tokens[j].text
                tables[alias] = name
        except sqlglot.errors.TokenError:
            pass
    return SQLContext(prefix, qualifier, table_context, tables)
