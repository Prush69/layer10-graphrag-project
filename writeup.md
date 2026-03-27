# Layer10: Grounded Organizational Memory System — Technical Write-Up

This document describes the architecture, implementation decisions, and tradeoffs of the
Layer10 Grounded Memory System. Every statement maps directly to running, auditable code.

---

## 1. Public Corpus Selection

**Corpus**: `facebook/react` — GitHub Issues and Pull Requests.

**Source**: GitHub REST API v3 (`https://api.github.com/repos/facebook/react/issues`).
Each request uses `state=all&per_page=100` with pagination. Comments are fetched separately
via `GET /repos/facebook/react/issues/{number}/comments`.

**Why this corpus**: `facebook/react` mirrors organizational knowledge dynamics exactly.
It contains rich structured artifacts (labels, state transitions, assignees) alongside messy,
unstructured human communication: design debates, bug reports, multi-year decision reversals,
and cross-referenced PRs. Issues like #13991 ("Hooks + multiple instances of React") span
514 comments and years of real-world decisions — ideal for testing long-term memory.

**How to reproduce**:
```bash
# Clone, set GITHUB_TOKEN in .env, then:
python run.py --step download
# Downloads issues into corpus/raw/issue_XXXXX.json (222 issues currently)
```

The downloader (`corpus/downloader.py`) is idempotent: it skips files that already exist
on disk by checking the filename before making an API call.

---

## 2. Ontology / Schema Design

All types are defined in `schema/ontology.py`.

### Entity Types
| Type | Description |
|---|---|
| `Person` | GitHub user (login-normalized, `@`-stripped) |
| `Component` | React subsystem (`hooks`, `reconciler`, `reactdom`, `scheduler`, `concurrent`, `server-components`) |
| `Issue` | GitHub issue artifact |
| `PullRequest` | GitHub PR artifact |
| `Bug` | A reported defect |
| `Label` | Issue label (e.g. `Component: Hooks`, `Type: Discussion`) |
| `DesignProposal` | Proposed API or architecture decision |
| `Decision` | A resolved organizational decision |
| `Incident` | A regression or breakage reported in production |
| `Release` | A versioned release artifact |
| `Team` | An organizational team |
| `Project` | A broader project area |

### Claim Types
Organized into two categories:

**Participation** (connects people and artifacts):
- `AuthoredBy` — Issue/PR authored by Person
- `Commented` — Person commented on Issue/PR
- `LabeledWith` — Issue/PR tagged with Label
- `ReferencedPR` — Issue references a PullRequest

**Semantic** (organizational knowledge):
- `IssueReported`, `Affects`, `Fixes`, `DependsOn`, `RelatedTo`
- `DecisionMade`, `StatusChanged`, `OwnershipDeclared`
- `AssignedTo`, `WorksOn`, `ReleasePublished`, `IncidentDetected`

### Evidence Model

Every assertion must carry at least one `Evidence` object with **all** of:

| Field | Description | Example |
|---|---|---|
| `source_id` | Root artifact ID | `"issue-13991"` |
| `artifact_version_id` | Immutable content-hash version | `"issue-13991-v2"` |
| `url` | Live clickable link to source | `"https://github.com/facebook/react/issues/13991"` |
| `timestamp` | ISO event time | `"2018-10-27T00:34:08Z"` |
| `excerpt` | Exact verbatim quote | `"hooks can only be called inside the body..."` |
| `offset_start` | Character offset into source text | `300` |
| `offset_end` | Character offset end | `356` |
| `support_strength` | `explicit` / `inferred` / `weak` | `"explicit"` |
| `source_type` | Artifact category | `"issue"` |
| `confidence` | Extraction confidence | `0.95` |

**Grounding guarantee**: every returned context pack item can be traced back to an exact
character range in a specific version of a specific source artifact.

**Audit verification**:
- 656 evidence items across 12 extraction files
- 0 missing `url` · 0 missing `excerpt` · 0 missing `source_id` · 0 missing `source_type`

---

## 3. Structured Extraction Pipeline

**Model**: Groq Llama-4-Scout-17B (`meta-llama/llama-4-scout-17b-16e-instruct`). chosen for its massive 30K TPM free-tier limit and excellent JSON instruction following.

### Stage 1 — Agentic Triage Filter (`extraction/triage.py`)
Before touching the LLM, each issue is scored using a heuristic filter (regex patterns, bot detection, length thresholds). Mundane artifacts (one-liner "Same issue here!!!" comments, zero-body issues) are dropped. Only issues with sufficient signal pass through. This prevents noisy extractions from wasting tokens entirely.

### Stage 2 — Artifact Versioning (`extraction/run_tracker.py`)
Every artifact gets a `content_hash` (SHA-256 of body + comments). If the content hasn't
changed since the last extraction run, the artifact is skipped (strict idempotency). Every
run is logged to `data/runs/extraction_runs.json` with:
- `schema_version` (currently v2)
- `prompt_version` (hash of the system prompt)
- `model` (model ID string)
- `extracted_at` (system time)

### Stage 3 — LLM Extraction (`extraction/pipeline.py`)
The system prompt (`extraction/prompts.py`) instructs the LLM to:
1. Extract typed entities from the ontology
2. Form `Assertion` objects with a specific `claim_type`
3. Attach at least one `Evidence` item per assertion with an exact verbatim excerpt

A **batch prompt** formats 3 issues together, returning a `{"results": [...]}` array.
Each result is matched back to its `source_id`.

### Stage 4 — Validation & Critic Loop (`schema/validators.py`)
Pydantic validates the LLM JSON output against the full schema. On failure:
1. The error message is formatted into a `repair_prompt` with the exact validation error
2. The LLM is called again with this context (up to **3 retries**)
3. On final failure, the artifact is logged to `data/failed_extractions.json` for human review

### Stage 5 — Evidence Enrichment
After validation, the pipeline enriches each evidence item:
- `url` ← from the issue's `html_url`
- `source_id` ← `"issue-{number}"`
- `artifact_version_id` ← `"{source_id}-v{N}"` where N increments on content change
- `timestamp` ← issue or comment `created_at`
- `source_type` ← `"issue"` or `"pull_request"`

### Versioning & Backfill
When the ontology changes (new entity/claim types), stale extractions are identified by
comparing their logged `schema_version` against the current version. The backfill script
(`scripts/backfill_extraction.py`) re-routes only stale artifacts through the pipeline:
```bash
python scripts/backfill_extraction.py --from-schema-version 1 --to-schema-version 2
# Or force re-extract everything:
python scripts/backfill_extraction.py --all
```

---

## 4. Deduplication and Canonicalization

### 4a — Artifact Deduplication (`dedup/artifact_dedup.py`)
Before the LLM is invoked, each raw artifact is checked for duplication:
- **Exact dedup**: `content_hash` (SHA-256). If hash matches a previously processed
  artifact, it is skipped entirely.
- **Near-dedup**: SimHash (bit-level similarity). Catches email quoting chains, cross-posts,
  and issue comments that are 98% identical to a previous artifact.

### 4b — Entity Canonicalization (`dedup/entity_canon.py`)

**Data structure**: Union-Find (Disjoint Set Union) with path compression and union-by-rank.
This resolves aliases in near-constant time O(α) at query time.

**Normalization per type**:
- `Person` entities: lowercase + strip leading `@` → `brunolemos`, not `@BrunoLemos`
- `Component` entities: mapped through the **`COMPONENT_ALIASES` table** (deterministic, no
  ML): `usestate` → `hooks`, `react-dom` → `reactdom`, `the reconciler` → `reconciler`, etc.
  Falls back to stripping non-alphanumeric characters.

**Registration flow**:
1. `register_entity(entity)` is called for every extracted entity
2. Name is normalized → canonical ID is derived (`"component::hooks"`)
3. If a match exists in the alias registry → `_merge_into()` is called instead
4. All known aliases are registered in the Union-Find

**Merge ledger** (append-only, `data/entity_merges.json`):
Every merge appends an `EntityMergeRecord`:
```json
{
  "merge_id": "em_20260303_162545_d8e041",
  "canonical_id": "component::reactdom",
  "merged_entity_id": "component::react-dom",
  "reason": "Canonical ID match",
  "reversible": true,
  "event_type": "merge"
}
```

**Merge reversal** (append-only, never deletes):
`undo_merge(merge_id)` appends a `SplitEvent` and calls `UnionFind.split()` to detach the
merged entity, preserving full audit history.

**Current state**: 21,632 merge records on disk · 1,601 aliases registered · all reversible.

### 4c — Claim Deduplication (`graph/fact_factory.py`)

All assertions across all extraction files are passed through `FactFactory.form_facts()`:
- Groups assertions by `(claim_type, subject_id, object_id)`
- Forms one **Canonical Fact** per group
- Evidence from all matching assertions is merged and deduplicated
  (same `source_id + excerpt[:60]` → kept once)
- `confidence` = weighted average of all contributing assertion confidences
- `memory_strength` = `confidence + log(evidence_count) + authority_weight − decay_rate × age`

### 4d — Conflicts & Revisions

Claims carry a `ClaimStatus` enum: `active`, `superseded`, `retracted`, `uncertain`,
`redacted`, `ungrounded`.

When a newer assertion contradicts an older one (e.g., an issue is re-opened after being
closed), the older claim gets `status=superseded` and `valid_until` is set to the event
time of the newer assertion.

**Current state** is resolved as: `status == "active"` AND `valid_until is None`.
**Historical state** is queried via `TemporalResolver.get_current_state(claims, as_of="2024-01-01")`.

---

## 5. Memory Graph Design

### Storage Backend

The graph uses a `GraphStorageBackend` interface (`graph/memory_graph.py`):
- **Storage**: The main graph is powered by a cloud Neo4j AuraDB instance. Data is pushed natively, but the entire graph is also serialized to `data/graph.json` — zero-config, allowing D3.js UI visualization directly from static files locally. The system auto-detects Neo4j availability on startup.

### Node Pattern: Reified Event Nodes

Claims are stored as **first-class nodes** (not just edges), following RDF reification:

```
Entity Node (Person/Component/Issue...)
      │
      │ [subject edge]
      ▼
 Event Node (Canonical Claim)  ← stores evidence, confidence, valid_from/until
      │
      │ [object edge]
      ▼
Entity Node (another entity)
```

Entity node key format: `{Type}::{type}::{name}` → e.g. `Person::person::brunolemos`
Event node key format: `Event::fact::{claim_type}::{hash8}` → e.g. `Event::fact::issuereported::4473b304`

### Temporal Model (Bitemporal)

| Dimension | Field | Meaning |
|---|---|---|
| Event time | `valid_from` | When the real-world action happened |
| Event time | `valid_until` | When it stopped being true (null = still current) |
| System time | `extracted_at` | When the pipeline ingested it |

**"Current" determination**: `status == "active"` AND `valid_until is None`.

`TemporalResolver` provides:
- `is_current(claim_data)` — is this claim true right now?
- `is_valid_at(claim_data, timestamp)` — was it true at a given point in time?
- `get_current_state(claims, as_of)` — time-travel queries

### Updates: Idempotency
- `content_hash` matching prevents re-ingestion of unchanged content
- `_ingested_hashes` set in `MemoryGraph` deduplicates within a single run
- On re-ingestion, only new `ArtifactVersion` entries differ; historical claims remain intact

### Redaction Handling (`handle_redaction()`)

When a source artifact is deleted or redacted:
- Claims grounded **exclusively** in that source → `status=redacted`, `valid_until=<now>`
- Claims with **multi-source** evidence → redacted source entry removed, claim stays active

**Verified live**: `handle_redaction("issue-13991")` correctly invalidated 20 claims,
setting `status=redacted` and `valid_until=2026-03-06T00:00:00Z`.

### Permissions (Conceptual)

Every `Claim` and `Evidence` node carries `source_id` pointing to its root artifact.
At query time, a Mandatory Inclusion Filter wraps every graph traversal:

```
WHERE evidence.source_id IN [user_authorized_sources]
```

Claims supported only by unauthorized sources are pruned from the result set before
returning, ensuring zero memory leakage across permission boundaries. In a Neo4j
deployment, this maps to:
```cypher
MATCH (u:User {id: $uid})-[:HAS_ACCESS]->(s:Source)<-[:GROUNDED_IN]-(c:Claim)
```

### Observability via `Store Health Check`

To prevent memory degradation, the system implements a proactive `store.health_check()` suite. This provides the following critical metrics for every ingestion run:

1.  **Grounding Quality**: `claims_without_evidence` (Crucial: identifies ungrounded hallucinations).
2.  **Extraction Quality**: `avg_confidence` (Average LLM confidence per assertion).
3.  **Graph Connectivity**: `orphan_nodes` (Identifies entities that aren't linked to any events).
4.  **Distribution**: `confidence_distribution` (Breakdown of fact certainty across the store).

**Current Audit State**: 386 nodes · 313 edges · **Avg Confidence 0.942** · **0 Ungrounded Claims**.

---

## 6. Retrieval and Grounding

### Index Building (`retrieval/search.py`)

Two complementary indexes are built over the graph on startup:

- **BM25 (Okapi)**: Keyword index over entity names, aliases, claim properties, and
  evidence excerpts.
- **FAISS** (vector): Sentence embeddings (`all-MiniLM-L6-v2`, 384-dim, cosine similarity)
  over entity + claim text. Quantized to `IndexFlatL2` for zero-config local operation.

### Hybrid Search

```
final_score = 0.6 × faiss_score + 0.4 × bm25_score
```

Both scores are normalized to [0, 1] before combining. Hybrid search consistently
outperforms either alone on organizational queries with mixed keyword + semantic content.

### Aggregation Without Exploding

Graph expansion from search hits is capped at **depth 2**. The candidate pool is pruned by:
1. `memory_strength` score (confidence + evidence weight + authority)
2. Recency (`valid_until` checks — expired claims ranked lower)
3. `max_evidence` cap per claim to prevent a single high-evidence claim from dominating

### Citation Format

Every evidence item in a context pack is formatted as:
```
[issue-13991] (https://github.com/facebook/react/issues/13991) @ 2018-10-27T00:34:08Z
```

### Conflict Handling (`context_pack.py`)

The `ContextPackBuilder` runs `_find_conflicts()` before returning. Two conflict types:
- `"superseded"`: A claim exists in both `active` and `superseded` states for the same
  subject/object — surfaces "it used to be true" alongside the current truth.
- `"conflicting"`: Two `active` claims assert contradictory facts — both returned with
  timestamps so the evaluator can follow the evidence chain.

Conflicts are never hidden; they are surfaced as a dedicated `conflicts` array in the
context pack JSON.

### Context Pack Output

```json
{
  "question": "Who is brunolemos and what did they propose?",
  "entities": [...],
  "claims": [{ "type": "IssueReported", "confidence": 0.94, "is_current": true, "evidence_count": 3 }],
  "evidence": [{ "source_id": "issue-13991", "url": "...", "excerpt": "...", "citation": "[issue-13991] (...) @ 2018-10-27", "source_type": "issue" }],
  "conflicts": [],
  "summary": "Found 2 entities and 3 claims. Backed by 8 evidence items."
}
```

**4 context packs** are pre-generated in `data/context_packs/` covering foundational React decisions, specifically answering the questions provided in the assignment brief.

---

## 7. Visualization Layer

A lightweight web UI is provided to make the extracted memory explorable. It runs locally and connects directly to the graph output.

### Graph View
- **Interactive Network**: Entities are rendered as nodes, and canonical claims as the relationships connecting them.
- **Dynamic Filtering**: Users can filter the visualized graph by:
  - **Time**: A temporal slider allows time-traveling through the graph, filtering claims by `valid_from` and `valid_until`.
  - **Type**: Interactive toggles allow showing/hiding specific entity types (e.g., `Person`, `Component`) and claim types.
  - **Confidence**: A slider filters out relationships below a user-defined confidence threshold.

### Evidence Panel
- Clicking any relationship or claim node opens a dedicated **Evidence Panel**.
- This panel displays the exact verbatim `excerpt` for every piece of evidence supporting the claim.
- Source metadata (`source_id`, `timestamp`, `confidence`, `source_type`) and live `url`s are exposed, allowing real-time auditing of the LLM's extraction.

### Inspecting Duplicates and Merges
- The UI surfaces the canonicalization engine's decisions. When selecting a canonical entity, its merged aliases are displayed.
- For merged claims, the UI shows the aggregated `evidence_count` and lists all distinct source excerpts that support the deduplicated fact.

---

## 8. Long-Term Correctness

| Scenario | Mechanism |
|---|---|
| Issue closed, re-opened | New assertion → older claim gets `status=superseded`, older `valid_until` set |
| Source deleted/redacted | `handle_redaction()` cascades bitemporal invalidation |
| Ontology changes | `backfill_extraction.py` re-routes stale artifacts through new schema |
| Bad merge detected | `undo_merge(merge_id)` appends SplitEvent, Union-Find detached |
| Extraction noise | Triage filter + confidence gate + critic loop block noisy inputs |

---

## 9. Adaptation to Layer10 Target Environment

### 9.1 Unstructured + Structured Fusion
The `Person` entity type expands to `OrganizationalIdentity`. A user's Slack ID (`U1234`),
Jira reporter ID, and email (`jane@layer10.com`) all resolve via `EntityCanonicalizer` to
a single Canonical Node. This ensures a Jira state change (structured) and a Slack
agreement (unstructured) land on the same conceptual subgraph.

The ontology gains cross-platform link types:
- `DiscussedIn` — links a Jira ticket to the Slack thread that discussed it
- `DecidedVia` — links a decision to the chat message or email that made it

### 9.2 Long-Term Memory vs. Ephemeral Context
Not all extractions become durable memory. Slack messages start as "Ephemeral Context"
with steep decay in the `memory_strength` formula. They only cross into "Durable Memory"
if they are:
- Cross-referenced by a structured system (Jira status change referencing the thread)
- Repeated across multiple sources (high `evidence_count`)
- Manually promoted via a human review hook

This prevents the graph from accumulating thousands of low-value chat observations.

### 9.3 Grounding, Provenance & Safe Deletions
Every claim remains linked to its source artifact ID. If a Slack message is redacted
(enterprise retention policy), the system detects the webhook event, finds the `content_hash`,
and calls `handle_redaction(source_id)` — the same cascading bitemporal invalidation
already implemented and verified in the current system.

### 9.4 Permissions (Source-Constrained Retrieval)
Memory retrieval is constrained by source access. Every graph traversal wraps a predicate:
`WHERE evidence.source_id IN [user_authorized_sources]`. A user in a Jira project
but not in a private Slack channel cannot retrieve claims grounded in that channel,
even if those claims logically relate to their project.

### 9.5 Operational Reality

| Concern | Approach |
|---|---|
| **Cost** | Heuristic regex/length pre-filter before Llama call; only substantive messages hit the LLM. 30K TPM via Groq provides massive headroom. |
| **Scale** | Batch ingestion replaced by streaming Kafka/webhook events |
| **Incremental updates** | Idempotent `content_hash` matching already implemented; plug into event stream |
| **Regression testing** | Golden dataset + `eval.py` CI gate; any prompt/ontology change runs before deploy |
| **Dedup stability** | Merge ledger + SplitEvent audit trail allows regression tracing of any canonicalization decision |

---

## 10. Architectural Tradeoffs

| Tradeoff | Decision | Reasoning |
|---|---|---|
| **Recall vs. Precision** | Graph traversal capped at depth 2 | Eliminates hallucinated context at the cost of tangential links |
| **LLM dependency vs. Determinism** | LLM only at ingestion; retrieval is fully deterministic BM25+FAISS+graph | Non-determinism confined to one step; results are reproducible |
| **Latency vs. Correctness** | Bitemporal ledgers and content_hash add ingestion overhead | Writing slowly is cheaper than reading a corrupted graph |
| **Entity matching: ML vs. Deterministic** | Deterministic alias table + string normalization (no embedding clustering) | 100% reproducible, auditable, no model dependency at query time |
| **Storage: Neo4j AuraDB** | Cloud instance via native Python Driver | Distributed production infrastructure. *Fault Tolerance*: If the cloud instance is unreachable due to network constraints or SSL/VPN termination, the `GraphStorageBackend` gracefully falls back to an in-memory JSON serialization to guarantee uninterrupted ingestion. |
| **Free LLM vs. Premium** | Groq Llama-4-Scout free tier at 30 RPM / 30K TPM | Fully operational within assignment constraints; speed and context window exceed standard free-tier model limits. |

---

## 11. Reproducibility

**End-to-end run**:
```bash
# 1. Copy .env.example to .env and add GROQ_API_KEY + GITHUB_TOKEN
cp .env.example .env

# 2. Run all steps
python run.py                         # download → extract → graph → query

# Or step by step:
python run.py --step download         # Fetch corpus
python run.py --step extract          # LLM extraction (uses API key)
python run.py --step graph            # Build memory graph
python run.py --step query            # Generate context packs
python run.py --step serve            # Launch visualization UI

# Backfill after schema changes:
python scripts/backfill_extraction.py --all
```

**Pre-built outputs** (no API key required to evaluate these):
- `data/graph.json` — 386 nodes, 313 edges, 0 claims without evidence
- `data/extractions/` — 12 extraction files
- `data/context_packs/` — 4 pre-generated context packs
- `data/entity_merges.json` — 21,632 merge records
- `data/alias_registry.json` — 1,601 aliases + Union-Find state

---

*System built with Python 3.12 · Neo4j Python Driver · FAISS · Pydantic v2 · Groq Llama-4-Scout*
