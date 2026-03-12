"""
Flask application — REST API for the SQL Compiler Pipeline.

Endpoints:
  POST /api/compile   — Compile SQL through all pipeline stages
  GET  /api/schema    — Return the mock database schema
  GET  /api/examples  — Return example SQL queries
"""

import time
import traceback
from flask import Flask, request, jsonify
from flask_cors import CORS

from compiler.lexer import tokenize
from compiler.parser import parse
from compiler.semantic import analyze, get_schema
from compiler.icg import generate
from compiler.optimizer import optimize
from compiler.errors import CompilerError

app = Flask(__name__)
CORS(app)


# ── Example queries ─────────────────────────────────────────────────────────

EXAMPLE_QUERIES = [
    {
        "name": "Simple SELECT",
        "description": "Select specific columns from the users table",
        "sql": "SELECT username, email, age\nFROM users\nWHERE age > 25\nORDER BY age DESC;"
    },
    {
        "name": "JOIN Query",
        "description": "Join users with their orders",
        "sql": "SELECT u.username, o.total_price, p.name AS product_name\nFROM users u\nINNER JOIN orders o ON u.id = o.user_id\nINNER JOIN products p ON o.product_id = p.id\nWHERE o.total_price > 100\nORDER BY o.total_price DESC;"
    },
    {
        "name": "Aggregation with GROUP BY",
        "description": "Count orders and total revenue per user",
        "sql": "SELECT u.username, COUNT(o.id) AS order_count, SUM(o.total_price) AS total_spent\nFROM users u\nLEFT JOIN orders o ON u.id = o.user_id\nGROUP BY u.username\nHAVING SUM(o.total_price) > 500\nORDER BY total_spent DESC;"
    },
    {
        "name": "Subquery with IN",
        "description": "Find users who have ordered expensive products",
        "sql": "SELECT username, email\nFROM users\nWHERE id IN (\n  SELECT user_id\n  FROM orders\n  WHERE total_price > 200\n)\nORDER BY username;"
    },
    {
        "name": "INSERT Statement",
        "description": "Insert a new product into the products table",
        "sql": "INSERT INTO products (name, category, price, stock)\nVALUES ('Mechanical Keyboard', 'Electronics', 89.99, 150);"
    },
    {
        "name": "UPDATE Statement",
        "description": "Update employee salaries in a department",
        "sql": "UPDATE employees\nSET salary = salary * 1.10\nWHERE department_id = 3\n  AND hire_date < '2024-01-01';"
    },
    {
        "name": "DELETE Statement",
        "description": "Delete inactive users",
        "sql": "DELETE FROM users\nWHERE is_active = FALSE\n  AND created_at < '2023-01-01';"
    },
    {
        "name": "CREATE TABLE",
        "description": "Create a new reviews table",
        "sql": "CREATE TABLE reviews (\n  id INT PRIMARY KEY AUTO_INCREMENT,\n  user_id INT NOT NULL,\n  product_id INT NOT NULL,\n  rating INT NOT NULL,\n  comment TEXT,\n  created_at DATE DEFAULT '2025-01-01'\n);"
    },
    {
        "name": "Complex Analytics Query",
        "description": "Product category analytics with multiple aggregates",
        "sql": "SELECT p.category,\n       COUNT(DISTINCT o.user_id) AS unique_customers,\n       COUNT(o.id) AS total_orders,\n       AVG(o.total_price) AS avg_order_value,\n       MAX(o.total_price) AS max_order\nFROM products p\nINNER JOIN orders o ON p.id = o.product_id\nGROUP BY p.category\nHAVING COUNT(o.id) > 10\nORDER BY total_orders DESC\nLIMIT 10;"
    },
    {
        "name": "BETWEEN and LIKE",
        "description": "Search users with pattern matching and range filters",
        "sql": "SELECT username, email, salary\nFROM users\nWHERE salary BETWEEN 50000 AND 120000\n  AND email LIKE '%@gmail.com'\n  AND department IS NOT NULL\nORDER BY salary DESC;"
    },
]


# ── API Endpoints ───────────────────────────────────────────────────────────

@app.route("/api/compile", methods=["POST"])
def compile_sql():
    """Run SQL through the full compilation pipeline."""
    data = request.get_json()
    if not data or "sql" not in data:
        return jsonify({"success": False, "error": "Missing 'sql' field in request body"}), 400

    sql = data["sql"].strip()
    if not sql:
        return jsonify({"success": False, "error": "Empty SQL input"}), 400

    stages = {}
    errors = []
    total_start = time.perf_counter()

    # ── Stage 1: Lexer ──────────────────────────────────────────────────
    try:
        t0 = time.perf_counter()
        tokens = tokenize(sql)
        t1 = time.perf_counter()
        stages["lexer"] = {
            "tokens": tokens,
            "token_count": len(tokens),
            "time_ms": round((t1 - t0) * 1000, 2),
            "status": "success",
        }
    except CompilerError as e:
        stages["lexer"] = {"status": "error", "error": e.to_dict()}
        errors.append(e.to_dict())
        return jsonify({
            "success": False,
            "stages": stages,
            "errors": errors,
            "total_time_ms": round((time.perf_counter() - total_start) * 1000, 2),
        })

    # ── Stage 2: Parser ─────────────────────────────────────────────────
    try:
        t0 = time.perf_counter()
        ast = parse(tokens)
        t1 = time.perf_counter()
        stages["parser"] = {
            "ast": ast,
            "time_ms": round((t1 - t0) * 1000, 2),
            "status": "success",
        }
    except CompilerError as e:
        stages["parser"] = {"status": "error", "error": e.to_dict()}
        errors.append(e.to_dict())
        return jsonify({
            "success": False,
            "stages": stages,
            "errors": errors,
            "total_time_ms": round((time.perf_counter() - total_start) * 1000, 2),
        })

    # ── Stage 3: Semantic Analysis ──────────────────────────────────────
    try:
        t0 = time.perf_counter()
        sem_result = analyze(ast)
        t1 = time.perf_counter()
        stages["semantic"] = {
            **sem_result,
            "time_ms": round((t1 - t0) * 1000, 2),
            "status": "error" if sem_result["errors"] else "success",
        }
        if sem_result["errors"]:
            errors.extend(sem_result["errors"])
    except CompilerError as e:
        stages["semantic"] = {"status": "error", "error": e.to_dict()}
        errors.append(e.to_dict())

    # ── Stage 4: ICG ────────────────────────────────────────────────────
    try:
        t0 = time.perf_counter()
        icg_result = generate(ast)
        t1 = time.perf_counter()
        stages["icg"] = {
            **icg_result,
            "time_ms": round((t1 - t0) * 1000, 2),
            "status": "success",
        }
    except Exception as e:
        stages["icg"] = {
            "status": "error",
            "error": {"message": str(e), "stage": "icg", "severity": "error"},
        }

    # ── Stage 5: Optimizer ──────────────────────────────────────────────
    try:
        t0 = time.perf_counter()
        ir_tree = icg_result.get("ir_tree", {})
        opt_result = optimize(ir_tree)
        t1 = time.perf_counter()
        stages["optimizer"] = {
            **opt_result,
            "time_ms": round((t1 - t0) * 1000, 2),
            "status": "success",
        }
    except Exception as e:
        stages["optimizer"] = {
            "status": "error",
            "error": {"message": str(e), "stage": "optimizer", "severity": "error"},
        }

    total_time = round((time.perf_counter() - total_start) * 1000, 2)

    return jsonify({
        "success": len(errors) == 0,
        "stages": stages,
        "errors": errors,
        "total_time_ms": total_time,
    })


@app.route("/api/schema", methods=["GET"])
def schema():
    """Return the mock database schema."""
    return jsonify(get_schema())


@app.route("/api/examples", methods=["GET"])
def examples():
    """Return example SQL queries."""
    return jsonify(EXAMPLE_QUERIES)


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
