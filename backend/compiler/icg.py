"""
Intermediate Code Generator — Converts AST to relational algebra representation.

Produces a tree of relational algebra operations:
  σ  — Selection (filter / WHERE)
  π  — Projection (column selection)
  ⋈  — Join
  γ  — Grouping / Aggregation
  τ  — Sort (ORDER BY)
  ρ  — Rename (alias)
  δ  — Distinct

Each node is a JSON-serializable dict with a human-readable string representation.
"""


class ICGenerator:
    """Generates relational algebra intermediate representation from an AST."""

    def __init__(self):
        self.steps = []  # Step-by-step explanation for the frontend

    def generate(self, ast: dict) -> dict:
        """
        Generate IR from an AST.

        Returns:
          - ir_tree: the relational algebra tree (dict)
          - readable: human-readable relational algebra string
          - steps: step-by-step explanation of the generation process
        """
        ir = self._gen_node(ast)
        readable = self._to_string(ir)

        return {
            "ir_tree": ir,
            "readable": readable,
            "steps": self.steps,
        }

    def _gen_node(self, node):
        if not isinstance(node, dict) or "type" not in node:
            return {"op": "UNKNOWN", "detail": str(node)}

        handler = {
            "SelectStatement":      self._gen_select,
            "InsertStatement":      self._gen_insert,
            "UpdateStatement":      self._gen_update,
            "DeleteStatement":      self._gen_delete,
            "CreateTableStatement": self._gen_create,
            "DropTableStatement":   self._gen_drop,
        }.get(node["type"])

        if handler:
            return handler(node)
        return {"op": "UNKNOWN", "detail": node["type"]}

    # ── SELECT → Relational Algebra ─────────────────────────────────────────

    def _gen_select(self, node):
        children = node.get("children", {})

        # Start from base tables (FROM clause)
        from_tables = children.get("from", [])
        if not from_tables:
            return {"op": "EMPTY_SET"}

        # Build base relation(s)
        if len(from_tables) == 1:
            current = self._table_node(from_tables[0])
        else:
            # Cross product of multiple tables in FROM
            current = self._table_node(from_tables[0])
            for t in from_tables[1:]:
                right = self._table_node(t)
                current = {"op": "CROSS_PRODUCT", "symbol": "×", "left": current, "right": right}
                self.steps.append(f"Cross product: {self._to_string(current)}")

        # Apply JOINs
        for join in children.get("joins", []):
            table = self._table_node(join.get("table", {}))
            condition = join.get("condition")
            join_type = join.get("join_type", "INNER JOIN")

            if join_type == "CROSS JOIN":
                current = {"op": "CROSS_PRODUCT", "symbol": "×", "left": current, "right": table}
            else:
                cond_str = self._expr_to_string(condition) if condition else "TRUE"
                symbol_map = {
                    "INNER JOIN": "⋈",
                    "LEFT JOIN": "⟕",
                    "RIGHT JOIN": "⟖",
                    "FULL JOIN": "⟗",
                }
                current = {
                    "op": "JOIN",
                    "join_type": join_type,
                    "symbol": symbol_map.get(join_type, "⋈"),
                    "condition": cond_str,
                    "left": current,
                    "right": table,
                }
            self.steps.append(f"Apply {join_type}: {self._to_string(current)}")

        # Apply WHERE (Selection: σ)
        where = children.get("where")
        if where:
            cond_str = self._expr_to_string(where)
            current = {"op": "SELECTION", "symbol": "σ", "condition": cond_str, "input": current}
            self.steps.append(f"Apply selection (WHERE): σ_{{{cond_str}}}")

        # Apply GROUP BY (Grouping: γ)
        group_by = children.get("group_by", [])
        if group_by:
            group_cols = ", ".join(self._expr_to_string(e) for e in group_by)
            # Collect aggregate functions from select list
            agg_funcs = self._extract_aggregates(children.get("columns", []))
            agg_str = ", ".join(agg_funcs) if agg_funcs else ""
            current = {
                "op": "GROUPING",
                "symbol": "γ",
                "group_by": group_cols,
                "aggregates": agg_str,
                "input": current,
            }
            self.steps.append(f"Apply grouping: γ_{{{group_cols}}}[{agg_str}]")

        # Apply HAVING (Selection after grouping: σ)
        having = children.get("having")
        if having:
            cond_str = self._expr_to_string(having)
            current = {"op": "SELECTION", "symbol": "σ", "condition": cond_str, "note": "HAVING", "input": current}
            self.steps.append(f"Apply HAVING filter: σ_{{{cond_str}}}")

        # Apply Projection (π) — SELECT columns
        columns = children.get("columns", [])
        col_strs = self._columns_to_strings(columns)
        if col_strs and col_strs != ["*"]:
            current = {"op": "PROJECTION", "symbol": "π", "columns": ", ".join(col_strs), "input": current}
            self.steps.append(f"Apply projection: π_{{{', '.join(col_strs)}}}")

        # Apply DISTINCT (δ)
        if children.get("distinct"):
            current = {"op": "DISTINCT", "symbol": "δ", "input": current}
            self.steps.append("Apply distinct: δ")

        # Apply ORDER BY (τ)
        order_by = children.get("order_by", [])
        if order_by:
            sort_strs = []
            for item in order_by:
                expr_str = self._expr_to_string(item.get("expression", {}))
                direction = item.get("direction", "ASC")
                sort_strs.append(f"{expr_str} {direction}")
            current = {"op": "SORT", "symbol": "τ", "order": ", ".join(sort_strs), "input": current}
            self.steps.append(f"Apply sort: τ_{{{', '.join(sort_strs)}}}")

        # Apply LIMIT
        limit = children.get("limit")
        if limit:
            limit_str = self._expr_to_string(limit)
            offset = children.get("offset")
            offset_str = self._expr_to_string(offset) if offset else "0"
            current = {"op": "LIMIT", "symbol": "LIMIT", "count": limit_str, "offset": offset_str, "input": current}
            self.steps.append(f"Apply limit: LIMIT {limit_str} OFFSET {offset_str}")

        return current

    # ── INSERT ──────────────────────────────────────────────────────────────

    def _gen_insert(self, node):
        children = node.get("children", {})
        table = children.get("table", {}).get("name", "?")
        cols = children.get("columns", [])
        values = children.get("values", [])

        value_strs = []
        for row in values:
            row_str = ", ".join(self._expr_to_string(v) for v in row)
            value_strs.append(f"({row_str})")

        ir = {
            "op": "INSERT",
            "symbol": "INSERT",
            "table": table,
            "columns": cols,
            "values": value_strs,
        }
        self.steps.append(f"Insert into '{table}': {len(values)} row(s)")
        return ir

    # ── UPDATE ──────────────────────────────────────────────────────────────

    def _gen_update(self, node):
        children = node.get("children", {})
        table = children.get("table", {}).get("name", "?")

        assignments = []
        for a in children.get("assignments", []):
            assignments.append(f"{a['column']} = {self._expr_to_string(a['value'])}")

        ir = {
            "op": "UPDATE",
            "symbol": "UPDATE",
            "table": table,
            "assignments": assignments,
        }

        where = children.get("where")
        if where:
            cond_str = self._expr_to_string(where)
            ir["condition"] = cond_str
            self.steps.append(f"Update '{table}' WHERE {cond_str}")
        else:
            self.steps.append(f"Update ALL rows in '{table}'")

        return ir

    # ── DELETE ──────────────────────────────────────────────────────────────

    def _gen_delete(self, node):
        children = node.get("children", {})
        table = children.get("table", {}).get("name", "?")

        ir = {"op": "DELETE", "symbol": "DELETE", "table": table}
        where = children.get("where")
        if where:
            cond_str = self._expr_to_string(where)
            ir["condition"] = cond_str
            self.steps.append(f"Delete from '{table}' WHERE {cond_str}")
        else:
            self.steps.append(f"Delete ALL rows from '{table}'")

        return ir

    # ── CREATE / DROP ───────────────────────────────────────────────────────

    def _gen_create(self, node):
        children = node.get("children", {})
        table = children.get("table", {}).get("name", "?")
        columns = children.get("columns", [])

        col_defs = []
        for col in columns:
            s = f"{col['name']} {col.get('data_type', '?')}"
            if col.get("type_params"):
                s += f"({', '.join(col['type_params'])})"
            if col.get("constraints"):
                for c in col["constraints"]:
                    if isinstance(c, str):
                        s += f" {c}"
            col_defs.append(s)

        ir = {
            "op": "CREATE_TABLE",
            "symbol": "CREATE",
            "table": table,
            "columns": col_defs,
        }
        self.steps.append(f"Create table '{table}' with columns: {', '.join(c['name'] for c in columns)}")
        return ir

    def _gen_drop(self, node):
        children = node.get("children", {})
        table = children.get("table", {}).get("name", "?")
        ir = {
            "op": "DROP_TABLE",
            "symbol": "DROP",
            "table": table,
            "if_exists": children.get("if_exists", False),
        }
        self.steps.append(f"Drop table '{table}'")
        return ir

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _table_node(self, tref):
        name = tref.get("name", "?")
        node = {"op": "TABLE_SCAN", "symbol": "R", "table": name}
        if tref.get("alias") and tref["alias"] != name:
            node = {"op": "RENAME", "symbol": "ρ", "alias": tref["alias"], "input": node}
        return node

    def _expr_to_string(self, expr):
        if not isinstance(expr, dict):
            return str(expr)

        t = expr.get("type")
        if t == "Identifier":
            return expr.get("value", "?")
        if t == "QualifiedIdentifier":
            return f"{expr.get('table', '?')}.{expr.get('column', '?')}"
        if t == "NumberLiteral":
            return expr.get("value", "0")
        if t == "StringLiteral":
            return expr.get("value", "''")
        if t == "BooleanLiteral":
            return expr.get("value", "TRUE")
        if t == "NullLiteral":
            return "NULL"
        if t == "Star":
            return "*"
        if t == "BinaryExpression":
            left = self._expr_to_string(expr.get("left"))
            right = self._expr_to_string(expr.get("right"))
            op = expr.get("operator", "?")
            return f"{left} {op} {right}"
        if t == "UnaryExpression":
            op = expr.get("operator", "")
            operand = self._expr_to_string(expr.get("operand"))
            return f"{op} {operand}"
        if t == "FunctionCall":
            name = expr.get("name", "?")
            args = ", ".join(self._expr_to_string(a) for a in expr.get("arguments", []))
            distinct = "DISTINCT " if expr.get("distinct") else ""
            return f"{name}({distinct}{args})"
        if t == "InExpression":
            e = self._expr_to_string(expr.get("expression"))
            neg = "NOT " if expr.get("negated") else ""
            vals = expr.get("values", [])
            if isinstance(vals, list):
                v = ", ".join(self._expr_to_string(v) for v in vals)
                return f"{e} {neg}IN ({v})"
            return f"{e} {neg}IN (subquery)"
        if t == "BetweenExpression":
            e = self._expr_to_string(expr.get("expression"))
            lo = self._expr_to_string(expr.get("low"))
            hi = self._expr_to_string(expr.get("high"))
            neg = "NOT " if expr.get("negated") else ""
            return f"{e} {neg}BETWEEN {lo} AND {hi}"
        if t == "LikeExpression":
            e = self._expr_to_string(expr.get("expression"))
            p = self._expr_to_string(expr.get("pattern"))
            neg = "NOT " if expr.get("negated") else ""
            return f"{e} {neg}LIKE {p}"
        if t == "IsExpression":
            e = self._expr_to_string(expr.get("expression"))
            neg = " NOT" if expr.get("negated") else ""
            return f"{e} IS{neg} NULL"
        if t == "Grouped":
            return f"({self._expr_to_string(expr.get('expression'))})"
        if t == "AliasedExpression":
            return self._expr_to_string(expr.get("expression"))
        if t == "CaseExpression":
            return "CASE..."
        if t == "CastExpression":
            return f"CAST({self._expr_to_string(expr.get('expression'))} AS {expr.get('cast_type', '?')})"
        if t == "ExistsExpression":
            return "EXISTS(subquery)"
        if t == "QualifiedStar":
            return f"{expr.get('table', '?')}.*"

        return str(expr)

    def _columns_to_strings(self, columns):
        result = []
        for col in columns:
            if isinstance(col, dict):
                if col.get("type") == "AliasedExpression":
                    expr_str = self._expr_to_string(col.get("expression"))
                    alias = col.get("alias", "")
                    result.append(f"{expr_str} AS {alias}" if alias else expr_str)
                else:
                    result.append(self._expr_to_string(col))
            else:
                result.append(str(col))
        return result

    def _extract_aggregates(self, columns):
        aggs = []
        for col in columns:
            self._find_aggregates(col, aggs)
        return aggs

    def _find_aggregates(self, node, aggs):
        if not isinstance(node, dict):
            return
        if node.get("type") == "FunctionCall" and node.get("name", "").upper() in (
            "COUNT", "SUM", "AVG", "MIN", "MAX"
        ):
            aggs.append(self._expr_to_string(node))
        for key, val in node.items():
            if isinstance(val, dict):
                self._find_aggregates(val, aggs)
            elif isinstance(val, list):
                for item in val:
                    self._find_aggregates(item, aggs)

    def _to_string(self, ir, indent=0):
        """Convert IR tree to a human-readable string."""
        if not isinstance(ir, dict):
            return str(ir)

        op = ir.get("op", "?")
        prefix = "  " * indent

        if op == "TABLE_SCAN":
            return f"{ir.get('table', '?')}"

        if op == "RENAME":
            inner = self._to_string(ir.get("input", {}), indent)
            return f"ρ_{{{ir.get('alias', '?')}}}({inner})"

        if op == "SELECTION":
            inner = self._to_string(ir.get("input", {}), indent)
            note = f" [{ir['note']}]" if ir.get("note") else ""
            return f"σ_{{{ir.get('condition', '?')}}}{note}({inner})"

        if op == "PROJECTION":
            inner = self._to_string(ir.get("input", {}), indent)
            return f"π_{{{ir.get('columns', '*')}}}({inner})"

        if op == "JOIN":
            left = self._to_string(ir.get("left", {}), indent)
            right = self._to_string(ir.get("right", {}), indent)
            return f"({left}) {ir.get('symbol', '⋈')}_{{{ir.get('condition', '')}}} ({right})"

        if op == "CROSS_PRODUCT":
            left = self._to_string(ir.get("left", {}), indent)
            right = self._to_string(ir.get("right", {}), indent)
            return f"({left}) × ({right})"

        if op == "GROUPING":
            inner = self._to_string(ir.get("input", {}), indent)
            agg = f" [{ir['aggregates']}]" if ir.get("aggregates") else ""
            return f"γ_{{{ir.get('group_by', '?')}}}{agg}({inner})"

        if op == "SORT":
            inner = self._to_string(ir.get("input", {}), indent)
            return f"τ_{{{ir.get('order', '?')}}}({inner})"

        if op == "DISTINCT":
            inner = self._to_string(ir.get("input", {}), indent)
            return f"δ({inner})"

        if op == "LIMIT":
            inner = self._to_string(ir.get("input", {}), indent)
            return f"LIMIT_{{{ir.get('count', '?')}}}({inner})"

        if op == "INSERT":
            return f"INSERT INTO {ir.get('table', '?')} VALUES {', '.join(ir.get('values', []))}"

        if op == "UPDATE":
            cond = f" WHERE {ir['condition']}" if ir.get("condition") else ""
            assigns = ", ".join(ir.get("assignments", []))
            return f"UPDATE {ir.get('table', '?')} SET {assigns}{cond}"

        if op == "DELETE":
            cond = f" WHERE {ir['condition']}" if ir.get("condition") else ""
            return f"DELETE FROM {ir.get('table', '?')}{cond}"

        if op == "CREATE_TABLE":
            cols = ", ".join(ir.get("columns", []))
            return f"CREATE TABLE {ir.get('table', '?')} ({cols})"

        if op == "DROP_TABLE":
            ie = " IF EXISTS" if ir.get("if_exists") else ""
            return f"DROP TABLE{ie} {ir.get('table', '?')}"

        return str(ir)


# ── Public API ──────────────────────────────────────────────────────────────

def generate(ast: dict) -> dict:
    """Generate intermediate relational algebra representation from an AST."""
    gen = ICGenerator()
    return gen.generate(ast)
