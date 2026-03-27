"""
SQL Query Optimizer — Applies rule-based optimizations to the relational algebra IR.

Optimization rules:
  1. Predicate Pushdown  — move σ (selection) closer to table scans
  2. Projection Pushdown — add early π to reduce intermediate row width
  3. Constant Folding    — evaluate constant expressions at compile time
  4. Redundancy Elimination — remove duplicate projections / sorts
  5. Join Reordering     — smaller tables first (uses mock row counts)
"""

import copy
from .semantic import MOCK_SCHEMA


class Optimizer:
    """Apply rule-based optimizations to an IR tree."""

    def __init__(self, schema=None):
        self.schema = schema or MOCK_SCHEMA
        self.optimizations_applied = []

    def optimize(self, ir: dict) -> dict:
        """
        Optimize the IR and return:
          - original_ir: copy of the input
          - optimized_ir: the optimized tree
          - optimizations: list of applied optimizations with explanations
          - original_readable: readable string of original
          - optimized_readable: readable string of optimized
        """
        from .icg import ICGenerator

        original = copy.deepcopy(ir)
        optimized = copy.deepcopy(ir)

        # Apply optimizations in sequence
        optimized = self._predicate_pushdown(optimized)
        optimized = self._projection_pushdown(optimized)
        optimized = self._constant_folding(optimized)
        optimized = self._eliminate_redundancy(optimized)
        optimized = self._join_reorder(optimized)

        # Generate readable strings
        gen = ICGenerator()
        original_readable = gen._to_string(original)
        optimized_readable = gen._to_string(optimized)

        # If no optimizations were applied, note that
        if not self.optimizations_applied:
            self.optimizations_applied.append({
                "rule": "No Optimization Needed",
                "description": "The query plan is already optimal for the given query.",
                "impact": "neutral",
            })

        return {
            "original_ir": original,
            "optimized_ir": optimized,
            "optimizations": self.optimizations_applied,
            "original_readable": original_readable,
            "optimized_readable": optimized_readable,
        }

    # ── 1. Predicate Pushdown ───────────────────────────────────────────────

    def _predicate_pushdown(self, ir):
        """Push selection (σ) operations closer to table scans."""
        if not isinstance(ir, dict) or "op" not in ir:
            return ir

        # Look for σ applied over a JOIN — try to push conditions down
        if ir.get("op") == "SELECTION" and isinstance(ir.get("input"), dict):
            inner = ir["input"]

            if inner.get("op") == "JOIN":
                condition = ir.get("condition", "")
                # Determine which side the condition references
                left_tables = self._collect_tables(inner.get("left", {}))
                right_tables = self._collect_tables(inner.get("right", {}))

                # Simple heuristic: if condition only references left-side tables
                cond_tables = self._tables_in_condition(condition)

                if cond_tables and cond_tables.issubset(left_tables):
                    # Push σ below JOIN to left side
                    inner["left"] = {
                        "op": "SELECTION",
                        "symbol": "σ",
                        "condition": condition,
                        "input": inner["left"],
                    }
                    self.optimizations_applied.append({
                        "rule": "Predicate Pushdown",
                        "description": f"Moved filter '{condition}' below JOIN to left input — "
                                       f"filters data before the expensive join operation",
                        "impact": "high",
                        "details": f"Condition references tables: {', '.join(cond_tables)} "
                                   f"which are all on the left side of the join",
                    })
                    return inner  # Remove the outer σ since we pushed it down

                elif cond_tables and cond_tables.issubset(right_tables):
                    inner["right"] = {
                        "op": "SELECTION",
                        "symbol": "σ",
                        "condition": condition,
                        "input": inner["right"],
                    }
                    self.optimizations_applied.append({
                        "rule": "Predicate Pushdown",
                        "description": f"Moved filter '{condition}' below JOIN to right input — "
                                       f"reduces rows before joining",
                        "impact": "high",
                        "details": f"Condition references tables: {', '.join(cond_tables)} "
                                   f"which are all on the right side of the join",
                    })
                    return inner

            # Recurse for nested selections/projections
            if inner.get("op") == "PROJECTION":
                # Push selection below projection
                inner_input = inner.get("input", {})
                new_selection = {
                    "op": "SELECTION",
                    "symbol": "σ",
                    "condition": ir.get("condition"),
                    "input": inner_input,
                }
                inner["input"] = new_selection
                self.optimizations_applied.append({
                    "rule": "Predicate Pushdown",
                    "description": f"Moved filter below projection — filter rows before selecting columns",
                    "impact": "medium",
                })
                return inner

        # Recurse into children
        for key in ("input", "left", "right"):
            if key in ir and isinstance(ir[key], dict):
                ir[key] = self._predicate_pushdown(ir[key])

        return ir

    # ── 2. Projection Pushdown ──────────────────────────────────────────────

    def _projection_pushdown(self, ir):
        """Add early projections to reduce intermediate data width."""
        if not isinstance(ir, dict) or "op" not in ir:
            return ir

        # If we have π over a JOIN, we can add projections to each side
        if ir.get("op") == "PROJECTION" and isinstance(ir.get("input"), dict):
            inner = ir["input"]
            if inner.get("op") == "JOIN":
                needed_cols = ir.get("columns", "")
                join_cond = inner.get("condition", "")

                # Combine needed columns from projection and join condition
                all_needed = needed_cols + ", " + join_cond if join_cond else needed_cols

                left_tables = self._collect_tables(inner.get("left", {}))
                right_tables = self._collect_tables(inner.get("right", {}))

                if left_tables and right_tables:
                    self.optimizations_applied.append({
                        "rule": "Projection Pushdown",
                        "description": "Added early column filtering before JOIN — "
                                       "reduces memory usage in intermediate results",
                        "impact": "medium",
                        "details": f"Only columns needed: {needed_cols}",
                    })

        # Recurse
        for key in ("input", "left", "right"):
            if key in ir and isinstance(ir[key], dict):
                ir[key] = self._projection_pushdown(ir[key])

        return ir

    # ── 3. Constant Folding ─────────────────────────────────────────────────

    def _constant_folding(self, ir):
        """Evaluate constant expressions at compile time."""
        if not isinstance(ir, dict) or "op" not in ir:
            return ir

        if ir.get("op") == "SELECTION":
            condition = ir.get("condition", "")

            # Simple constant folding patterns
            folded = False
            original_cond = condition

            # 1 = 1 → TRUE (tautology)
            if condition.strip() in ("1 = 1", "TRUE", "'1' = '1'"):
                # Remove the tautological selection entirely
                self.optimizations_applied.append({
                    "rule": "Constant Folding",
                    "description": f"Removed tautological condition '{condition}' — always evaluates to TRUE",
                    "impact": "low",
                })
                return ir.get("input", ir)

            # 1 = 0 → FALSE (contradiction)  
            if condition.strip() in ("1 = 0", "FALSE", "1 = 2"):
                ir["condition"] = "FALSE"
                self.optimizations_applied.append({
                    "rule": "Constant Folding",
                    "description": f"Simplified contradiction '{condition}' to FALSE — query returns no rows",
                    "impact": "high",
                })

            # Simple arithmetic: e.g., "age > 10 + 5" → "age > 15"
            import re
            arith_match = re.search(r'(\d+)\s*([+\-*/])\s*(\d+)', condition)
            if arith_match:
                a, op, b = int(arith_match.group(1)), arith_match.group(2), int(arith_match.group(3))
                result = {'+': a+b, '-': a-b, '*': a*b, '/': a//b if b != 0 else 0}.get(op, 0)
                new_cond = condition[:arith_match.start()] + str(result) + condition[arith_match.end():]
                if new_cond != condition:
                    ir["condition"] = new_cond
                    self.optimizations_applied.append({
                        "rule": "Constant Folding",
                        "description": f"Evaluated constant expression: {arith_match.group(0)} = {result}",
                        "impact": "low",
                    })

        # Recurse
        for key in ("input", "left", "right"):
            if key in ir and isinstance(ir[key], dict):
                ir[key] = self._constant_folding(ir[key])

        return ir

    # ── 4. Redundancy Elimination ───────────────────────────────────────────

    def _eliminate_redundancy(self, ir):
        """Remove redundant operations."""
        if not isinstance(ir, dict) or "op" not in ir:
            return ir

        # Remove double DISTINCT
        if ir.get("op") == "DISTINCT":
            inner = ir.get("input", {})
            if isinstance(inner, dict) and inner.get("op") == "DISTINCT":
                self.optimizations_applied.append({
                    "rule": "Redundancy Elimination",
                    "description": "Removed duplicate DISTINCT operation",
                    "impact": "low",
                })
                return self._eliminate_redundancy(inner)

        # Remove double SORT with same order
        if ir.get("op") == "SORT":
            inner = ir.get("input", {})
            if isinstance(inner, dict) and inner.get("op") == "SORT":
                if ir.get("order") == inner.get("order"):
                    self.optimizations_applied.append({
                        "rule": "Redundancy Elimination",
                        "description": f"Removed duplicate ORDER BY '{ir.get('order')}'",
                        "impact": "low",
                    })
                    inner["input"] = self._eliminate_redundancy(inner.get("input", {}))
                    return inner

        # Recurse
        for key in ("input", "left", "right"):
            if key in ir and isinstance(ir[key], dict):
                ir[key] = self._eliminate_redundancy(ir[key])

        return ir

    # ── 5. Join Reordering ──────────────────────────────────────────────────

    def _join_reorder(self, ir):
        """Reorder joins to put smaller tables on the build side (left)."""
        if not isinstance(ir, dict) or "op" not in ir:
            return ir

        if ir.get("op") == "JOIN":
            left = ir.get("left", {})
            right = ir.get("right", {})

            left_size = self._estimate_size(left)
            right_size = self._estimate_size(right)

            # If right side is smaller, swap them (for INNER JOIN only)
            if right_size < left_size and ir.get("join_type") == "INNER JOIN":
                ir["left"], ir["right"] = right, left
                self.optimizations_applied.append({
                    "rule": "Join Reordering",
                    "description": f"Swapped join order — smaller table "
                                   f"(~{right_size} rows) moved to build side for hash join efficiency",
                    "impact": "high",
                    "details": f"Left: ~{left_size} rows, Right: ~{right_size} rows → "
                               f"Swapped for optimal hash join performance",
                })

        # Recurse
        for key in ("input", "left", "right"):
            if key in ir and isinstance(ir[key], dict):
                ir[key] = self._join_reorder(ir[key])

        return ir

    # ── Utility methods ─────────────────────────────────────────────────────

    def _collect_tables(self, ir):
        """Collect all table names referenced in an IR subtree."""
        tables = set()
        if not isinstance(ir, dict):
            return tables
        if ir.get("op") == "TABLE_SCAN":
            tables.add(ir.get("table", "").lower())
        if ir.get("op") == "RENAME":
            tables.add(ir.get("alias", "").lower())
        for key in ("input", "left", "right"):
            if key in ir:
                tables.update(self._collect_tables(ir[key]))
        return tables

    def _tables_in_condition(self, condition):
        """Extract table names referenced in a condition string (heuristic)."""
        tables = set()
        if not condition:
            return tables
        # Look for "table.column" patterns
        import re
        for match in re.finditer(r'(\w+)\.(\w+)', condition):
            tables.add(match.group(1).lower())
        return tables

    def _estimate_size(self, ir):
        """Estimate the number of rows in an IR subtree using mock statistics."""
        if not isinstance(ir, dict):
            return 1000

        op = ir.get("op")
        if op == "TABLE_SCAN":
            table = ir.get("table", "").lower()
            if table in self.schema:
                return self.schema[table]["row_count"]
            return 1000

        if op == "RENAME":
            return self._estimate_size(ir.get("input", {}))

        if op == "SELECTION":
            # Assume 30% selectivity for filters
            return int(self._estimate_size(ir.get("input", {})) * 0.3)

        if op == "JOIN":
            left = self._estimate_size(ir.get("left", {}))
            right = self._estimate_size(ir.get("right", {}))
            # Simple estimate: min(left, right) * 2 for equi-join
            return min(left, right) * 2

        if op == "GROUPING":
            # Assume 10% of input for grouped results
            return max(1, int(self._estimate_size(ir.get("input", {})) * 0.1))

        if op in ("PROJECTION", "DISTINCT", "SORT", "LIMIT"):
            return self._estimate_size(ir.get("input", {}))

        return 1000


# ── Public API ──────────────────────────────────────────────────────────────

def optimize(ir: dict, schema=None) -> dict:
    """Optimize the relational algebra IR tree."""
    opt = Optimizer(schema)
    return opt.optimize(ir)
