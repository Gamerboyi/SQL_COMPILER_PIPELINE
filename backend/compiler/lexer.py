"""
SQL Lexer — Tokenizes raw SQL input into a stream of classified tokens.

Each token carries:
  - type:     keyword | identifier | number | string | operator | punctuation
  - value:    the literal text
  - line/col: position in source (1-indexed)
  - category: higher-level grouping for color coding in the frontend
"""

import re
from .errors import LexerError


# ── SQL keyword classification ──────────────────────────────────────────────

DML_KEYWORDS = {
    "SELECT", "INSERT", "UPDATE", "DELETE", "INTO", "VALUES", "SET"
}

DDL_KEYWORDS = {
    "CREATE", "DROP", "ALTER", "TABLE", "INDEX", "VIEW",
    "PRIMARY", "KEY", "FOREIGN", "REFERENCES", "CONSTRAINT",
    "DEFAULT", "AUTO_INCREMENT", "UNIQUE", "CHECK"
}

CLAUSE_KEYWORDS = {
    "FROM", "WHERE", "JOIN", "INNER", "LEFT", "RIGHT", "OUTER",
    "FULL", "CROSS", "ON", "USING", "GROUP", "BY", "HAVING",
    "ORDER", "ASC", "DESC", "LIMIT", "OFFSET", "UNION", "ALL",
    "DISTINCT", "AS", "CASE", "WHEN", "THEN", "ELSE", "END"
}

LOGIC_KEYWORDS = {
    "AND", "OR", "NOT", "IN", "BETWEEN", "LIKE", "IS", "NULL",
    "EXISTS", "ANY", "SOME", "TRUE", "FALSE"
}

FUNCTION_KEYWORDS = {
    "COUNT", "SUM", "AVG", "MIN", "MAX", "UPPER", "LOWER",
    "LENGTH", "TRIM", "SUBSTRING", "CONCAT", "COALESCE",
    "IFNULL", "NULLIF", "CAST"
}

TYPE_KEYWORDS = {
    "INT", "INTEGER", "BIGINT", "SMALLINT", "TINYINT",
    "FLOAT", "DOUBLE", "DECIMAL", "NUMERIC", "REAL",
    "VARCHAR", "CHAR", "TEXT", "BLOB", "CLOB",
    "DATE", "TIME", "DATETIME", "TIMESTAMP",
    "BOOLEAN", "BOOL"
}

ALL_KEYWORDS = (
    DML_KEYWORDS | DDL_KEYWORDS | CLAUSE_KEYWORDS |
    LOGIC_KEYWORDS | FUNCTION_KEYWORDS | TYPE_KEYWORDS
)


def _classify_keyword(value):
    """Return the category for a SQL keyword."""
    upper = value.upper()
    if upper in DML_KEYWORDS:
        return "DML"
    if upper in DDL_KEYWORDS:
        return "DDL"
    if upper in CLAUSE_KEYWORDS:
        return "CLAUSE"
    if upper in LOGIC_KEYWORDS:
        return "LOGIC"
    if upper in FUNCTION_KEYWORDS:
        return "FUNCTION"
    if upper in TYPE_KEYWORDS:
        return "TYPE"
    return "KEYWORD"


# ── Token patterns (order matters — first match wins) ───────────────────────

TOKEN_PATTERNS = [
    ("WHITESPACE",  r"[ \t]+"),
    ("NEWLINE",     r"\n"),
    ("COMMENT",     r"--[^\n]*"),
    ("BLOCK_COMMENT", r"/\*[\s\S]*?\*/"),
    ("STRING",      r"'(?:''|[^'])*'"),
    ("QUOTED_ID",   r'"(?:""|[^"])*"'),
    ("NUMBER",      r"\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b"),
    ("OPERATOR",    r"<>|!=|>=|<=|<|>|=|\+|-|\*|/|%|\|\|"),
    ("PUNCTUATION", r"[(),;.\[\]]"),
    ("WORD",        r"[A-Za-z_][A-Za-z0-9_]*"),
]

_master_pattern = re.compile(
    "|".join(
        f"(?P<{name}_{i}>{pattern})"
        for i, (name, pattern) in enumerate(TOKEN_PATTERNS)
    ),
    re.IGNORECASE,
)


# ── Public API ──────────────────────────────────────────────────────────────

def tokenize(sql: str) -> list[dict]:
    """
    Tokenize a SQL string and return a list of token dicts.

    Raises LexerError on unexpected characters.
    """
    tokens = []
    line = 1
    col = 1
    pos = 0

    for match in _master_pattern.finditer(sql):
        start = match.start()

        # Check for unmatched characters
        if start > pos:
            bad = sql[pos:start].strip()
            if bad:
                raise LexerError(
                    f"Unexpected character(s): '{bad}'",
                    line=line, col=col,
                )

        # Determine which group matched
        kind = None
        value = match.group()
        for key in match.groupdict():
            if match.group(key) is not None:
                kind = key.rsplit("_", 1)[0]
                break

        if kind == "NEWLINE":
            line += 1
            col = 1
            pos = match.end()
            continue

        if kind == "WHITESPACE":
            col += len(value)
            pos = match.end()
            continue

        if kind in ("COMMENT", "BLOCK_COMMENT"):
            newlines = value.count("\n")
            if newlines:
                line += newlines
                col = len(value) - value.rfind("\n")
            else:
                col += len(value)
            pos = match.end()
            continue

        # Build token
        token = {
            "type": kind,
            "value": value,
            "line": line,
            "col": col,
        }

        # Reclassify WORDs
        if kind == "WORD":
            if value.upper() in ALL_KEYWORDS:
                token["type"] = "KEYWORD"
                token["category"] = _classify_keyword(value)
            else:
                token["type"] = "IDENTIFIER"
                token["category"] = "IDENTIFIER"
        elif kind == "NUMBER":
            token["category"] = "LITERAL"
        elif kind in ("STRING", "QUOTED_ID"):
            token["type"] = "STRING"
            token["category"] = "LITERAL"
        elif kind == "OPERATOR":
            token["category"] = "OPERATOR"
        elif kind == "PUNCTUATION":
            token["category"] = "PUNCTUATION"
        else:
            token["category"] = kind

        tokens.append(token)
        col += len(value)
        pos = match.end()

    # Check for trailing unmatched characters
    remaining = sql[pos:].strip()
    if remaining:
        raise LexerError(
            f"Unexpected character(s) at end of input: '{remaining}'",
            line=line, col=col,
        )

    return tokens
