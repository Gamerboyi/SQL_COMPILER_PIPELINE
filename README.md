# SQL Compiler Pipeline Visualizer

An interactive web application that demonstrates how a SQL compiler processes queries through each stage of the compilation pipeline.

## Architecture

```
User → Web Interface → Flask Backend API
                           │
               ┌───────────┴───────────┐
            Lexer → Parser → Semantic → ICG → Optimizer
                           │
                   Results Sent Back
                           │
                   Visual Display
```

## Features

- **Lexical Analysis** — Tokenizes SQL into classified tokens (keywords, identifiers, operators, literals)
- **Syntax Analysis** — Recursive descent parser builds an Abstract Syntax Tree (AST)
- **Semantic Analysis** — Validates against a mock database schema with type checking
- **Intermediate Code Generation** — Converts AST to relational algebra notation
- **Query Optimization** — Applies rule-based optimizations (predicate pushdown, join reordering, etc.)

## Supported SQL

- `SELECT` with `WHERE`, `JOIN`, `GROUP BY`, `HAVING`, `ORDER BY`, `LIMIT`
- `INSERT INTO ... VALUES`
- `UPDATE ... SET ... WHERE`
- `DELETE FROM ... WHERE`
- `CREATE TABLE` with column definitions and constraints
- `DROP TABLE`

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12 + Flask |
| Frontend | Vanilla HTML/CSS/JS |
| Editor | CodeMirror 5 |
| Fonts | Inter + JetBrains Mono |

## Setup

### Backend

```bash
cd backend
pip install -r requirements.txt
python app.py
```

The API server starts on `http://localhost:5000`.

### Frontend

Open `frontend/index.html` in your browser, or serve it with any static server:

```bash
cd frontend
python -m http.server 8080
```

Then visit `http://localhost:8080`.

## Mock Database Schema

The compiler uses a built-in mock schema with these tables:

| Table | Columns | Rows |
|-------|---------|------|
| users | id, username, email, age, salary, department, is_active, created_at | 10,000 |
| orders | id, user_id, product_id, quantity, total_price, status, order_date | 50,000 |
| products | id, name, category, price, stock, description | 500 |
| departments | id, name, budget, location | 20 |
| employees | id, name, department_id, manager_id, hire_date, salary, position | 200 |

## Project Structure

```
├── backend/
│   ├── app.py                  # Flask API server
│   ├── requirements.txt
│   └── compiler/
│       ├── lexer.py            # SQL tokenizer
│       ├── parser.py           # Recursive descent parser
│       ├── semantic.py         # Schema & type validation
│       ├── icg.py              # Relational algebra generator
│       ├── optimizer.py        # Rule-based optimizer
│       └── errors.py           # Error classes
├── frontend/
│   ├── index.html
│   ├── css/style.css
│   └── js/
│       ├── app.js              # Main application logic
│       ├── pipeline.js         # Stage output rendering
│       └── ast-renderer.js     # AST tree visualization
├── .gitignore
└── README.md
```
