// --- Graph & Interaction State ---
let graphData = { nodes: [], links: [] };
let mergeData = [];
let simulation, svg, g, linkElements, nodeElements;
let width, height, zoomBehavior;
let selectedNodeId = null;

// --- Temporal State ---
let timeMin = 0, timeMax = 0, timeCurrent = 0;
let entityFilters = new Set();
let claimFilters = new Set();
let confThreshold = 0.4;

document.addEventListener('DOMContentLoaded', initApp);

async function initApp() {
    try {
        const timestamp = Date.now();
        const [gRes, mRes] = await Promise.all([
            fetch(`../data/graph.json?t=${timestamp}`),
            fetch(`../data/entity_merges.json?t=${timestamp}`).catch(() => ({ ok: true, json: () => [] }))
        ]);

        if (!gRes.ok) throw new Error(`HTTP Error ${gRes.status} fetching graph.json`);
        graphData = await gRes.json();

        // NetworkX node_link_data outputs either "links" or "edges" depending on version. D3 needs "links".
        if (graphData.edges && !graphData.links) {
            graphData.links = graphData.edges;
        }

        if (mRes.ok) {
            try { mergeData = await mRes.json() || []; } catch (e) { mergeData = []; }
        } else {
            mergeData = [];
        }

        preprocessData();
        setupUI();
        initVisualization();

        document.getElementById('loading-overlay').style.display = 'none';
        applyTimeFilter();
    } catch (err) {
        console.error("Data load failed:", err);
        document.getElementById('loading-overlay').innerHTML = `
            <div style="color: #ef4444; max-width: 600px; padding: 20px; background: rgba(0,0,0,0.8); border: 1px solid #ef4444; font-family: monospace;">
                <h3>UI Initialization Error</h3>
                <p>${err.toString()}</p>
                <p style="font-size: 0.8rem; margin-top: 10px; color: #888;">Stack Trace:</p>
                <pre style="font-size: 0.7rem; color: #ccc; white-space: pre-wrap; text-align: left;">${err.stack || 'No stack trace'}</pre>
            </div>
        `;
    }
}

function preprocessData() {
    let minT = Infinity, maxT = -Infinity;

    graphData.nodes.forEach(n => {
        n.isEvent = n.id.startsWith("assertion::") || n.id.startsWith("Event::") || n.type === "event" || n.type === "Claim";
        n.displayType = n.isEvent ? "claim" : (n.type ? n.type.toLowerCase() : "unknown");

        // Bitemporal resolution
        n.startT = n.valid_from ? new Date(n.valid_from).getTime() : 0;
        n.endT = n.valid_until ? new Date(n.valid_until).getTime() : Infinity;

        // Skip finding limits for generic timeless entities if they have 0
        if (n.startT > 0) {
            if (n.startT < minT) minT = n.startT;
            if (n.startT > maxT) maxT = n.startT;
        }

        if (n.isEvent && n.claim_type) claimFilters.add(n.claim_type);
        if (!n.isEvent) entityFilters.add(n.displayType);
    });

    if (minT !== Infinity && maxT !== -Infinity) {
        timeMin = minT; timeMax = maxT; timeCurrent = maxT;

        const sd = new Date(minT);
        document.getElementById('time-display-min').textContent = `${sd.getFullYear()}-${String(sd.getMonth() + 1).padStart(2, '0')}`;
    }

    // Populate Sidebar Checkboxes
    const addChecks = (containerId, set) => {
        const c = document.getElementById(containerId);
        Array.from(set).sort().forEach(item => {
            c.innerHTML += `<div><input type="checkbox" id="chk-${item}" value="${item}" checked><label for="chk-${item}">${item}</label></div>`;
        });
        c.querySelectorAll('input').forEach(i => i.addEventListener('change', applyTimeFilter));
    };
    addChecks('entity-filters', entityFilters);
    addChecks('claim-filters', claimFilters);

    document.getElementById('stat-nodes').textContent = graphData.nodes.filter(n => !n.isEvent).length;
    document.getElementById('stat-edges').textContent = graphData.nodes.filter(n => n.isEvent).length;
}

function setupUI() {
    // Zoom Controls
    document.getElementById('zoom-in').addEventListener('click', () => svg.transition().call(zoomBehavior.scaleBy, 1.4));
    document.getElementById('zoom-out').addEventListener('click', () => svg.transition().call(zoomBehavior.scaleBy, 0.7));
    document.getElementById('zoom-fit').addEventListener('click', () => {
        svg.transition().duration(750).call(zoomBehavior.transform, d3.zoomIdentity.translate(width / 2, height / 2).scale(0.8).translate(-width / 2, -height / 2));
    });

    // Filtering Sliders
    document.getElementById('conf-slider').addEventListener('input', e => {
        confThreshold = parseFloat(e.target.value);
        document.getElementById('conf-val').textContent = confThreshold.toFixed(2);
        applyTimeFilter();
    });

    const timeSlider = document.getElementById('time-slider');
    const timeDisplay = document.getElementById('time-display');
    timeSlider.addEventListener('input', e => {
        const pct = parseInt(e.target.value) / 100;
        timeCurrent = timeMin + (timeMax - timeMin) * pct;

        if (pct === 1) {
            timeDisplay.textContent = "NOW";
        } else {
            const d = new Date(timeCurrent);
            timeDisplay.textContent = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
        }
        applyTimeFilter();
    });

    // Inspector Close
    document.getElementById('close-inspector').addEventListener('click', () => {
        document.getElementById('inspector-panel').classList.remove('open');
        selectedNodeId = null;
        nodeElements.classed("highlighted", false).classed("dimmed", false);
        linkElements.classed("highlighted", false).classed("dimmed", false);
    });
}

function initVisualization() {
    const container = document.querySelector('.graph-container');
    width = container.clientWidth;
    height = container.clientHeight;

    svg = d3.select("#network-graph").attr("viewBox", [0, 0, width, height]);
    g = svg.append("g");

    zoomBehavior = d3.zoom().scaleExtent([0.1, 8]).on("zoom", e => g.attr("transform", e.transform));
    svg.call(zoomBehavior);

    simulation = d3.forceSimulation(graphData.nodes)
        .force("link", d3.forceLink(graphData.links).id(d => d.id).distance(100))
        .force("charge", d3.forceManyBody().strength(-200))
        .force("center", d3.forceCenter(width / 2, height / 2))
        .force("collide", d3.forceCollide().radius(25).iterations(2));

    // Links as curved paths
    linkElements = g.append("g").attr("class", "links")
        .selectAll("path")
        .data(graphData.links)
        .enter().append("path")
        .attr("class", "link")
        .attr("stroke-width", d => Math.max(0.5, (d.confidence || 0.5) * 4)); // Edge thickness based on confidence

    // Nodes
    nodeElements = g.append("g").attr("class", "nodes")
        .selectAll("g")
        .data(graphData.nodes)
        .enter().append("g")
        .attr("class", "node")
        .on("click", handleNodeClick)
        .call(d3.drag()
            .on("start", dragstarted)
            .on("drag", dragged)
            .on("end", dragended));

    // Shape rendering
    nodeElements.each(function (d) {
        const el = d3.select(this);
        if (d.isEvent) {
            el.append("rect")
                .attr("width", 18).attr("height", 18)
                .attr("x", -9).attr("y", -9)
                .attr("rx", 3);
        } else {
            el.append("circle").attr("r", 12);
        }
        const name = d.name || d.id.split("::").pop() || "Unknown";
        el.append("text")
            .attr("dx", 16).attr("dy", ".3em")
            .text(name.length > 25 ? name.substring(0, 25) + "..." : name);
    });

    simulation.on("tick", () => {
        // Curved Edges via Arc Path
        linkElements.attr("d", d => {
            const dx = d.target.x - d.source.x, dy = d.target.y - d.source.y;
            const dr = Math.sqrt(dx * dx + dy * dy);
            // Avoid divide by zero curve explosion on exact overlap
            return `M${d.source.x},${d.source.y}A${dr},${dr} 0 0,1 ${d.target.x},${d.target.y}`;
        });
        nodeElements.attr("transform", d => `translate(${d.x},${d.y})`);
    });

    svg.call(zoomBehavior.transform, d3.zoomIdentity.translate(width / 2, height / 2).scale(0.8).translate(-width / 2, -height / 2));
}

// Applies filters and mutates color state (Time Travel logic)
function applyTimeFilter() {
    const activeE = new Set(Array.from(document.querySelectorAll('#entity-filters input:checked')).map(el => el.value));
    const activeC = new Set(Array.from(document.querySelectorAll('#claim-filters input:checked')).map(el => el.value));

    nodeElements.each(function (d) {
        const el = d3.select(this);
        let isVisible = true;
        let temporalState = 'invisible'; // active, superseded, redacted

        // 1. Time evaluation
        if (d.startT > 0 && d.startT > timeCurrent) {
            isVisible = false;
        } else {
            if (d.status === 'redacted') {
                temporalState = 'redacted';
            } else if (timeCurrent >= d.endT) {
                temporalState = 'superseded';
            } else {
                temporalState = 'active';
            }
        }

        // 2. Type/Confidence evaluation
        if (d.isEvent) {
            if (d.claim_type && !activeC.has(d.claim_type)) isVisible = false;
            if ((d.confidence || 0) < confThreshold) isVisible = false;
        } else {
            if (!activeE.has(d.displayType)) isVisible = false;
        }

        d.isVisible = isVisible;
        d.temporalState = temporalState;

        el.classed("hidden", !isVisible);

        // Remove old states, apply new
        el.classed("state-active state-superseded state-redacted", false);
        if (isVisible) el.classed(`state-${temporalState}`, true);
    });

    linkElements.each(function (d) {
        const el = d3.select(this);
        const vis = d.source.isVisible && d.target.isVisible;
        el.classed("hidden", !vis);

        // Links color inherit from event source, or just active
        el.classed("active", vis && (d.source.temporalState === 'active' || d.target.temporalState === 'active'));
        el.classed("superseded", vis && (d.source.temporalState === 'superseded' || d.target.temporalState === 'superseded'));
    });
}

function handleNodeClick(e, d) {
    e.stopPropagation();
    selectedNodeId = d.id;

    // 1. Highlight graph neighbors
    nodeElements.classed("highlighted", false).classed("dimmed", true);
    linkElements.classed("dimmed", true);

    const neighbors = new Set([d.id]);
    linkElements.each(function (l) {
        if (!l.source.isVisible || !l.target.isVisible) return;
        if (l.source.id === d.id) { neighbors.add(l.target.id); d3.select(this).classed("dimmed", false); }
        if (l.target.id === d.id) { neighbors.add(l.source.id); d3.select(this).classed("dimmed", false); }
    });

    nodeElements.filter(n => neighbors.has(n.id))
        .classed("highlighted", true)
        .classed("dimmed", false);

    // 2. Camera Snap to Node
    const currentTransform = d3.zoomTransform(svg.node());
    const panelOffset = 200; // Account for right sidebar width
    const targetX = (width / 2) - panelOffset - (d.x * currentTransform.k);
    const targetY = (height / 2) - (d.y * currentTransform.k);

    svg.transition().duration(750)
        .call(zoomBehavior.transform, d3.zoomIdentity.translate(targetX, targetY).scale(currentTransform.k));

    // 3. Populate Right Panel
    openInspector(d);
}

function openInspector(d) {
    const panel = document.getElementById('inspector-panel');
    const content = document.getElementById('insp-content');

    document.getElementById('insp-type').textContent = d.isEvent ? (d.claim_type || d.type) : "ENTITY";
    document.getElementById('insp-type').style.color = d.temporalState === 'superseded' ? 'var(--color-superseded)' : 'var(--color-active-truth)';
    document.getElementById('insp-title').textContent = d.name || d.id;
    document.getElementById('insp-id').textContent = `ID: ${d.id}`;

    // Merges
    const blockMerges = document.getElementById('block-merges');
    if (!d.isEvent && d.aliases && d.aliases.length > 0) {
        blockMerges.classList.remove('hidden');
        let html = "";
        d.aliases.forEach(alias => {
            const mData = mergeData.find(m => m.canonical_id === d.id && m.merged_entity_id === alias);
            const reason = mData ? mData.reason : "Alias match";
            html += `<div class="log-line"><span class="log-key">Alias:</span> <span>${alias}</span></div>`;
            html += `<div class="log-line" style="margin-bottom: 8px"><span class="log-key">Reason:</span> <span style="color:var(--text-muted)">${reason}</span></div>`;
        });
        document.getElementById('merge-list').innerHTML = html;
    } else {
        blockMerges.classList.add('hidden');
    }

    // Evidence
    const blockEvidence = document.getElementById('block-evidence');
    if (d.isEvent && d.evidence && d.evidence.length > 0) {
        blockEvidence.classList.remove('hidden');
        document.getElementById('ev-count').textContent = d.evidence.length;

        let html = "";
        d.evidence.forEach(ev => {
            const offsetStr = ev.offset_start != null ? `${ev.offset_start}..${ev.offset_end}` : "unknown";
            const timeStr = ev.timestamp ? new Date(ev.timestamp).toISOString().split('T')[0] : '';
            const urlStr = ev.url ? `<a href="${ev.url}" target="_blank" class="ev-link">[${ev.source_id}]</a>` : `[${ev.source_id}]`;

            html += `
                <div class="evidence-card">
                    <div class="ev-header">
                        <div class="ev-meta-row">
                            <span class="ev-offset">[offs: ${offsetStr}]</span>
                            <span>TS: ${timeStr}</span>
                        </div>
                        <div class="ev-meta-row">
                            ${urlStr}
                            <span>cnf: ${(ev.confidence || 1).toFixed(2)}</span>
                        </div>
                    </div>
                    <div class="ev-excerpt">"${ev.excerpt}"</div>
                </div>
            `;
        });
        document.getElementById('evidence-list').innerHTML = html;
    } else {
        blockEvidence.classList.add('hidden');
    }

    // JSON Raw
    document.getElementById('insp-json').textContent = JSON.stringify(d, null, 2);

    content.classList.remove('hidden');
    panel.classList.add('open');
}

// Chart background click
d3.select("main").on("click", (e) => {
    if (e.target.tagName === "svg") document.getElementById('close-inspector').click();
});

// Drag
function dragstarted(e, d) { if (!e.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; }
function dragged(e, d) { d.fx = e.x; d.fy = e.y; }
function dragended(e, d) { if (!e.active) simulation.alphaTarget(0); d.fx = null; d.fy = null; }
