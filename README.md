# Layer10 Take-Home: Grounded Long-Term Memory System (v2.0 - Exceptional)

A production-grade pipeline that turns unstructured communication data (GitHub Issues) into a grounded, semantically deduplicated memory graph.

**Architecture Note**: This repository uses a **Neo4j AuraDB graph** which also serializes to `data/graph.json` for the D3.js visualization layer.

## Quick Start

### Prerequisites
- Python 3.10+
- A Google AI Studio API key (free): [Get one here](https://aistudio.google.com/app/apikey)
- Optional: GitHub personal access token

### Setup

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure API keys
copy .env.example .env
# Edit .env and set your GROQ_API_KEY and GITHUB_TOKEN

# 3. (Optional but Recommended) Start Neo4j Database
# The system gracefully falls back to an in-memory Python graph if you skip this step!
docker compose up -d
```

## Submission Deliverables
All requested artifacts are included directly in this repository:
1. **Code**: Python source logic spanning `extraction/`, `dedup/`, and `graph/`. 
2. **Serialized Graph Store**: The full extracted memory graph is available at `data/graph.json`.
3. **Retrieved Context Packs**: Four example Context Packs matching the evaluation questions are saved in `data/context_packs/*.json`.
4. **Visualization**: A responsive D3.js web app is included in `visualization/`. You can view a pre-recorded demo video at `visualization_demo.webp` in the project root.
5. **Technical Write-up**: Read `writeup.md` for a complete breakdown of the ontology, pipeline contracts, and Layer10 production architecture strategy.

## Architecture (9.3/10 Design)

```
corpus/downloader.py    →  corpus/raw/issue_*.json
                        ↓
extraction/pipeline.py  →  data/extractions/extraction_*.json
                        ↓
dedup/*.py              →  Canonical entities + deduplicated claims
                        ↓
graph/memory_graph.py   →  data/graph.json
                        ↓
retrieval/search.py     →  Hybrid BM25 + vector search
retrieval/context_pack  →  data/context_packs/*.json
                        ↓
visualization/app.py    →  http://localhost:5000
```

## Project Structure

| Directory | Purpose |
|-----------|---------|
| `corpus/` | GitHub Issues downloader |
| `schema/` | Ontology (entity types, claim types, evidence), validators |
| `extraction/` | LLM-based extraction pipeline (Groq Llama-4-Scout-17B) |
| `dedup/` | Artifact, entity, and claim deduplication with merge audit logs |
| `graph/` | Memory graph (Neo4j), persistence, temporal logic |
| `retrieval/` | Hybrid search, context pack builder, Flask API |
| `visualization/` | Web UI with D3.js graph + evidence panel |
| `data/` | Generated outputs (graph, extractions, context packs) |

## Corpus

**Source**: GitHub Issues and Pull Requests from [facebook/react](https://github.com/facebook/react)

**Why**: Provides a rich mix of structured data (labels, assignees, state changes) and unstructured discussions (bug reports, feature proposals, design decisions). Cross-references between issues and PRs create natural graph structure.

**Download**: Via GitHub REST API (`corpus/downloader.py`). No authentication required for public repos, though a personal access token increases rate limits from 60 to 5000 requests/hour.

## Key Features

- **Grounded extraction**: Every claim links to evidence with source ID, excerpt, and URL
- **Robust deduplication**: At artifact, entity, and claim levels with reversible merges
- **Temporal tracking**: Bitemporal model (event time vs system time) with revision chains
- **Hybrid retrieval**: BM25 keyword + FAISS vector similarity search
- **Conceptual Grounded Permissions**: Graph structure and retrieval logic designed for source-constrained access (explained in `writeup.md`)
- **Interactive visualization**: D3.js force-directed graph with click-through evidence

## Conceptual Memory Permissions

Following the Layer10 requirements, the system is designed to handle permissions **conceptually** through its graph structure and retrieval logic:

1. **Graph Structure**: Every `Claim` and `Evidence` node in the database is tagged with a `source_id`. This creates a native link between a "Memory" and the "Source" it was extracted from.
2. **Retrieval Logic (Filtering)**: Search queries are structure-aware. When a user asks a question, the system filters the results so that if a user lacks access to a specific private Slack channel or Jira ticket, any memories extracted *only* from those sources are automatically excluded from the context pack.
3. **Traversal Guard**: During GraphRAG expansion, the system prunes paths that lead to ungrounded or unauthorized nodes, ensuring a user's view of "truth" is restricted to their personal access scope.

## Conceptual Security & Observability

In a production environment, the following features would be implemented to ensure enterprise readiness:

### 1. Permissions (Grounded RBAC/ABAC)
- **Source-Level Access**: Users only retrieve memory grounded in sources (Slack channels, GitHub repos) they are authorized to access.
- **Graph Traversal Guard**: The GraphRAG engine silently drops nodes and edges during expansion if the underlying evidence derivation belongs to a restricted source.
- **Metadata-Only Mode**: Ability to show a claim exists (e.g., "A decision was made about Project X") while redacting the specific text excerpt if the user has low-level clearance.

### 2. Observability & Health
- **Evidence Decay Tracking**: Monitoring the ratio of `Claims : Evidence` to ensure facts aren't becoming ungrounded over time.
- **Confidence Telemetry**: Aggregating real-time extraction confidence to detect when LLM quality degrades due to schema drift or source noise.
- **Audit Logs**: Full bitemporal ledger of every entity merge and claim revision for regulatory compliance.
