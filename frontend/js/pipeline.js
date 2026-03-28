/**
 * Pipeline Renderer — Renders output for each compilation stage.
 */

const PipelineRenderer = {

    // ── Lexer Stage ─────────────────────────────────────────────────────

    renderLexer(data, container) {
        container.innerHTML = '';

        if (data.status === 'error') {
            container.innerHTML = this._errorHTML(data.error);
            return;
        }

        const tokens = data.tokens || [];
        const fragment = document.createDocumentFragment();

        // Summary badges
        const summary = document.createElement('div');
        summary.className = 'token-summary';

        const categoryCounts = {};
        tokens.forEach(t => {
            const cat = t.category || t.type;
            categoryCounts[cat] = (categoryCounts[cat] || 0) + 1;
        });

        const categoryColors = {
            DML: '#00d4ff', DDL: '#a855f7', CLAUSE: '#6366f1',
            LOGIC: '#22c55e', FUNCTION: '#f59e0b', TYPE: '#ec4899',
            IDENTIFIER: '#94a3b8', LITERAL: '#fb923c',
            OPERATOR: '#14b8a6', PUNCTUATION: '#64748b'
        };

        Object.entries(categoryCounts).forEach(([cat, count]) => {
            const badge = document.createElement('span');
            badge.className = 'token-count-badge';
            const color = categoryColors[cat] || '#94a3b8';
            badge.innerHTML = `<span class="dot" style="background:${color}"></span>${cat} <strong>${count}</strong>`;
            summary.appendChild(badge);
        });

        fragment.appendChild(summary);

        // Token grid
        const grid = document.createElement('div');
        grid.className = 'token-grid';

        tokens.forEach(token => {
            const chip = document.createElement('div');
            chip.className = 'token-chip';
            chip.dataset.category = token.category || token.type;
            chip.title = `Line ${token.line}, Col ${token.col}`;

            chip.innerHTML = `
                <span class="token-value">${this._escapeHTML(token.value)}</span>
                <span class="token-type">${token.type} · ${token.category || ''}</span>
            `;
            grid.appendChild(chip);
        });

        fragment.appendChild(grid);
        container.appendChild(fragment);
    },

    // ── Parser Stage ────────────────────────────────────────────────────

    renderParser(data, container) {
        container.innerHTML = '';

        if (data.status === 'error') {
            container.innerHTML = this._errorHTML(data.error);
            return;
        }

        const ast = data.ast;
        if (ast) {
            ASTRenderer.render(ast, container);
        }
    },

    // ── Semantic Stage ──────────────────────────────────────────────────

    renderSemantic(data, container) {
        container.innerHTML = '';

        if (data.status === 'error' && data.error) {
            container.innerHTML = this._errorHTML(data.error);
            return;
        }

        const fragment = document.createDocumentFragment();

        // Tables referenced
        const tablesUsed = data.tables_referenced || [];
        if (tablesUsed.length > 0) {
            const section = document.createElement('div');
            section.className = 'semantic-section';
            section.innerHTML = `<div class="semantic-section-title">📊 Tables Referenced</div>`;

            const badges = document.createElement('div');
            badges.className = 'schema-tables-used';

            tablesUsed.forEach(table => {
                const info = data.schema_info?.[table] || {};
                const badge = document.createElement('span');
                badge.className = 'schema-table-badge';
                badge.innerHTML = `${table} <span class="badge-count">(${info.row_count || '?'} rows)</span>`;
                badges.appendChild(badge);
            });

            section.appendChild(badges);
            fragment.appendChild(section);
        }

        // Errors
        const errors = data.errors || [];
        if (errors.length > 0) {
            const section = document.createElement('div');
            section.className = 'semantic-section';
            section.innerHTML = `
                <div class="semantic-section-title">
                    <span class="semantic-badge error">✕ ${errors.length} Error${errors.length > 1 ? 's' : ''}</span>
                </div>
            `;
            errors.forEach(err => {
                const msg = document.createElement('div');
                msg.className = 'semantic-message error';
                msg.innerHTML = `<span class="semantic-icon">✕</span>${this._escapeHTML(err.message)}`;
                section.appendChild(msg);
            });
            fragment.appendChild(section);
        }

        // Warnings
        const warnings = data.warnings || [];
        if (warnings.length > 0) {
            const section = document.createElement('div');
            section.className = 'semantic-section';
            section.innerHTML = `
                <div class="semantic-section-title">
                    <span class="semantic-badge warning">⚠ ${warnings.length} Warning${warnings.length > 1 ? 's' : ''}</span>
                </div>
            `;
            warnings.forEach(w => {
                const msg = document.createElement('div');
                msg.className = 'semantic-message warning';
                msg.innerHTML = `<span class="semantic-icon">⚠</span>${this._escapeHTML(w.message)}`;
                section.appendChild(msg);
            });
            fragment.appendChild(section);
        }

        // Annotations
        const annotations = data.annotations || [];
        if (annotations.length > 0) {
            const section = document.createElement('div');
            section.className = 'semantic-section';
            section.innerHTML = `
                <div class="semantic-section-title">
                    <span class="semantic-badge info">ℹ ${annotations.length} Annotation${annotations.length > 1 ? 's' : ''}</span>
                </div>
            `;
            annotations.forEach(a => {
                const msg = document.createElement('div');
                msg.className = 'semantic-message info';
                msg.innerHTML = `<span class="semantic-icon">ℹ</span>${this._escapeHTML(a.message)}`;
                section.appendChild(msg);
            });
            fragment.appendChild(section);
        }

        // If all clear
        if (errors.length === 0 && warnings.length === 0) {
            const badge = document.createElement('div');
            badge.className = 'semantic-section';
            badge.innerHTML = `
                <div class="semantic-message info" style="background:rgba(34,197,94,0.08);border-color:rgba(34,197,94,0.2)">
                    <span class="semantic-icon">✓</span>
                    <span style="color:#86efac">Semantic analysis passed — no errors or warnings</span>
                </div>
            `;
            fragment.appendChild(badge);
        }

        container.appendChild(fragment);
    },

    // ── ICG Stage ───────────────────────────────────────────────────────

    renderICG(data, container) {
        container.innerHTML = '';

        if (data.status === 'error') {
            container.innerHTML = this._errorHTML(data.error);
            return;
        }

        const fragment = document.createDocumentFragment();

        // Relational algebra expression
        const readable = data.readable || '';
        if (readable) {
            const exprDiv = document.createElement('div');
            exprDiv.className = 'icg-expression';
            exprDiv.innerHTML = this._highlightRA(readable);
            fragment.appendChild(exprDiv);
        }

        // Generation steps
        const steps = data.steps || [];
        if (steps.length > 0) {
            const stepsTitle = document.createElement('div');
            stepsTitle.className = 'semantic-section-title';
            stepsTitle.textContent = 'Generation Steps';
            fragment.appendChild(stepsTitle);

            const stepsDiv = document.createElement('div');
            stepsDiv.className = 'icg-steps';

            steps.forEach((step, i) => {
                const stepEl = document.createElement('div');
                stepEl.className = 'icg-step';
                stepEl.innerHTML = `
                    <span class="icg-step-number">${i + 1}</span>
                    <span class="icg-step-text">${this._highlightRA(this._escapeHTML(step))}</span>
                `;
                stepsDiv.appendChild(stepEl);
            });

            fragment.appendChild(stepsDiv);
        }

        container.appendChild(fragment);
    },

    // ── Optimizer Stage ─────────────────────────────────────────────────

    renderOptimizer(data, container) {
        container.innerHTML = '';

        if (data.status === 'error') {
            container.innerHTML = this._errorHTML(data.error);
            return;
        }

        const fragment = document.createDocumentFragment();

        // Before / After comparison
        const origReadable = data.original_readable || '';
        const optReadable = data.optimized_readable || '';

        const comparison = document.createElement('div');
        comparison.className = 'optimizer-comparison';
        comparison.innerHTML = `
            <div class="optimizer-panel before">
                <div class="optimizer-panel-title">Before Optimization</div>
                <div class="optimizer-expression">${this._highlightRA(this._escapeHTML(origReadable))}</div>
            </div>
            <div class="optimizer-panel after">
                <div class="optimizer-panel-title">After Optimization</div>
                <div class="optimizer-expression">${this._highlightRA(this._escapeHTML(optReadable))}</div>
            </div>
        `;
        fragment.appendChild(comparison);

        // Optimizations applied
        const optimizations = data.optimizations || [];
        if (optimizations.length > 0) {
            const title = document.createElement('div');
            title.className = 'semantic-section-title';
            title.style.marginBottom = '12px';
            title.textContent = 'Optimizations Applied';
            fragment.appendChild(title);

            const impactIcons = {
                high: '🚀',
                medium: '⚡',
                low: '📌',
                neutral: '○'
            };

            optimizations.forEach(opt => {
                const rule = document.createElement('div');
                rule.className = 'optimization-rule';
                const impact = opt.impact || 'neutral';
                rule.innerHTML = `
                    <div class="optimization-impact ${impact}">${impactIcons[impact] || '○'}</div>
                    <div class="optimization-content">
                        <div class="optimization-rule-name">${this._escapeHTML(opt.rule)}</div>
                        <div class="optimization-rule-desc">${this._escapeHTML(opt.description)}</div>
                        ${opt.details ? `<div class="optimization-rule-desc" style="margin-top:4px;color:var(--text-dim);font-style:italic">${this._escapeHTML(opt.details)}</div>` : ''}
                    </div>
                `;
                fragment.appendChild(rule);
            });
        }

        container.appendChild(fragment);
    },

    // ── Helpers ──────────────────────────────────────────────────────────

    _errorHTML(error) {
        if (!error) return '<div class="compile-error">Unknown error</div>';
        const loc = error.line ? `Line ${error.line}, Col ${error.col}` : '';
        return `
            <div class="compile-error">
                <div class="error-stage">${error.stage || 'Error'}</div>
                <div class="error-message">${this._escapeHTML(error.message)}</div>
                ${loc ? `<div class="error-location">${loc}</div>` : ''}
            </div>
        `;
    },

    _escapeHTML(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    },

    _highlightRA(text) {
        // Highlight relational algebra symbols
        return text
            .replace(/σ/g, '<span class="icg-symbol">σ</span>')
            .replace(/π/g, '<span class="icg-symbol">π</span>')
            .replace(/⋈/g, '<span class="icg-symbol">⋈</span>')
            .replace(/⟕/g, '<span class="icg-symbol">⟕</span>')
            .replace(/⟖/g, '<span class="icg-symbol">⟖</span>')
            .replace(/⟗/g, '<span class="icg-symbol">⟗</span>')
            .replace(/γ/g, '<span class="icg-symbol">γ</span>')
            .replace(/τ/g, '<span class="icg-symbol">τ</span>')
            .replace(/δ/g, '<span class="icg-symbol">δ</span>')
            .replace(/ρ/g, '<span class="icg-symbol">ρ</span>')
            .replace(/×/g, '<span class="icg-symbol">×</span>');
    }
};
