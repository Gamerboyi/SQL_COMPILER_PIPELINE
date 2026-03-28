/**
 * AST Renderer — Renders an AST tree as interactive collapsible HTML nodes.
 */

const ASTRenderer = {
    /**
     * Render an AST node into an HTML container.
     * @param {Object} ast - The AST object (dict-like)
     * @param {HTMLElement} container - DOM element to render into
     */
    render(ast, container) {
        container.innerHTML = '';
        const wrapper = document.createElement('div');
        wrapper.className = 'ast-container';
        this._renderNode(ast, wrapper, 0);
        container.appendChild(wrapper);
    },

    _renderNode(node, parent, depth) {
        if (!node || typeof node !== 'object') {
            return;
        }

        // Array handling
        if (Array.isArray(node)) {
            node.forEach((item, i) => {
                this._renderNode(item, parent, depth);
            });
            return;
        }

        const nodeType = node.type || node.op || 'Object';
        const hasChildren = this._hasChildren(node);

        const nodeEl = document.createElement('div');
        nodeEl.className = 'ast-node';
        nodeEl.style.marginLeft = depth > 0 ? '20px' : '0';

        // Node header (clickable)
        const itemEl = document.createElement('div');
        itemEl.className = 'ast-item';

        // Toggle button (if has children)
        if (hasChildren) {
            const toggle = document.createElement('button');
            toggle.className = 'ast-toggle';
            toggle.textContent = '▼';
            toggle.addEventListener('click', (e) => {
                e.stopPropagation();
                const children = nodeEl.querySelector('.ast-children');
                if (children) {
                    const isCollapsed = children.classList.contains('collapsed');
                    children.classList.toggle('collapsed');
                    toggle.textContent = isCollapsed ? '▼' : '▶';
                }
            });
            itemEl.appendChild(toggle);
        } else {
            const spacer = document.createElement('span');
            spacer.style.width = '16px';
            spacer.style.display = 'inline-block';
            itemEl.appendChild(spacer);
        }

        // Node type label
        const typeSpan = document.createElement('span');
        typeSpan.className = 'ast-type';
        typeSpan.textContent = nodeType;
        itemEl.appendChild(typeSpan);

        // Inline leaf values
        const leafValue = this._getLeafValue(node);
        if (leafValue !== null) {
            const valSpan = document.createElement('span');
            valSpan.className = 'ast-value ast-leaf';
            valSpan.textContent = ` = ${leafValue}`;
            itemEl.appendChild(valSpan);
        }

        // Simple properties (non-object, non-array)
        const simpleProps = this._getSimpleProps(node);
        if (simpleProps.length > 0) {
            const propsSpan = document.createElement('span');
            propsSpan.className = 'ast-value';
            propsSpan.textContent = ` { ${simpleProps.join(', ')} }`;
            itemEl.appendChild(propsSpan);
        }

        nodeEl.appendChild(itemEl);

        // Children container
        if (hasChildren) {
            const childrenEl = document.createElement('div');
            childrenEl.className = 'ast-children';
            // Auto-collapse deep nodes
            if (depth > 3) {
                childrenEl.classList.add('collapsed');
                const toggle = itemEl.querySelector('.ast-toggle');
                if (toggle) toggle.textContent = '▶';
            }

            const childKeys = this._getChildKeys(node);
            childKeys.forEach(key => {
                const value = node[key];

                // Label for the child key
                const label = document.createElement('div');
                label.className = 'ast-item';
                label.style.marginLeft = '20px';

                const labelSpan = document.createElement('span');
                labelSpan.className = 'ast-value';
                labelSpan.textContent = `${key}:`;
                labelSpan.style.color = 'var(--text-muted)';
                labelSpan.style.fontWeight = '500';
                label.appendChild(labelSpan);

                if (typeof value === 'object' && value !== null) {
                    childrenEl.appendChild(label);
                    if (Array.isArray(value)) {
                        value.forEach(item => {
                            this._renderNode(item, childrenEl, depth + 1);
                        });
                    } else {
                        this._renderNode(value, childrenEl, depth + 1);
                    }
                } else {
                    const valSpan = document.createElement('span');
                    valSpan.className = 'ast-value ast-leaf';
                    valSpan.textContent = ` ${JSON.stringify(value)}`;
                    label.appendChild(valSpan);
                    childrenEl.appendChild(label);
                }
            });

            nodeEl.appendChild(childrenEl);
        }

        parent.appendChild(nodeEl);
    },

    _hasChildren(node) {
        return this._getChildKeys(node).length > 0;
    },

    _getChildKeys(node) {
        const skipKeys = new Set(['type', 'op', 'value', 'name', 'operator', 'direction',
            'symbol', 'alias', 'join_type', 'negated', 'distinct', 'data_type',
            'table', 'column', 'if_exists', 'note', 'cast_type', 'condition',
            'columns', 'group_by', 'aggregates', 'order', 'count', 'offset',
            'assignments', 'values']);

        const childKeys = [];
        for (const key of Object.keys(node)) {
            const val = node[key];
            if (typeof val === 'object' && val !== null && !skipKeys.has(key)) {
                childKeys.push(key);
            }
            // Also include these complex keys that are arrays/objects
            if (skipKeys.has(key) && typeof val === 'object' && val !== null) {
                childKeys.push(key);
            }
        }
        return childKeys;
    },

    _getSimpleProps(node) {
        const skipKeys = new Set(['type', 'op', 'children']);
        const props = [];
        for (const [key, val] of Object.entries(node)) {
            if (skipKeys.has(key)) continue;
            if (typeof val !== 'object' || val === null) {
                if (val !== undefined && val !== null && val !== '') {
                    props.push(`${key}: ${val}`);
                }
            }
        }
        // Limit to avoid clutter
        return props.slice(0, 5);
    },

    _getLeafValue(node) {
        // For simple leaf nodes, return the primary value
        if (node.type === 'NumberLiteral' || node.type === 'StringLiteral' ||
            node.type === 'BooleanLiteral' || node.type === 'NullLiteral') {
            return node.value;
        }
        if (node.type === 'Identifier') {
            return node.value;
        }
        if (node.type === 'Star') {
            return '*';
        }
        return null;
    }
};
