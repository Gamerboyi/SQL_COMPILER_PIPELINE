"""
SQL Semantic Analyzer — Validates the AST against a mock database schema.

Performs:
  - Table existence checks
  - Column existence / ambiguity checks
  - Type compatibility in comparisons
  - Aggregate function validation (GROUP BY requirements)
  - Alias resolution

Uses a built-in mock schema so the visualizer works without a real database.
"""

from .errors import SemanticError, SemanticWarning


# ── Mock Database Schema ────────────────────────────────────────────────────

MOCK_SCHEMA = {
    "users": {
        "columns": {
            "id":         {"type": "INT",     "nullable": False, "primary_key": True},
            "username":   {"type": "VARCHAR", "nullable": False},
            "email":      {"type": "VARCHAR", "nullable": False},
            "age":        {"type": "INT",     "nullable": True},
            "salary":     {"type": "DECIMAL", "nullable": True},
            "department": {"type": "VARCHAR", "nullable": True},
            "is_active":  {"type": "BOOLEAN", "nullable": False},
            "created_at": {"type": "DATE",    "nullable": False},
        },
        "row_count": 10000,
    },
    "orders": {
        "columns": {
            "id":          {"type": "INT",     "nullable": False, "primary_key": True},
            "user_id":     {"type": "INT",     "nullable": False},
            "product_id":  {"type": "INT",     "nullable": False},
            "quantity":    {"type": "INT",     "nullable": False},
            "total_price": {"type": "DECIMAL", "nullable": False},
            "status":      {"type": "VARCHAR", "nullable": False},
            "order_date":  {"type": "DATE",    "nullable": False},
        },
        "row_count": 50000,
    },
    "products": {
        "columns": {
            "id":          {"type": "INT",     "nullable": False, "primary_key": True},
            "name":        {"type": "VARCHAR", "nullable": False},
            "category":    {"type": "VARCHAR", "nullable": True},
            "price":       {"type": "DECIMAL", "nullable": False},
            "stock":       {"type": "INT",     "nullable": False},
            "description": {"type": "TEXT",    "nullable": True},
        },
        "row_count": 500,
    },
    "departments": {
        "columns": {
            "id":       {"type": "INT",     "nullable": False, "primary_key": True},
            "name":     {"type": "VARCHAR", "nullable": False},
            "budget":   {"type": "DECIMAL", "nullable": True},
            "location": {"type": "VARCHAR", "nullable": True},
        },
        "row_count": 20,
    },
    "employees": {
        "columns": {
            "id":            {"type": "INT",     "nullable": False, "primary_key": True},
            "name":          {"type": "VARCHAR", "nullable": False},
            "department_id": {"type": "INT",     "nullable": True},
            "manager_id":    {"type": "INT",     "nullable": True},
            "hire_date":     {"type": "DATE",    "nullable": False},
            "salary":        {"type": "DECIMAL", "nullable": False},
            "position":      {"type": "VARCHAR", "nullable": True},
        },
        "row_count": 200,
    },
}

# Types compatibility groups
NUMERIC_TYPES = {"INT", "INTEGER", "BIGINT", "SMALLINT", "TINYINT", "FLOAT", "DOUBLE", "DECIMAL", "NUMERIC", "REAL"}
STRING_TYPES  = {"VARCHAR", "CHAR", "TEXT", "BLOB", "CLOB"}
DATE_TYPES    = {"DATE", "TIME", "DATETIME", "TIMESTAMP"}
BOOL_TYPES    = {"BOOLEAN", "BOOL"}

AGGREGATE_FUNCTIONS = {"COUNT", "SUM", "AVG", "MIN", "MAX"}


class SemanticAnalyzer:
    """Analyze an AST for semantic correctness."""

    def __init__(self, schema=None):
        self.schema = schema or MOCK_SCHEMA
        self.errors = []
        self.warnings = []
        self.table_aliases = {}      # alias -> real table name
        self.tables_in_scope = {}    # name/alias -> schema entry
        self.has_aggregates = False
        self.has_non_aggregates = False
        self.group_by_exprs = []
        self.annotations = []        # metadata for the frontend

    def analyze(self, ast: dict) -> dict:
        """
        Analyze the AST and return:
          - annotated_ast: the original AST with type annotations
          - errors: list of error dicts
          - warnings: list of warning dicts
          - schema_used: list of tables/columns referenced
          - annotations: additional metadata
        """
        self._analyze_node(ast)

        return {
            "annotated_ast": ast,
            "errors": [e.to_dict() for e in self.errors],
            "warnings": [w.to_dict() for w in self.warnings],
            "tables_referenced": list(self.tables_in_scope.keys()),
            "schema_info": {
                name: {
                    "columns": list(info["columns"].keys()),
                    "row_count": info["row_count"],
                }
                for name, info in self.tables_in_scope.items()
            },
            "annotations": self.annotations,
        }

    def _analyze_node(self, node):
        if not isinstance(node, dict) or "type" not in node:
            return

        handler = {
            "SelectStatement":     self._analyze_select,
            "InsertStatement":     self._analyze_insert,
            "UpdateStatement":     self._analyze_update,
            "DeleteStatement":     self._analyze_delete,
            "CreateTableStatement": self._analyze_create_table,
            "DropTableStatement":  self._analyze_drop_table,
        }.get(node["type"])

        if handler:
            handler(node)

    # ── SELECT ──────────────────────────────────────────────────────────────

    def _analyze_select(self, node):
        children = node.get("children", {})

        # 1. Resolve FROM tables
        from_tables = children.get("from", [])
        for tref in from_tables:
            self._register_table(tref)

        # 2. Resolve JOIN tables
        for join in children.get("joins", []):
            self._register_table(join.get("table", {}))
            if join.get("condition"):
                self._check_expression(join["condition"])

        # 3. Validate columns in SELECT list
        columns = children.get("columns", [])
        for col in columns:
            self._check_select_item(col)

        # 4. Validate WHERE
        where = children.get("where")
        if where:
            self._check_expression(where)

        # 5. GROUP BY
        group_by = children.get("group_by", [])
        if group_by:
            self.group_by_exprs = group_by
            for expr in group_by:
                self._check_expression(expr)

        # 6. HAVING
        having = children.get("having")
        if having:
            self._check_expression(having)

        # 7. ORDER BY
        order_by = children.get("order_by", [])
        for item in order_by:
            self._check_expression(item.get("expression", {}))

        # 8. Aggregate validation
        if self.has_aggregates and self.has_non_aggregates and not group_by:
            self.errors.append(SemanticError(
                "SELECT mixes aggregate and non-aggregate columns without GROUP BY"
            ))
            self.annotations.append({
                "type": "aggregate_warning",
                "message": "When using aggregate functions (COUNT, SUM, etc.), "
                           "non-aggregated columns must appear in GROUP BY",
            })

    def _check_select_item(self, item):
        if isinstance(item, dict):
            if item.get("type") == "Star":
                self.has_non_aggregates = True
                self.annotations.append({
                    "type": "star_expansion",
                    "message": f"* expands to all columns from: {', '.join(self.tables_in_scope.keys())}",
                })
                return
            if item.get("type") == "AliasedExpression":
                self._check_expression(item.get("expression", {}))
                return
            self._check_expression(item)

    # ── INSERT ──────────────────────────────────────────────────────────────

    def _analyze_insert(self, node):
        children = node.get("children", {})
        table = children.get("table", {})
        self._register_table(table)

        table_name = table.get("name", "").lower()
        schema_entry = self.schema.get(table_name)
        if not schema_entry:
            return

        # Validate column names
        cols = children.get("columns", [])
        for col in cols:
            if col.lower() not in {c.lower() for c in schema_entry["columns"]}:
                self.errors.append(SemanticError(
                    f"Column '{col}' does not exist in table '{table_name}'"
                ))

        # Validate value count matches column count
        values = children.get("values", [])
        expected = len(cols) if cols else len(schema_entry["columns"])
        for i, row in enumerate(values):
            if len(row) != expected:
                self.errors.append(SemanticError(
                    f"Row {i+1}: expected {expected} values, got {len(row)}"
                ))

    # ── UPDATE ──────────────────────────────────────────────────────────────

    def _analyze_update(self, node):
        children = node.get("children", {})
        table = children.get("table", {})
        self._register_table(table)

        table_name = table.get("name", "").lower()
        schema_entry = self.schema.get(table_name)
        if not schema_entry:
            return

        for assignment in children.get("assignments", []):
            col = assignment.get("column", "")
            if col.lower() not in {c.lower() for c in schema_entry["columns"]}:
                self.errors.append(SemanticError(
                    f"Column '{col}' does not exist in table '{table_name}'"
                ))
            self._check_expression(assignment.get("value", {}))

        where = children.get("where")
        if where:
            self._check_expression(where)
        else:
            self.warnings.append(SemanticWarning(
                "UPDATE without WHERE clause will modify ALL rows"
            ))

    # ── DELETE ──────────────────────────────────────────────────────────────

    def _analyze_delete(self, node):
        children = node.get("children", {})
        table = children.get("table", {})
        self._register_table(table)

        where = children.get("where")
        if where:
            self._check_expression(where)
        else:
            self.warnings.append(SemanticWarning(
                "DELETE without WHERE clause will delete ALL rows"
            ))

    # ── CREATE TABLE ────────────────────────────────────────────────────────

    def _analyze_create_table(self, node):
        children = node.get("children", {})
        table = children.get("table", {})
        table_name = table.get("name", "").lower()

        if table_name in self.schema:
            self.warnings.append(SemanticWarning(
                f"Table '{table_name}' already exists in schema"
            ))

        # Validate column definitions
        columns = children.get("columns", [])
        col_names = set()
        for col_def in columns:
            name = col_def.get("name", "")
            if name.lower() in col_names:
                self.errors.append(SemanticError(
                    f"Duplicate column name '{name}'"
                ))
            col_names.add(name.lower())

        self.annotations.append({
            "type": "ddl_info",
            "message": f"CREATE TABLE will create table '{table_name}' with {len(columns)} columns",
        })

    # ── DROP TABLE ──────────────────────────────────────────────────────────

    def _analyze_drop_table(self, node):
        children = node.get("children", {})
        table = children.get("table", {})
        table_name = table.get("name", "").lower()

        if table_name not in self.schema and not children.get("if_exists"):
            self.errors.append(SemanticError(
                f"Table '{table_name}' does not exist"
            ))

        self.annotations.append({
            "type": "ddl_warning",
            "message": f"DROP TABLE will permanently remove table '{table_name}' and all its data",
        })

    # ── Expression checking ─────────────────────────────────────────────────

    def _check_expression(self, expr):
        if not isinstance(expr, dict):
            return None

        t = expr.get("type")

        if t == "Identifier":
            self.has_non_aggregates = True
            return self._resolve_column(expr.get("value", ""))

        if t == "QualifiedIdentifier":
            self.has_non_aggregates = True
            return self._resolve_qualified_column(
                expr.get("table", ""), expr.get("column", "")
            )

        if t == "NumberLiteral":
            return "NUMERIC"

        if t == "StringLiteral":
            return "STRING"

        if t == "BooleanLiteral":
            return "BOOLEAN"

        if t == "NullLiteral":
            return "NULL"

        if t == "FunctionCall":
            name = expr.get("name", "").upper()
            if name in AGGREGATE_FUNCTIONS:
                self.has_aggregates = True
                self.annotations.append({
                    "type": "aggregate",
                    "message": f"{name}() is an aggregate function",
                    "function": name,
                })
            for arg in expr.get("arguments", []):
                self._check_expression(arg)
            if name in ("COUNT",):
                return "NUMERIC"
            if name in ("SUM", "AVG"):
                return "NUMERIC"
            if name in ("MIN", "MAX"):
                return "ANY"
            if name in ("UPPER", "LOWER", "TRIM", "CONCAT", "SUBSTRING"):
                return "STRING"
            return "ANY"

        if t == "BinaryExpression":
            left_type = self._check_expression(expr.get("left"))
            right_type = self._check_expression(expr.get("right"))
            op = expr.get("operator", "")

            # Type compatibility check
            if left_type and right_type and left_type != "ANY" and right_type != "ANY":
                if left_type == "NULL" or right_type == "NULL":
                    pass  # NULL is compatible with anything
                elif self._type_group(left_type) != self._type_group(right_type):
                    self.warnings.append(SemanticWarning(
                        f"Type mismatch in '{op}': {left_type} vs {right_type}"
                    ))

            if op in ("=", "!=", "<>", "<", ">", "<=", ">=", "AND", "OR"):
                return "BOOLEAN"
            return left_type or right_type

        if t == "UnaryExpression":
            return self._check_expression(expr.get("operand"))

        if t == "InExpression":
            self._check_expression(expr.get("expression"))
            values = expr.get("values")
            if isinstance(values, list):
                for v in values:
                    self._check_expression(v)
            return "BOOLEAN"

        if t == "BetweenExpression":
            self._check_expression(expr.get("expression"))
            self._check_expression(expr.get("low"))
            self._check_expression(expr.get("high"))
            return "BOOLEAN"

        if t == "LikeExpression":
            self._check_expression(expr.get("expression"))
            self._check_expression(expr.get("pattern"))
            return "BOOLEAN"

        if t == "IsExpression":
            self._check_expression(expr.get("expression"))
            return "BOOLEAN"

        if t in ("Grouped", "AliasedExpression"):
            return self._check_expression(expr.get("expression"))

        if t == "Star":
            self.has_non_aggregates = True
            return "ANY"

        if t == "Subquery":
            return "ANY"

        return None

    # ── Resolution helpers ──────────────────────────────────────────────────

    def _register_table(self, tref):
        if not isinstance(tref, dict):
            return
        name = tref.get("name", "").lower()
        alias = tref.get("alias", "").lower() if tref.get("alias") else name

        if name in self.schema:
            self.tables_in_scope[alias] = self.schema[name]
            if alias != name:
                self.table_aliases[alias] = name
            self.annotations.append({
                "type": "table_resolved",
                "table": name,
                "alias": alias if alias != name else None,
                "row_count": self.schema[name]["row_count"],
                "columns": list(self.schema[name]["columns"].keys()),
            })
        else:
            if tref.get("type") != "Subquery":
                self.errors.append(SemanticError(
                    f"Table '{name}' does not exist in schema"
                ))

    def _resolve_column(self, col_name):
        """Find which table a bare column belongs to."""
        found_in = []
        for tname, tschema in self.tables_in_scope.items():
            if col_name.lower() in {c.lower() for c in tschema["columns"]}:
                found_in.append(tname)

        if not found_in:
            if self.tables_in_scope:  # Only error if we have tables
                self.errors.append(SemanticError(
                    f"Column '{col_name}' not found in any table in scope"
                ))
            return None

        if len(found_in) > 1:
            self.warnings.append(SemanticWarning(
                f"Column '{col_name}' is ambiguous — found in: {', '.join(found_in)}"
            ))

        # Return the type of the column
        table_schema = self.tables_in_scope[found_in[0]]
        for cname, cinfo in table_schema["columns"].items():
            if cname.lower() == col_name.lower():
                return cinfo["type"]
        return None

    def _resolve_qualified_column(self, table, column):
        """Resolve table.column."""
        table_lower = table.lower()
        real_table = self.table_aliases.get(table_lower, table_lower)

        if table_lower not in self.tables_in_scope and real_table not in self.tables_in_scope:
            self.errors.append(SemanticError(
                f"Table or alias '{table}' not in scope"
            ))
            return None

        schema_entry = self.tables_in_scope.get(table_lower) or self.tables_in_scope.get(real_table)
        if schema_entry:
            if column.lower() not in {c.lower() for c in schema_entry["columns"]}:
                self.errors.append(SemanticError(
                    f"Column '{column}' does not exist in table '{table}'"
                ))
                return None
            for cname, cinfo in schema_entry["columns"].items():
                if cname.lower() == column.lower():
                    return cinfo["type"]
        return None

    @staticmethod
    def _type_group(type_str):
        if type_str in NUMERIC_TYPES or type_str == "NUMERIC":
            return "NUMERIC"
        if type_str in STRING_TYPES or type_str == "STRING":
            return "STRING"
        if type_str in DATE_TYPES:
            return "DATE"
        if type_str in BOOL_TYPES or type_str == "BOOLEAN":
            return "BOOLEAN"
        return type_str


# ── Public API ──────────────────────────────────────────────────────────────

def analyze(ast: dict, schema=None) -> dict:
    """Perform semantic analysis on an AST. Returns analysis results."""
    analyzer = SemanticAnalyzer(schema)
    return analyzer.analyze(ast)


def get_schema() -> dict:
    """Return the mock schema for frontend display."""
    result = {}
    for table_name, table_info in MOCK_SCHEMA.items():
        result[table_name] = {
            "columns": {
                col_name: col_info["type"]
                for col_name, col_info in table_info["columns"].items()
            },
            "row_count": table_info["row_count"],
        }
    return result
