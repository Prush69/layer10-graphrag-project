"""
Extraction Run Tracker.

Persists metadata about each extraction run to ensure auditability and versioning.
"""
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from pydantic import BaseModel, Field

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config

class ExtractionRun(BaseModel):
    """Metadata about a single extraction execution."""
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    model: str
    prompt_version: str
    schema_version: str = "3.0.0"
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    artifacts_processed: int = 0
    assertions_extracted: int = 0
    errors_encountered: int = 0
    metadata: dict = Field(default_factory=dict)

class RunRegistry:
    """Registry for managing extraction runs."""
    
    def __init__(self):
        self.path = config.DATA_DIR / "extraction_runs.json"
        self.runs: List[ExtractionRun] = []
        self._load()

    def _load(self):
        if self.path.exists():
            with open(self.path, "r") as f:
                data = json.load(f)
                self.runs = [ExtractionRun(**r) for r in data]

    def _save(self):
        with open(self.path, "w") as f:
            json.dump([r.model_dump() for r in self.runs], f, indent=2)

    def start_run(self, model: str, prompt_version: str, metadata: dict = None) -> ExtractionRun:
        """Initialize a new extraction run."""
        run = ExtractionRun(
            model=model,
            prompt_version=prompt_version,
            metadata=metadata or {}
        )
        self.runs.append(run)
        self._save()
        return run

    def update_run(self, run: ExtractionRun):
        """Update an existing run's stats."""
        for i, r in enumerate(self.runs):
            if r.run_id == run.run_id:
                self.runs[i] = run
                break
        self._save()

    def get_latest_run(self) -> Optional[ExtractionRun]:
        if not self.runs:
            return None
        return self.runs[-1]
