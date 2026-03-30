/**
 * SQL Compiler Pipeline — Main Application
 *
 * Wires together the CodeMirror editor, API calls, and stage rendering.
 */

const API_BASE = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1' ? 'http://localhost:5000/api' : '/api';

// ── State ──────────────────────────────────────────────────────────────────
let editor = null;
let isCompiling = false;

// ── Initialization ─────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    initEditor();
    initEventListeners();
    loadExamples();
    loadSchema();
    updateEditorInfo();
});

// ── CodeMirror Editor ──────────────────────────────────────────────────────

function initEditor() {
    editor = CodeMirror.fromTextArea(document.getElementById('sql-editor'), {
        mode: 'text/x-sql',
        theme: 'material-darker',
        lineNumbers: true,
        lineWrapping: true,
        indentWithTabs: false,
        indentUnit: 2,
        tabSize: 2,
        matchBrackets: true,
        autoCloseBrackets: true,
        styleActiveLine: true,
        placeholder: 'Enter your SQL query here...',
        extraKeys: {
            'Ctrl-Enter': () => compile(),
            'Cmd-Enter': () => compile(),
        }
    });

    editor.on('change', () => {
        updateEditorInfo();
    });

    // Initial info
    setTimeout(updateEditorInfo, 100);
}

function updateEditorInfo() {
    if (!editor) return;
    const val = editor.getValue();
    document.getElementById('char-count').textContent = `${val.length} chars`;
    document.getElementById('line-count').textContent = `${val.split('\n').length} lines`;
}

// ── Event Listeners ────────────────────────────────────────────────────────

function initEventListeners() {
    // Compile button
    document.getElementById('btn-compile').addEventListener('click', compile);

    // Clear button
    document.getElementById('btn-clear').addEventListener('click', () => {
        editor.setValue('');
        resetStages();
    });

    // Example selector
    document.getElementById('example-select').addEventListener('change', (e) => {
        const idx = parseInt(e.target.value);
        if (!isNaN(idx) && window._examples && window._examples[idx]) {
            editor.setValue(window._examples[idx].sql);
            updateEditorInfo();
        }
        e.target.value = '';
    });

    // Stage headers — toggle expand/collapse
    document.querySelectorAll('.stage-header').forEach(header => {
        header.addEventListener('click', () => {
            const card = header.closest('.stage-card');
            card.classList.toggle('expanded');
        });
    });

    // Expand / Collapse all
    document.getElementById('btn-expand-all').addEventListener('click', () => {
        document.querySelectorAll('.stage-card').forEach(c => c.classList.add('expanded'));
    });
    document.getElementById('btn-collapse-all').addEventListener('click', () => {
        document.querySelectorAll('.stage-card').forEach(c => c.classList.remove('expanded'));
    });

    // Schema sidebar
    document.getElementById('btn-schema').addEventListener('click', () => {
        document.getElementById('schema-sidebar').classList.toggle('open');
    });
    document.getElementById('btn-close-schema').addEventListener('click', () => {
        document.getElementById('schema-sidebar').classList.remove('open');
    });

    // Help modal
    document.getElementById('btn-help').addEventListener('click', () => {
        document.getElementById('help-modal').classList.add('open');
    });
    document.getElementById('btn-close-help').addEventListener('click', () => {
        document.getElementById('help-modal').classList.remove('open');
    });
    document.getElementById('help-modal').addEventListener('click', (e) => {
        if (e.target === e.currentTarget) {
            e.currentTarget.classList.remove('open');
        }
    });

    // Panel resizer
    initPanelResizer();

    // Keyboard shortcut
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            document.getElementById('help-modal').classList.remove('open');
            document.getElementById('schema-sidebar').classList.remove('open');
        }
    });
}

// ── Panel Resizer ──────────────────────────────────────────────────────────

function initPanelResizer() {
    const divider = document.getElementById('panel-divider');
    const editorPanel = document.getElementById('panel-editor');
    let isDragging = false;

    divider.addEventListener('mousedown', (e) => {
        isDragging = true;
        divider.classList.add('dragging');
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
        e.preventDefault();
    });

    document.addEventListener('mousemove', (e) => {
        if (!isDragging) return;
        const main = document.getElementById('app-main');
        const rect = main.getBoundingClientRect();
        const percent = ((e.clientX - rect.left) / rect.width) * 100;
        const clamped = Math.max(25, Math.min(65, percent));
        editorPanel.style.width = `${clamped}%`;
        editor.refresh();
    });

    document.addEventListener('mouseup', () => {
        if (isDragging) {
            isDragging = false;
            divider.classList.remove('dragging');
            document.body.style.cursor = '';
            document.body.style.userSelect = '';
            editor.refresh();
        }
    });
}

// ── Compile ────────────────────────────────────────────────────────────────

async function compile() {
    if (isCompiling) return;
    const sql = editor.getValue().trim();
    if (!sql) return;

    isCompiling = true;
    const btn = document.getElementById('btn-compile');
    btn.classList.add('compiling');
    btn.innerHTML = `
        <svg class="spin" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10" stroke-dasharray="32" stroke-dashoffset="32"><animateTransform attributeName="transform" type="rotate" from="0 12 12" to="360 12 12" dur="0.8s" repeatCount="indefinite"/></circle></svg>
        Compiling…
    `;

    resetStages();

    // Animate stages sequentially
    const stageNames = ['lexer', 'parser', 'semantic', 'icg', 'optimizer'];
    stageNames.forEach(s => {
        document.getElementById(`stage-${s}`).classList.add('processing');
    });

    try {
        const response = await fetch(`${API_BASE}/compile`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ sql }),
        });

        const data = await response.json();

        // Remove processing animation
        stageNames.forEach(s => {
            document.getElementById(`stage-${s}`).classList.remove('processing');
        });

        // Render each stage with staggered delay
        const stages = data.stages || {};
        const stageRenderers = {
            lexer: PipelineRenderer.renderLexer.bind(PipelineRenderer),
            parser: PipelineRenderer.renderParser.bind(PipelineRenderer),
            semantic: PipelineRenderer.renderSemantic.bind(PipelineRenderer),
            icg: PipelineRenderer.renderICG.bind(PipelineRenderer),
            optimizer: PipelineRenderer.renderOptimizer.bind(PipelineRenderer),
        };

        for (let i = 0; i < stageNames.length; i++) {
            const name = stageNames[i];
            const stageData = stages[name];
            if (!stageData) continue;

            await delay(120 * i);

            const card = document.getElementById(`stage-${name}`);
            const output = document.getElementById(`${name}-output`);
            const timeEl = document.getElementById(`${name}-time`);
            const statusEl = document.getElementById(`${name}-status`);

            // Render output
            stageRenderers[name](stageData, output);

            // Update time
            if (stageData.time_ms !== undefined) {
                timeEl.textContent = `${stageData.time_ms}ms`;
            }

            // Update status indicator
            if (stageData.status === 'error') {
                statusEl.className = 'stage-status error';
                card.classList.add('error');
                card.classList.add('expanded');
                card.classList.add('active');
            } else if (stageData.status === 'success') {
                const hasWarnings = stageData.warnings && stageData.warnings.length > 0;
                statusEl.className = `stage-status ${hasWarnings ? 'warning' : 'success'}`;
                card.classList.add('active');
                card.classList.add('expanded');
            }

            // Stop rendering if error
            if (stageData.status === 'error' && !stages[stageNames[i + 1]]) {
                break;
            }
        }

        // Update total time
        if (data.total_time_ms !== undefined) {
            document.getElementById('timer-value').textContent = `${data.total_time_ms}ms`;
        }

    } catch (err) {
        console.error('Compile error:', err);
        stageNames.forEach(s => {
            document.getElementById(`stage-${s}`).classList.remove('processing');
        });
        const lexerOutput = document.getElementById('lexer-output');
        lexerOutput.innerHTML = `
            <div class="compile-error">
                <div class="error-stage">Connection Error</div>
                <div class="error-message">Could not connect to the backend server. Make sure the Flask server is running on port 5000.</div>
                <div class="error-location">Run: cd backend && python app.py</div>
            </div>
        `;
        const card = document.getElementById('stage-lexer');
        card.classList.add('expanded', 'error');
    }

    isCompiling = false;
    btn.classList.remove('compiling');
    btn.innerHTML = `
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>
        Compile
    `;
}

function resetStages() {
    const stageNames = ['lexer', 'parser', 'semantic', 'icg', 'optimizer'];
    stageNames.forEach(name => {
        const card = document.getElementById(`stage-${name}`);
        card.classList.remove('active', 'error', 'expanded', 'processing');

        document.getElementById(`${name}-output`).innerHTML =
            '<div class="stage-placeholder">Click <strong>Compile</strong> to see results</div>';
        document.getElementById(`${name}-time`).textContent = '—';
        document.getElementById(`${name}-status`).className = 'stage-status';
    });
    document.getElementById('timer-value').textContent = '—';
}

// ── Load Examples ──────────────────────────────────────────────────────────

async function loadExamples() {
    try {
        const res = await fetch(`${API_BASE}/examples`);
        const examples = await res.json();
        window._examples = examples;

        const select = document.getElementById('example-select');
        examples.forEach((ex, i) => {
            const opt = document.createElement('option');
            opt.value = i;
            opt.textContent = ex.name;
            select.appendChild(opt);
        });
    } catch (err) {
        console.warn('Could not load examples:', err);
        // Fallback: hardcode some examples
        window._examples = [
            { name: 'Simple SELECT', sql: "SELECT username, email\nFROM users\nWHERE age > 25;" }
        ];
    }
}

// ── Load Schema ────────────────────────────────────────────────────────────

async function loadSchema() {
    try {
        const res = await fetch(`${API_BASE}/schema`);
        const schema = await res.json();
        renderSchema(schema);
    } catch (err) {
        console.warn('Could not load schema:', err);
        // Render a static fallback schema
        renderSchema({
            users: { columns: { id: 'INT', username: 'VARCHAR', email: 'VARCHAR', age: 'INT', salary: 'DECIMAL', department: 'VARCHAR', is_active: 'BOOLEAN', created_at: 'DATE' }, row_count: 10000 },
            orders: { columns: { id: 'INT', user_id: 'INT', product_id: 'INT', quantity: 'INT', total_price: 'DECIMAL', status: 'VARCHAR', order_date: 'DATE' }, row_count: 50000 },
            products: { columns: { id: 'INT', name: 'VARCHAR', category: 'VARCHAR', price: 'DECIMAL', stock: 'INT', description: 'TEXT' }, row_count: 500 },
            departments: { columns: { id: 'INT', name: 'VARCHAR', budget: 'DECIMAL', location: 'VARCHAR' }, row_count: 20 },
            employees: { columns: { id: 'INT', name: 'VARCHAR', department_id: 'INT', manager_id: 'INT', hire_date: 'DATE', salary: 'DECIMAL', position: 'VARCHAR' }, row_count: 200 },
        });
    }
}

function renderSchema(schema) {
    const container = document.getElementById('schema-content');
    container.innerHTML = '';

    Object.entries(schema).forEach(([tableName, info]) => {
        const tableDiv = document.createElement('div');
        tableDiv.className = 'schema-table';

        let html = `<div class="schema-table-name">
            <span>📋 ${tableName}</span>
            <span class="row-count">~${(info.row_count || 0).toLocaleString()} rows</span>
        </div>`;
        html += '<div class="schema-columns">';

        Object.entries(info.columns || {}).forEach(([colName, colType]) => {
            html += `<div class="schema-col">
                <span class="schema-col-name">${colName}</span>
                <span class="schema-col-type">${colType}</span>
            </div>`;
        });

        html += '</div>';
        tableDiv.innerHTML = html;
        container.appendChild(tableDiv);
    });
}

// ── Utility ────────────────────────────────────────────────────────────────

function delay(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}
