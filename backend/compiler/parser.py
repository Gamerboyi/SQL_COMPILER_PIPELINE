"""
SQL Parser — Recursive-descent parser that produces an Abstract Syntax Tree.

Supported statements:
  SELECT, INSERT INTO, UPDATE, DELETE FROM, CREATE TABLE, DROP TABLE

The AST is a nested dict structure, fully JSON-serializable, designed to be
rendered as an interactive tree in the frontend.
"""

from .errors import ParserError


# ─── helpers ────────────────────────────────────────────────────────────────

def _kw(token, *keywords):
    """Check if token is a KEYWORD with one of the given values (case-insensitive)."""
    return (
        token is not None
        and token["type"] == "KEYWORD"
        and token["value"].upper() in {k.upper() for k in keywords}
    )


def _op(token, *operators):
    return token is not None and token["type"] == "OPERATOR" and token["value"] in operators


def _punc(token, *chars):
    return token is not None and token["type"] == "PUNCTUATION" and token["value"] in chars


# ─── Parser class ───────────────────────────────────────────────────────────

class Parser:
    """Recursive-descent SQL parser."""

    def __init__(self, tokens: list[dict]):
        # Filter out any remaining whitespace/comment tokens (should already be gone)
        self.tokens = [t for t in tokens if t["type"] not in ("WHITESPACE", "NEWLINE", "COMMENT")]
        self.pos = 0

    # -- cursor helpers --

    def _peek(self):
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return None

    def _advance(self):
        tok = self._peek()
        if tok is None:
            raise ParserError("Unexpected end of input")
        self.pos += 1
        return tok

    def _expect_keyword(self, *keywords):
        tok = self._peek()
        if not _kw(tok, *keywords):
            expected = " or ".join(keywords)
            got = tok["value"] if tok else "end of input"
            raise ParserError(
                f"Expected {expected}, got '{got}'",
                line=tok["line"] if tok else None,
                col=tok["col"] if tok else None,
            )
        return self._advance()

    def _expect_punc(self, char):
        tok = self._peek()
        if not _punc(tok, char):
            got = tok["value"] if tok else "end of input"
            raise ParserError(
                f"Expected '{char}', got '{got}'",
                line=tok["line"] if tok else None,
                col=tok["col"] if tok else None,
            )
        return self._advance()

    def _at_end(self):
        return self.pos >= len(self.tokens)

    def _match_keyword(self, *keywords):
        tok = self._peek()
        if _kw(tok, *keywords):
            return self._advance()
        return None

    def _match_punc(self, *chars):
        tok = self._peek()
        if _punc(tok, *chars):
            return self._advance()
        return None

    # -- entry point --

    def parse(self) -> dict:
        """Parse the token stream and return an AST dict."""
        stmt = self._parse_statement()
        # consume optional trailing semicolon
        self._match_punc(";")
        if not self._at_end():
            tok = self._peek()
            raise ParserError(
                f"Unexpected token after statement: '{tok['value']}'",
                line=tok["line"], col=tok["col"],
            )
        return stmt

    # -- statement dispatch --

    def _parse_statement(self):
        tok = self._peek()
        if tok is None:
            raise ParserError("Empty input — no SQL statement found")

        upper = tok["value"].upper() if tok["type"] == "KEYWORD" else ""
        if upper == "SELECT":
            return self._parse_select()
        elif upper == "INSERT":
            return self._parse_insert()
        elif upper == "UPDATE":
            return self._parse_update()
        elif upper == "DELETE":
            return self._parse_delete()
        elif upper == "CREATE":
            return self._parse_create_table()
        elif upper == "DROP":
            return self._parse_drop_table()
        else:
            raise ParserError(
                f"Unsupported statement starting with '{tok['value']}'",
                line=tok["line"], col=tok["col"],
            )

    # ── SELECT ──────────────────────────────────────────────────────────────

    def _parse_select(self):
        self._expect_keyword("SELECT")
        node = {"type": "SelectStatement", "children": {}}

        # DISTINCT
        if self._match_keyword("DISTINCT"):
            node["children"]["distinct"] = True

        # select list
        node["children"]["columns"] = self._parse_select_list()

        # FROM
        if _kw(self._peek(), "FROM"):
            self._advance()
            node["children"]["from"] = self._parse_from_clause()

        # joins
        joins = self._parse_joins()
        if joins:
            node["children"]["joins"] = joins

        # WHERE
        if _kw(self._peek(), "WHERE"):
            self._advance()
            node["children"]["where"] = self._parse_expression()

        # GROUP BY
        if _kw(self._peek(), "GROUP"):
            self._advance()
            self._expect_keyword("BY")
            node["children"]["group_by"] = self._parse_expression_list()

        # HAVING
        if _kw(self._peek(), "HAVING"):
            self._advance()
            node["children"]["having"] = self._parse_expression()

        # ORDER BY
        if _kw(self._peek(), "ORDER"):
            self._advance()
            self._expect_keyword("BY")
            node["children"]["order_by"] = self._parse_order_by_list()

        # LIMIT
        if _kw(self._peek(), "LIMIT"):
            self._advance()
            node["children"]["limit"] = self._parse_expression()

        # OFFSET
        if _kw(self._peek(), "OFFSET"):
            self._advance()
            node["children"]["offset"] = self._parse_expression()

        return node

    def _parse_select_list(self):
        """Parse comma-separated select items (column, *, expression AS alias)."""
        items = []
        items.append(self._parse_select_item())
        while self._match_punc(","):
            items.append(self._parse_select_item())
        return items

    def _parse_select_item(self):
        tok = self._peek()
        # *
        if _op(tok, "*"):
            self._advance()
            return {"type": "Star", "value": "*"}

        # table.*
        if tok and tok["type"] == "IDENTIFIER":
            next_tok = self.tokens[self.pos + 1] if self.pos + 1 < len(self.tokens) else None
            if _punc(next_tok, "."):
                star_tok = self.tokens[self.pos + 2] if self.pos + 2 < len(self.tokens) else None
                if _op(star_tok, "*"):
                    table = self._advance()
                    self._advance()  # .
                    self._advance()  # *
                    item = {"type": "QualifiedStar", "table": table["value"]}
                    if self._match_keyword("AS"):
                        alias_tok = self._advance()
                        item["alias"] = alias_tok["value"]
                    return item

        expr = self._parse_expression()
        if self._match_keyword("AS"):
            alias_tok = self._advance()
            return {"type": "AliasedExpression", "expression": expr, "alias": alias_tok["value"]}
        # implicit alias (identifier right after expression without AS)  
        tok = self._peek()
        if tok and tok["type"] == "IDENTIFIER" and not _kw(tok, "FROM", "WHERE", "JOIN", "INNER",
                "LEFT", "RIGHT", "FULL", "CROSS", "ON", "GROUP", "ORDER", "HAVING", "LIMIT",
                "OFFSET", "UNION"):
            alias_tok = self._advance()
            return {"type": "AliasedExpression", "expression": expr, "alias": alias_tok["value"]}
        return expr

    # ── FROM clause ─────────────────────────────────────────────────────────

    def _parse_from_clause(self):
        """Parse FROM table references (simple table, aliased, subquery)."""
        tables = []
        tables.append(self._parse_table_ref())
        while self._match_punc(","):
            tables.append(self._parse_table_ref())
        return tables

    def _parse_table_ref(self):
        tok = self._peek()

        # Subquery: ( SELECT ... )
        if _punc(tok, "("):
            self._advance()
            sub = self._parse_select()
            self._expect_punc(")")
            node = {"type": "Subquery", "query": sub}
            if self._match_keyword("AS"):
                alias_tok = self._advance()
                node["alias"] = alias_tok["value"]
            elif self._peek() and self._peek()["type"] == "IDENTIFIER":
                alias_tok = self._advance()
                node["alias"] = alias_tok["value"]
            return node

        # Regular table name
        name_tok = self._advance()
        node = {"type": "TableRef", "name": name_tok["value"]}

        # Optional alias
        if self._match_keyword("AS"):
            alias_tok = self._advance()
            node["alias"] = alias_tok["value"]
        elif self._peek() and self._peek()["type"] == "IDENTIFIER" and not _kw(
            self._peek(), "WHERE", "JOIN", "INNER", "LEFT", "RIGHT", "FULL",
            "CROSS", "ON", "GROUP", "ORDER", "HAVING", "LIMIT", "SET"
        ):
            alias_tok = self._advance()
            node["alias"] = alias_tok["value"]

        return node

    # ── JOINs ───────────────────────────────────────────────────────────────

    def _parse_joins(self):
        joins = []
        while True:
            join_type = None
            tok = self._peek()
            if _kw(tok, "JOIN"):
                join_type = "INNER JOIN"
                self._advance()
            elif _kw(tok, "INNER"):
                self._advance()
                self._expect_keyword("JOIN")
                join_type = "INNER JOIN"
            elif _kw(tok, "LEFT"):
                self._advance()
                self._match_keyword("OUTER")
                self._expect_keyword("JOIN")
                join_type = "LEFT JOIN"
            elif _kw(tok, "RIGHT"):
                self._advance()
                self._match_keyword("OUTER")
                self._expect_keyword("JOIN")
                join_type = "RIGHT JOIN"
            elif _kw(tok, "FULL"):
                self._advance()
                self._match_keyword("OUTER")
                self._expect_keyword("JOIN")
                join_type = "FULL JOIN"
            elif _kw(tok, "CROSS"):
                self._advance()
                self._expect_keyword("JOIN")
                join_type = "CROSS JOIN"
            else:
                break

            table = self._parse_table_ref()
            condition = None
            if _kw(self._peek(), "ON"):
                self._advance()
                condition = self._parse_expression()

            joins.append({
                "type": "Join",
                "join_type": join_type,
                "table": table,
                "condition": condition,
            })
        return joins

    # ── INSERT ──────────────────────────────────────────────────────────────

    def _parse_insert(self):
        self._expect_keyword("INSERT")
        self._expect_keyword("INTO")
        table_tok = self._advance()
        node = {
            "type": "InsertStatement",
            "children": {
                "table": {"type": "TableRef", "name": table_tok["value"]},
            },
        }

        # Optional column list
        if _punc(self._peek(), "("):
            self._advance()
            cols = []
            cols.append(self._advance()["value"])
            while self._match_punc(","):
                cols.append(self._advance()["value"])
            self._expect_punc(")")
            node["children"]["columns"] = cols

        self._expect_keyword("VALUES")

        # Values can be multiple rows: VALUES (...), (...)
        rows = []
        rows.append(self._parse_value_row())
        while self._match_punc(","):
            rows.append(self._parse_value_row())
        node["children"]["values"] = rows

        return node

    def _parse_value_row(self):
        self._expect_punc("(")
        values = []
        values.append(self._parse_expression())
        while self._match_punc(","):
            values.append(self._parse_expression())
        self._expect_punc(")")
        return values

    # ── UPDATE ──────────────────────────────────────────────────────────────

    def _parse_update(self):
        self._expect_keyword("UPDATE")
        table_tok = self._advance()
        self._expect_keyword("SET")

        assignments = []
        assignments.append(self._parse_assignment())
        while self._match_punc(","):
            assignments.append(self._parse_assignment())

        node = {
            "type": "UpdateStatement",
            "children": {
                "table": {"type": "TableRef", "name": table_tok["value"]},
                "assignments": assignments,
            },
        }

        if _kw(self._peek(), "WHERE"):
            self._advance()
            node["children"]["where"] = self._parse_expression()

        return node

    def _parse_assignment(self):
        col_tok = self._advance()
        self._expect_punc_or_op("=")
        expr = self._parse_expression()
        return {"type": "Assignment", "column": col_tok["value"], "value": expr}

    def _expect_punc_or_op(self, char):
        tok = self._peek()
        if _punc(tok, char) or _op(tok, char):
            return self._advance()
        got = tok["value"] if tok else "end of input"
        raise ParserError(
            f"Expected '{char}', got '{got}'",
            line=tok["line"] if tok else None,
            col=tok["col"] if tok else None,
        )

    # ── DELETE ──────────────────────────────────────────────────────────────

    def _parse_delete(self):
        self._expect_keyword("DELETE")
        self._expect_keyword("FROM")
        table_tok = self._advance()

        node = {
            "type": "DeleteStatement",
            "children": {
                "table": {"type": "TableRef", "name": table_tok["value"]},
            },
        }

        if _kw(self._peek(), "WHERE"):
            self._advance()
            node["children"]["where"] = self._parse_expression()

        return node

    # ── CREATE TABLE ────────────────────────────────────────────────────────

    def _parse_create_table(self):
        self._expect_keyword("CREATE")
        self._expect_keyword("TABLE")
        table_tok = self._advance()

        self._expect_punc("(")
        columns = []
        columns.append(self._parse_column_def())
        while self._match_punc(","):
            # Check if it's a constraint rather than another column
            tok = self._peek()
            if _kw(tok, "PRIMARY", "FOREIGN", "UNIQUE", "CHECK", "CONSTRAINT"):
                # Skip table-level constraints for simplicity — just consume until , or )
                depth = 0
                while not self._at_end():
                    t = self._peek()
                    if _punc(t, "("):
                        depth += 1
                        self._advance()
                    elif _punc(t, ")"):
                        if depth == 0:
                            break
                        depth -= 1
                        self._advance()
                    elif _punc(t, ",") and depth == 0:
                        break
                    else:
                        self._advance()
                continue
            columns.append(self._parse_column_def())
        self._expect_punc(")")

        return {
            "type": "CreateTableStatement",
            "children": {
                "table": {"type": "TableRef", "name": table_tok["value"]},
                "columns": columns,
            },
        }

    def _parse_column_def(self):
        name_tok = self._advance()
        col = {"type": "ColumnDef", "name": name_tok["value"], "constraints": []}

        # Data type
        type_tok = self._peek()
        if type_tok and (type_tok["type"] == "KEYWORD" or type_tok["type"] == "IDENTIFIER"):
            self._advance()
            col["data_type"] = type_tok["value"].upper()

            # VARCHAR(n), DECIMAL(p,s)
            if _punc(self._peek(), "("):
                self._advance()
                params = [self._advance()["value"]]
                while self._match_punc(","):
                    params.append(self._advance()["value"])
                self._expect_punc(")")
                col["type_params"] = params

        # Column constraints
        while True:
            tok = self._peek()
            if _kw(tok, "PRIMARY"):
                self._advance()
                self._expect_keyword("KEY")
                col["constraints"].append("PRIMARY KEY")
            elif _kw(tok, "NOT"):
                self._advance()
                self._expect_keyword("NULL")
                col["constraints"].append("NOT NULL")
            elif _kw(tok, "UNIQUE"):
                self._advance()
                col["constraints"].append("UNIQUE")
            elif _kw(tok, "DEFAULT"):
                self._advance()
                default_val = self._parse_expression()
                col["constraints"].append({"DEFAULT": default_val})
            elif _kw(tok, "AUTO_INCREMENT"):
                self._advance()
                col["constraints"].append("AUTO_INCREMENT")
            elif _kw(tok, "NULL"):
                self._advance()
                col["constraints"].append("NULL")
            else:
                break

        return col

    # ── DROP TABLE ──────────────────────────────────────────────────────────

    def _parse_drop_table(self):
        self._expect_keyword("DROP")
        self._expect_keyword("TABLE")

        if_exists = False
        if _kw(self._peek(), "IF"):
            self._advance()
            self._expect_keyword("EXISTS")
            if_exists = True

        table_tok = self._advance()
        return {
            "type": "DropTableStatement",
            "children": {
                "table": {"type": "TableRef", "name": table_tok["value"]},
                "if_exists": if_exists,
            },
        }

    # ── Expressions (with precedence) ──────────────────────────────────────

    def _parse_expression(self):
        return self._parse_or()

    def _parse_or(self):
        left = self._parse_and()
        while _kw(self._peek(), "OR"):
            op_tok = self._advance()
            right = self._parse_and()
            left = {"type": "BinaryExpression", "operator": "OR", "left": left, "right": right}
        return left

    def _parse_and(self):
        left = self._parse_not()
        while _kw(self._peek(), "AND"):
            op_tok = self._advance()
            right = self._parse_not()
            left = {"type": "BinaryExpression", "operator": "AND", "left": left, "right": right}
        return left

    def _parse_not(self):
        if _kw(self._peek(), "NOT"):
            self._advance()
            expr = self._parse_not()
            return {"type": "UnaryExpression", "operator": "NOT", "operand": expr}
        return self._parse_comparison()

    def _parse_comparison(self):
        left = self._parse_addition()

        tok = self._peek()

        # IS [NOT] NULL
        if _kw(tok, "IS"):
            self._advance()
            if _kw(self._peek(), "NOT"):
                self._advance()
                self._expect_keyword("NULL")
                return {"type": "IsExpression", "expression": left, "negated": True}
            self._expect_keyword("NULL")
            return {"type": "IsExpression", "expression": left, "negated": False}

        # [NOT] IN (...)
        negated = False
        if _kw(tok, "NOT"):
            saved = self.pos
            self._advance()
            if _kw(self._peek(), "IN"):
                negated = True
                tok = self._peek()
            elif _kw(self._peek(), "BETWEEN"):
                negated = True
                tok = self._peek()
            elif _kw(self._peek(), "LIKE"):
                negated = True
                tok = self._peek()
            else:
                self.pos = saved
                tok = self._peek()

        if _kw(tok, "IN"):
            self._advance()
            self._expect_punc("(")
            # Could be subquery or value list
            if _kw(self._peek(), "SELECT"):
                subquery = self._parse_select()
                self._expect_punc(")")
                return {"type": "InExpression", "expression": left, "values": {"type": "Subquery", "query": subquery}, "negated": negated}
            values = self._parse_expression_list()
            self._expect_punc(")")
            return {"type": "InExpression", "expression": left, "values": values, "negated": negated}

        # [NOT] BETWEEN x AND y
        if _kw(tok, "BETWEEN"):
            self._advance()
            low = self._parse_addition()
            self._expect_keyword("AND")
            high = self._parse_addition()
            return {"type": "BetweenExpression", "expression": left, "low": low, "high": high, "negated": negated}

        # [NOT] LIKE
        if _kw(tok, "LIKE"):
            self._advance()
            pattern = self._parse_addition()
            return {"type": "LikeExpression", "expression": left, "pattern": pattern, "negated": negated}

        # Standard comparison operators
        if _op(tok, "=", "!=", "<>", "<", ">", "<=", ">="):
            op_tok = self._advance()
            right = self._parse_addition()
            return {"type": "BinaryExpression", "operator": op_tok["value"], "left": left, "right": right}

        return left

    def _parse_addition(self):
        left = self._parse_multiplication()
        while _op(self._peek(), "+", "-", "||"):
            op_tok = self._advance()
            right = self._parse_multiplication()
            left = {"type": "BinaryExpression", "operator": op_tok["value"], "left": left, "right": right}
        return left

    def _parse_multiplication(self):
        left = self._parse_unary()
        while _op(self._peek(), "*", "/", "%"):
            op_tok = self._advance()
            right = self._parse_unary()
            left = {"type": "BinaryExpression", "operator": op_tok["value"], "left": left, "right": right}
        return left

    def _parse_unary(self):
        if _op(self._peek(), "-", "+"):
            op_tok = self._advance()
            expr = self._parse_primary()
            return {"type": "UnaryExpression", "operator": op_tok["value"], "operand": expr}
        return self._parse_primary()

    def _parse_primary(self):
        tok = self._peek()
        if tok is None:
            raise ParserError("Unexpected end of input in expression")

        # Parenthesized expression or subquery
        if _punc(tok, "("):
            self._advance()
            if _kw(self._peek(), "SELECT"):
                sub = self._parse_select()
                self._expect_punc(")")
                return {"type": "Subquery", "query": sub}
            expr = self._parse_expression()
            self._expect_punc(")")
            return {"type": "Grouped", "expression": expr}

        # Number literal
        if tok["type"] == "NUMBER":
            self._advance()
            return {"type": "NumberLiteral", "value": tok["value"]}

        # String literal
        if tok["type"] == "STRING":
            self._advance()
            return {"type": "StringLiteral", "value": tok["value"]}

        # NULL
        if _kw(tok, "NULL"):
            self._advance()
            return {"type": "NullLiteral", "value": "NULL"}

        # TRUE / FALSE
        if _kw(tok, "TRUE", "FALSE"):
            self._advance()
            return {"type": "BooleanLiteral", "value": tok["value"].upper()}

        # CASE expression
        if _kw(tok, "CASE"):
            return self._parse_case()

        # EXISTS (subquery)
        if _kw(tok, "EXISTS"):
            self._advance()
            self._expect_punc("(")
            sub = self._parse_select()
            self._expect_punc(")")
            return {"type": "ExistsExpression", "query": sub}

        # CAST(expr AS type)
        if _kw(tok, "CAST"):
            self._advance()
            self._expect_punc("(")
            expr = self._parse_expression()
            self._expect_keyword("AS")
            type_tok = self._advance()
            cast_type = type_tok["value"]
            # optional (n) like VARCHAR(100)
            if _punc(self._peek(), "("):
                self._advance()
                self._advance()  # skip the number
                self._expect_punc(")")
            self._expect_punc(")")
            return {"type": "CastExpression", "expression": expr, "cast_type": cast_type}

        # Function call or identifier
        if tok["type"] in ("IDENTIFIER", "KEYWORD") and tok["value"].upper() in (
            "COUNT", "SUM", "AVG", "MIN", "MAX", "UPPER", "LOWER",
            "LENGTH", "TRIM", "SUBSTRING", "CONCAT", "COALESCE",
            "IFNULL", "NULLIF",
        ):
            return self._parse_function_call()

        if tok["type"] == "IDENTIFIER":
            self._advance()
            # Qualified name: table.column
            if _punc(self._peek(), "."):
                self._advance()
                col_tok = self._advance()
                return {"type": "QualifiedIdentifier", "table": tok["value"], "column": col_tok["value"]}
            return {"type": "Identifier", "value": tok["value"]}

        # Star (for COUNT(*) etc.)
        if _op(tok, "*"):
            self._advance()
            return {"type": "Star", "value": "*"}

        raise ParserError(
            f"Unexpected token in expression: '{tok['value']}'",
            line=tok["line"], col=tok["col"],
        )

    def _parse_function_call(self):
        name_tok = self._advance()
        self._expect_punc("(")

        args = []
        # COUNT(DISTINCT col)
        distinct = False
        if _kw(self._peek(), "DISTINCT"):
            self._advance()
            distinct = True

        if not _punc(self._peek(), ")"):
            args.append(self._parse_expression())
            while self._match_punc(","):
                args.append(self._parse_expression())

        self._expect_punc(")")

        node = {
            "type": "FunctionCall",
            "name": name_tok["value"].upper(),
            "arguments": args,
        }
        if distinct:
            node["distinct"] = True
        return node

    def _parse_case(self):
        self._expect_keyword("CASE")
        whens = []
        else_expr = None

        while _kw(self._peek(), "WHEN"):
            self._advance()
            condition = self._parse_expression()
            self._expect_keyword("THEN")
            result = self._parse_expression()
            whens.append({"condition": condition, "result": result})

        if _kw(self._peek(), "ELSE"):
            self._advance()
            else_expr = self._parse_expression()

        self._expect_keyword("END")
        return {"type": "CaseExpression", "whens": whens, "else": else_expr}

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _parse_expression_list(self):
        exprs = []
        exprs.append(self._parse_expression())
        while self._match_punc(","):
            exprs.append(self._parse_expression())
        return exprs

    def _parse_order_by_list(self):
        items = []
        expr = self._parse_expression()
        direction = "ASC"
        if self._match_keyword("ASC"):
            direction = "ASC"
        elif self._match_keyword("DESC"):
            direction = "DESC"
        items.append({"type": "OrderByItem", "expression": expr, "direction": direction})

        while self._match_punc(","):
            expr = self._parse_expression()
            direction = "ASC"
            if self._match_keyword("ASC"):
                direction = "ASC"
            elif self._match_keyword("DESC"):
                direction = "DESC"
            items.append({"type": "OrderByItem", "expression": expr, "direction": direction})

        return items


# ── Public API ──────────────────────────────────────────────────────────────

def parse(tokens: list[dict]) -> dict:
    """Parse a list of tokens into an AST dict."""
    return Parser(tokens).parse()
