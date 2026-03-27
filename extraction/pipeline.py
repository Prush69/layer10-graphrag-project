"""
Main extraction pipeline orchestrator.

Processes GitHub issue data through the LLM for structured extraction,
validates outputs, and saves results with versioning.

OPTIMIZED FOR FREE TIER: 5 RPM, 250K TPM, 20 RPD.
Strategy: Concurrent batches of 3 issues with 13s stagger = 5 RPM safe.
21 issues processed in ~2.3 minutes using 7/20 RPD.

Features:
- Concurrent Batch Extraction: 3 issues/batch, fired in parallel with 13s stagger
- Self-Correction/Critic Loop: feeds validation errors back to the model
- Integrity Guard: failed extractions go to observability queue
- Quality Gates: confidence threshold filtering
- Artifact Versioning: tracks content changes for re-extraction
"""
import json
import time
import hashlib
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from extraction.llm_client import GroqClient
from extraction.prompts import build_extraction_prompt, EXTRACTION_SYSTEM_PROMPT
from extraction.run_tracker import RunRegistry
from extraction.triage import TriageFilter
from schema.validators import (
    validate_extraction_result,
    verify_evidence_offsets,
    generate_entity_id,
    generate_claim_id,
)
from schema.ontology import EntityType, ExtractionResult


# Maximum repair attempts before flagging as failed_extraction
MAX_CRITIC_RETRIES = 3

# Pull rate limit settings from config
BATCH_SIZE = config.EXTRACTION_BATCH_SIZE
STAGGER_SECONDS = config.GROQ_RATE_LIMIT_DELAY


class FailedExtractionQueue:
    """Observability queue for extractions that fail after all retry attempts."""

    def __init__(self):
        self.queue_path = config.DATA_DIR / "failed_extractions.json"
        self.queue: list[dict] = []
        self._load()

    def _load(self):
        if self.queue_path.exists():
            with open(self.queue_path, "r") as f:
                self.queue = json.load(f)

    def _save(self):
        self.queue_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.queue_path, "w") as f:
            json.dump(self.queue, f, indent=2)

    def add(self, source_id: str, issue_path: str, error: str, attempts: int):
        entry = {
            "source_id": source_id,
            "issue_path": str(issue_path),
            "error": str(error),
            "attempts": attempts,
            "status": "failed_extraction",
            "flagged_at": datetime.utcnow().isoformat(),
            "reviewed": False,
        }
        self.queue.append(entry)
        self._save()
        print(f"  [!] Flagged as failed_extraction: {source_id} ({error[:80]})")

    def get_pending(self) -> list[dict]:
        return [e for e in self.queue if not e.get("reviewed")]

    def mark_reviewed(self, source_id: str):
        for entry in self.queue:
            if entry["source_id"] == source_id:
                entry["reviewed"] = True
        self._save()


class ArtifactVersioner:
    """Minimalist artifact versioning tracker."""
    def __init__(self, path: Path):
        self.path = path
        self.hashes = {}
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    self.hashes = json.load(f)
            except: pass

    def get_version(self, artifact_id: str, new_hash: str) -> int:
        if artifact_id not in self.hashes:
            self.hashes[artifact_id] = [new_hash]
            self._save()
            return 1
        versions = self.hashes[artifact_id]
        if new_hash in versions:
            return versions.index(new_hash) + 1
        versions.append(new_hash)
        self._save()
        return len(versions)

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.hashes, f)


class ExtractionPipeline:
    """Orchestrates structured extraction from raw corpus data."""

    def __init__(self, api_key: str = None):
        # We use a single shared client instance for the process
        self.client = GroqClient(api_key=api_key)
        self.run_registry = RunRegistry()
        self.versioner = ArtifactVersioner(config.DATA_DIR / "artifact_hashes.json")
        self.failed_queue = FailedExtractionQueue()
        self.triage = TriageFilter()
        self.results_dir = config.EXTRACTION_DIR
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.api_calls_made = 0

    def _generate_artifact_version(self, artifact_id: str, content: str, metadata: dict) -> tuple[str, int]:
        """Generate a versioned artifact and detect if it's an edit."""
        checksum = hashlib.sha256(content.encode()).hexdigest()
        version_num = self.versioner.get_version(artifact_id, checksum)
        version_id = f"{artifact_id}-v{version_num}"
        return version_id, version_num

    def _extract_single_batch(self, batch_num: int, batch_files: list[Path]) -> list[ExtractionResult]:
        """
        Extract a batch of issues in a single API call. Thread-safe.
        """
        batch_data = []
        batch_context = {}

        for issue_path in batch_files:
            with open(issue_path, "r", encoding="utf-8") as f:
                issue_data = json.load(f)

            issue_number = issue_data.get("issue", {}).get("number", "unknown")
            artifact_id = f"issue-{issue_number}"

            # Artifact Versioning
            raw_body = issue_data.get("issue", {}).get("body", "") or ""
            comment_text = "\n".join([c.get("body", "") for c in issue_data.get("comments", [])])
            full_content = f"{raw_body}\n\nMODS:\n{comment_text}"
            version_id, version_num = self._generate_artifact_version(artifact_id, full_content, {})

            # Triage
            raw_comments = issue_data.get("comments", [])
            signal_comments = self.triage.filter_comments(raw_comments)
            issue_data["comments"] = signal_comments

            batch_data.append(issue_data)
            batch_context[artifact_id] = {
                "version_id": version_id,
                "url": issue_data.get("issue", {}).get("html_url", ""),
                "timestamp": issue_data.get("issue", {}).get("created_at", ""),
            }

        prompt = build_extraction_prompt(batch_data)
        ids = [f"issue-{Path(f).stem.split('_')[1]}" for f in batch_files]
        print(f"  [SEND] Batch {batch_num}: {ids}")

        # Self-Correction/Critic Loop
        last_error = None
        raw_result = None
        for attempt in range(MAX_CRITIC_RETRIES):
            try:
                if attempt == 0 or raw_result is None:
                    raw_result = self.client.extract(prompt)
                else:
                    repair_prompt = self._build_repair_prompt(prompt, raw_result, last_error)
                    raw_result = self.client.extract(repair_prompt)

                # Handle both batch and single-issue responses
                if "results" in raw_result:
                    result_list = raw_result["results"]
                else:
                    result_list = [raw_result]

                successful_results = []
                retry_needed = False

                for i, issue_res in enumerate(result_list):
                    source_id = issue_res.get("source_id", "unknown")
                    if source_id == "unknown" and len(batch_files) == 1:
                        # Recover from filename
                        source_id = f"issue-{batch_files[0].stem.split('_')[1]}"
                    
                    issue_res["source_id"] = source_id
                    issue_res["model"] = self.client.model_name
                    issue_res["raw_text_length"] = len(prompt)

                    validated, errors = validate_extraction_result(issue_res)

                    if errors:
                        severe = [e for e in errors if any(kw in e.lower() for kw in ["required", "invalid", "missing"])]
                        if severe and attempt < MAX_CRITIC_RETRIES - 1:
                            last_error = f"Error in {source_id}: " + "; ".join(severe[:3])
                            retry_needed = True
                            break

                    for entity in validated.entities:
                        if not entity.id:
                            entity.id = generate_entity_id(entity.type, entity.name)

                    ctx = batch_context.get(source_id, {})
                    for assertion in validated.assertions:
                        if not assertion.id:
                            assertion.id = f"assertion::{hashlib.md5(str(assertion).encode()).hexdigest()[:8]}"
                        for ev in assertion.evidence:
                            ev.artifact_version_id = ctx.get("version_id", "unknown-v1")
                            ev.source_id = source_id
                            ev.url = ctx.get("url", "")
                            ev.timestamp = ctx.get("timestamp", "")
                            ev.source_type = "issue" if "issue" in source_id else "unknown"

                    successful_results.append(validated)

                if retry_needed:
                    continue

                return successful_results

            except (json.JSONDecodeError, ValueError) as e:
                last_error = str(e)
                if attempt < MAX_CRITIC_RETRIES - 1:
                    print(f"  Batch {batch_num}: Attempt {attempt+1} - {type(e).__name__}, retrying...")
                    continue
                else:
                    raise

        raise ValueError(f"Extraction failed after {MAX_CRITIC_RETRIES} attempts")

    def _extract_and_save_batch(self, batch_num: int, batch_files: list[Path], force: bool) -> tuple[list[ExtractionResult], int]:
        """
        Extract + save a batch. Returns (results, error_count). Thread-safe.
        """
        # Filter out already-extracted files
        files_to_process = []
        cached = []
        for issue_path in batch_files:
            issue_num = issue_path.stem.split("_")[1]
            result_path = self.results_dir / f"extraction_{issue_num}.json"
            if result_path.exists() and not force:
                with open(result_path, "r", encoding="utf-8") as f:
                    cached.append(ExtractionResult(**json.load(f)))
            else:
                files_to_process.append(issue_path)

        if not files_to_process:
            return cached, 0

        try:
            results = self._extract_single_batch(batch_num, files_to_process)

            for result in results:
                # Quality gate
                original = len(result.assertions)
                result.assertions = [a for a in result.assertions if a.confidence >= config.CONFIDENCE_THRESHOLD]
                removed = original - len(result.assertions)
                if removed > 0:
                    print(f"  Quality gate: removed {removed} low-confidence assertions from {result.source_id}")

                # Save
                issue_num = result.source_id.split("-")[1] if "-" in result.source_id else "unknown"
                result_path = self.results_dir / f"extraction_{issue_num}.json"
                with open(result_path, "w", encoding="utf-8") as f:
                    json.dump(result.model_dump(), f, indent=2, ensure_ascii=False)

            return cached + results, 0

        except Exception as e:
            for issue_path in files_to_process:
                issue_num = issue_path.stem.split("_")[1]
                self.failed_queue.add(
                    source_id=f"issue-{issue_num}",
                    issue_path=str(issue_path),
                    error=str(e),
                    attempts=MAX_CRITIC_RETRIES,
                )
            return cached, len(files_to_process)

    def _build_repair_prompt(self, original_prompt: str, failed_result: dict, error: str) -> str:
        return f"""{original_prompt}

--- REPAIR INSTRUCTIONS ---
Previous output failed validation:

```json
{json.dumps(failed_result, indent=2, default=str)[:3000]}
```

Error: {error}

Fix the output. Ensure all required fields are present and types match the schema.
"""

    def _verify_offsets(self, result: ExtractionResult, source_text: str):
        if not source_text:
            return
        stats = verify_evidence_offsets(result, source_text)
        if stats["total"] > 0:
            verified_pct = (stats["verified"] + stats["recovered"]) / stats["total"] * 100
            print(f"  Offset verification: {stats['verified']} verified, "
                  f"{stats['recovered']} recovered, {stats['failed']} failed "
                  f"({verified_pct:.0f}% grounded)")

    def filter_low_confidence(self, result: ExtractionResult) -> ExtractionResult:
        filtered = [a for a in result.assertions if a.confidence >= config.CONFIDENCE_THRESHOLD]
        removed = len(result.assertions) - len(filtered)
        if removed > 0:
            print(f"  Quality gate: removed {removed} low-confidence assertions")
        result.assertions = filtered
        return result

    def run(self, limit: int = None, force: bool = False) -> list[ExtractionResult]:
        """
        Run extraction with concurrent batch processing.

        Fires multiple batches in parallel with staggered starts
        to stay within 5 RPM. Each batch contains BATCH_SIZE issues.
        """
        raw_dir = config.RAW_DATA_DIR
        issue_files = sorted(raw_dir.glob("issue_*.json"))

        if not issue_files:
            print("No raw issue files found. Run the corpus downloader first.")
            return []

        if limit:
            issue_files = issue_files[:limit]

        # Split into batches
        batches = [issue_files[i:i + BATCH_SIZE] for i in range(0, len(issue_files), BATCH_SIZE)]
        num_batches = len(batches)

        print(f"\n{'='*60}")
        print(f"EXTRACTION PLAN")
        print(f"{'='*60}")
        print(f"  Issues: {len(issue_files)}")
        print(f"  Batch size: {BATCH_SIZE} issues/request")
        print(f"  Batches: {num_batches}")
        print(f"  RPD cost: {num_batches}/1000")
        print(f"  Mode: Concurrent ({STAGGER_SECONDS}s stagger to respect 30K TPM limit)")
        print(f"{'='*60}\n")

        # Start run tracking
        run = self.run_registry.start_run(
            model=self.client.model_name,
            prompt_version="v3.0-ideal"
        )

        start_time = time.time()
        all_results = []
        total_errors = 0

        # Fire all batches concurrently with stagger
        with ThreadPoolExecutor(max_workers=num_batches) as executor:
            futures = {}
            for i, batch in enumerate(batches):
                if i > 0:
                    time.sleep(STAGGER_SECONDS)
                future = executor.submit(self._extract_and_save_batch, i + 1, batch, force)
                futures[future] = i + 1
                elapsed = time.time() - start_time
                print(f"  [FIRED] Batch {i+1}/{num_batches} at t={elapsed:.0f}s")

            print(f"\nAll {num_batches} requests sent. Waiting for responses...\n")

            for future in as_completed(futures):
                batch_num = futures[future]
                try:
                    results, errors = future.result()
                    all_results.extend(results)
                    total_errors += errors
                    total_e = sum(len(r.entities) for r in results)
                    total_a = sum(len(r.assertions) for r in results)
                    elapsed = time.time() - start_time
                    print(f"  [DONE] Batch {batch_num}: {len(results)} issues, "
                          f"{total_e} entities, {total_a} assertions ({elapsed:.0f}s)")
                except Exception as e:
                    total_errors += 1
                    elapsed = time.time() - start_time
                    print(f"  [FAIL] Batch {batch_num}: {str(e)[:100]} ({elapsed:.0f}s)")

        # Update run tracking
        total_entities = sum(len(r.entities) for r in all_results)
        total_assertions = sum(len(r.assertions) for r in all_results)
        run.artifacts_processed = len(all_results)
        run.assertions_extracted = total_assertions
        run.errors_encountered = total_errors
        self.run_registry.update_run(run)

        total_time = time.time() - start_time

        pending = self.failed_queue.get_pending()
        if pending:
            print(f"\n[!] {len(pending)} failed extractions in observability queue")

        print(f"\n{'='*60}")
        print(f"EXTRACTION COMPLETE")
        print(f"{'='*60}")
        print(f"  Time: {total_time:.0f}s ({total_time/60:.1f} min)")
        print(f"  Sources: {len(all_results)}")
        print(f"  Entities: {total_entities}")
        print(f"  Assertions: {total_assertions}")
        print(f"  Errors: {total_errors}")
        print(f"  API calls: {num_batches}/20 RPD")
        print(f"{'='*60}")

        return all_results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run extraction pipeline")
    parser.add_argument("--limit", type=int, default=None, help="Max issues to process")
    parser.add_argument("--force", action="store_true", help="Re-extract existing results")
    args = parser.parse_args()

    pipeline = ExtractionPipeline()
    results = pipeline.run(limit=args.limit, force=args.force)
