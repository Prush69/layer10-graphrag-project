"""
End-to-end runner for the Layer10 Grounded Long-Term Memory system.

Orchestrates: download → extract → dedup → build graph → generate examples → launch UI
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import config


def step_download(args):
    """Step 1: Download corpus from GitHub."""
    print("\n" + "="*60)
    print("STEP 1: Downloading Corpus")
    print("="*60)

    from corpus.downloader import download_corpus
    count = download_corpus(
        repo=args.repo or config.GITHUB_REPO,
        max_issues=args.max_issues or config.MAX_ISSUES
    )
    print(f"[OK] {count} issues available in {config.RAW_DATA_DIR}")


def step_extract(args):
    """Step 2: Run structured extraction."""
    print("\n" + "="*60)
    print("STEP 2: Structured Extraction")
    print("="*60)

    from extraction.pipeline import ExtractionPipeline
    pipeline = ExtractionPipeline()
    results = pipeline.run(limit=args.limit, force=args.force)
    print(f"[OK] Extracted {len(results)} issues")
    return results


def _generate_participation_claims(extraction_file: Path, raw_dir: Path) -> list:
    """
    Generate AuthoredBy, Commented, LabeledWith assertions from raw issue metadata.
    These don't require the LLM — they are deterministic from the structured fields.
    """
    import hashlib
    from schema.ontology import (
        Assertion, AssertionType, ClaimType, Evidence, SupportStrength, Entity, EntityType
    )
    from datetime import datetime

    issue_num = extraction_file.stem.replace("extraction_", "")
    raw_path = raw_dir / f"issue_{issue_num}.json"
    if not raw_path.exists():
        return [], []

    with open(raw_path, encoding="utf-8") as f:
        raw = json.load(f)

    source_id = f"issue-{issue_num}"
    issue = raw.get("issue", {})
    comments = raw.get("comments", [])
    labels = [lb.get("name", "") for lb in issue.get("labels", [])]
    issue_url = issue.get("html_url", "")
    issue_created = issue.get("created_at", "")
    issue_title = issue.get("title", issue_num)
    issue_author = issue.get("user", {}).get("login", "")

    extra_assertions = []
    extra_entities = []

    def make_evidence(excerpt, url, ts):
        return Evidence(
            artifact_version_id=f"{source_id}-v1",
            source_id=source_id,
            url=url,
            timestamp=ts,
            excerpt=excerpt[:200] if excerpt else source_id,
            offset_start=0,
            offset_end=len(excerpt[:200]) if excerpt else 0,
            confidence=1.0,
            support_strength=SupportStrength.EXPLICIT,
            source_type="issue",
        )

    def make_assertion(claim_type, subject_id, object_id, asserted_by, ev, ts=None):
        aid = hashlib.md5(f"{claim_type}::{subject_id}::{object_id}::{source_id}".encode()).hexdigest()[:12]
        return Assertion(
            id=f"assertion::{aid}",
            artifact_version_id=f"{source_id}-v1",
            asserted_by=asserted_by or "system",
            type=AssertionType.OBSERVATION,
            claim_type=claim_type,
            subject_id=subject_id,
            object_id=object_id,
            confidence=1.0,
            timestamp=ts or issue_created,
            evidence=[ev],
        )

    issue_entity_id = f"issue::{source_id}"
    issue_entity = Entity(
        id=issue_entity_id,
        type=EntityType.ISSUE,
        name=source_id,
        aliases=[issue_title],
        properties={"state": issue.get("state", ""), "author": issue_author, "created_at": issue_created},
    )
    extra_entities.append(issue_entity)

    # AuthoredBy: Issue → author Person
    if issue_author:
        author_ev = make_evidence(f"Author: {issue_author}", issue_url, issue_created)
        extra_assertions.append(make_assertion(
            ClaimType.AUTHORED_BY, issue_entity_id, f"person::{issue_author.lower()}",
            issue_author, author_ev
        ))
        extra_entities.append(Entity(
            id=f"person::{issue_author.lower()}", type=EntityType.PERSON,
            name=issue_author, aliases=[]
        ))

    # Commented: each commenter Person → Issue
    seen_commenters = set()
    for comment in comments[:15]:
        commenter = comment.get("user", {}).get("login", "")
        if commenter and commenter not in seen_commenters:
            seen_commenters.add(commenter)
            c_body = (comment.get("body", "") or "")[:200]
            c_url = comment.get("html_url", issue_url)
            c_ts = comment.get("created_at", issue_created)
            c_ev = make_evidence(c_body or f"{commenter} commented", c_url, c_ts)
            extra_assertions.append(make_assertion(
                ClaimType.COMMENTED, f"person::{commenter.lower()}", issue_entity_id,
                commenter, c_ev, c_ts
            ))
            extra_entities.append(Entity(
                id=f"person::{commenter.lower()}", type=EntityType.PERSON,
                name=commenter, aliases=[]
            ))

    # LabeledWith: Issue → each Label
    for label_name in labels:
        label_id = f"label::{label_name.lower()}"
        lev = make_evidence(f"Label: {label_name}", issue_url, issue_created)
        extra_assertions.append(make_assertion(
            ClaimType.LABELED_WITH, issue_entity_id, label_id, "system", lev
        ))
        extra_entities.append(Entity(
            id=label_id, type=EntityType.LABEL, name=label_name, aliases=[]
        ))

    return extra_assertions, extra_entities


def step_dedup(args):
    """Step 3: Run deduplication and canonicalization (Canonical Fact Formation)."""
    print("\n" + "="*60)
    print("STEP 3: Canonical Fact Formation")
    print("="*60)

    from schema.ontology import ExtractionResult
    from dedup.entity_canon import EntityCanonicalizer
    from graph.fact_factory import FactFactory

    # Load extraction results
    extraction_dir = config.EXTRACTION_DIR
    extraction_files = sorted(extraction_dir.glob("extraction_*.json"))

    if not extraction_files:
        print("No extraction results found. Run extraction first.")
        return [], []

    print(f"Processing {len(extraction_files)} extraction results...")

    canonicalizer = EntityCanonicalizer()
    fact_factory = FactFactory()

    all_entities = []
    all_assertions = []

    for ef in extraction_files:
        with open(ef, "r", encoding="utf-8") as f:
            data = json.load(f)

        result = ExtractionResult(**data)

        # Register entities (canonicalization)
        for entity in result.entities:
            canonical = canonicalizer.register_entity(entity)
            all_entities.append(canonical)

        # Track assertions and resolve their entity references to canonical IDs
        for assertion in result.assertions:
            canon_subj = canonicalizer.get_canonical_id(assertion.subject_id)
            if canon_subj:
                assertion.subject_id = canon_subj

            if assertion.object_id:
                canon_obj = canonicalizer.get_canonical_id(assertion.object_id)
                if canon_obj:
                    assertion.object_id = canon_obj

            all_assertions.append(assertion)

        # Retroactive participation claims (AuthoredBy, Commented, LabeledWith)
        part_assertions, part_entities = _generate_participation_claims(ef, config.RAW_DATA_DIR)
        for entity in part_entities:
            canonical = canonicalizer.register_entity(entity)
            all_entities.append(canonical)
        all_assertions.extend(part_assertions)

    # Canonical Fact Formation (Aggregation)
    print(f"  Aggregating {len(all_assertions)} assertions into facts...")
    all_claims = fact_factory.form_facts(all_assertions)
    print(f"  Formed {len(all_claims)} canonical facts")

    # Deduplicate entities
    unique_entities = list({e.id: e for e in all_entities}.values())
    print(f"  Unique entities: {len(unique_entities)}")

    print(f"[OK] Fact formation complete: {len(unique_entities)} entities, {len(all_claims)} facts")
    return unique_entities, all_claims


def step_graph(args):
    """Step 4: Build memory graph."""
    print("\n" + "="*60)
    print("STEP 4: Building Memory Graph")
    print("="*60)

    from graph.store import GraphStore

    store = GraphStore()
    graph = store.load()

    entities, claims = step_dedup(args)

    # Add entities
    for entity in entities:
        graph.add_entity(entity)

    # Add claims
    for claim in claims:
        graph.add_claim(claim)

    # Save graph (implicit for Postgres, explicit for NetworkX)
    store.save(graph)

    # Health check
    health = store.health_check(graph)
    print(f"[OK] Graph built: {health['stats']['total_nodes']} nodes, {health['stats']['total_edges']} edges")
    print(f"  Avg confidence: {health['avg_confidence']}")
    print(f"  Evidence coverage: {health['stats']['total_edges'] - health['claims_without_evidence']}/{health['stats']['total_edges']} claims have evidence")

    return graph


def step_query(args):
    """Step 5: Run example queries."""
    print("\n" + "="*60)
    print("STEP 5: Generating Example Context Packs")
    print("="*60)

    from graph.memory_graph import MemoryGraph
    from graph.store import GraphStore
    from retrieval.search import HybridSearch
    from retrieval.context_pack import ContextPackBuilder

    store = GraphStore()
    graph = store.load()

    search = HybridSearch(graph)
    print("Building search index...")
    search.build_index()

    builder = ContextPackBuilder(graph)

    # Example questions
    questions = [
        args.question if args.question else None,
        "Why was Context API deprecated?",
        "Who proposed removing legacy context?",
        "What decision replaced Context API?",
        "What are the most discussed components in React?",
    ]

    questions = [q for q in questions if q]

    for question in questions[:5]:
        print(f"\n  Q: {question}")
        results = search.search(question, top_k=15)
        
            
        pack = builder.build(results, question)

        print(f"  -> {len(pack.entities)} entities, {len(pack.claims)} claims, {len(pack.evidence)} evidence items")
        if pack.conflicts:
            print(f"  -> [!] {len(pack.conflicts)} conflicts")

        builder.save_pack(pack)

    print(f"\n[OK] Context packs saved to {config.CONTEXT_PACKS_DIR}")


def step_serve(args):
    """Step 6: Launch visualization server."""
    print("\n" + "="*60)
    print("STEP 6: Launching Visualization")
    print("="*60)

    from visualization.app import create_app
    app = create_app()

    print(f"\n[*] Open http://localhost:{config.FLASK_PORT} in your browser")
    print("   Press Ctrl+C to stop the server\n")

    app.run(
        host=config.FLASK_HOST,
        port=config.FLASK_PORT,
        debug=config.FLASK_DEBUG
    )


def main():
    parser = argparse.ArgumentParser(
        description="Layer10 Grounded Long-Term Memory - End-to-End Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Steps:
  download    Download GitHub issues corpus
  extract     Run structured extraction via LLM
  dedup       Run deduplication and canonicalization
  graph       Build the memory graph
  query       Generate example context packs
  serve       Launch the visualization web UI
  all         Run all steps end-to-end (default)

Examples:
  python run.py                     # Run all steps
  python run.py --step extract --limit 5
  python run.py --step serve
  python run.py --step query --question "What issues affect hooks?"
"""
    )

    parser.add_argument("--step", default="all",
                        choices=["download", "extract", "dedup", "graph", "query", "serve", "all"],
                        help="Which step to run (default: all)")
    parser.add_argument("--repo", default=None, help="GitHub repo (owner/name)")
    parser.add_argument("--max-issues", type=int, default=None, help="Max issues to download")
    parser.add_argument("--limit", type=int, default=None, help="Limit extraction to N issues")
    parser.add_argument("--force", action="store_true", help="Force re-extraction")
    parser.add_argument("--question", default=None, help="Custom question for query step")

    args = parser.parse_args()

    print("=" * 60)
    print("   Layer10 Grounded Long-Term Memory System")
    print("   Structured Extraction > Dedup > Memory Graph")
    print("=" * 60)

    steps = {
        "download": step_download,
        "extract": step_extract,
        "dedup": step_dedup,
        "graph": step_graph,
        "query": step_query,
        "serve": step_serve,
    }

    if args.step == "all":
        step_download(args)
        step_extract(args)
        step_graph(args)  # This calls step_dedup internally
        step_query(args)
        step_serve(args)
    else:
        steps[args.step](args)


if __name__ == "__main__":
    main()
