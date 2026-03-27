"""
Ontology/Schema for the Layer10 Grounded Long-Term Memory system.

Defines all entity types, claim/relationship types, and evidence structures
used throughout the extraction and memory graph pipeline.
"""
from __future__ import annotations
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field
from datetime import datetime


# =============================================================================
# Evidence
# =============================================================================

class ArtifactType(str, Enum):
    ISSUE = "issue"
    PULL_REQUEST = "pull_request"
    COMMIT = "commit"
    DOCUMENT = "document"
    MESSAGE = "message"
    EMAIL = "email"


class SupportStrength(str, Enum):
    EXPLICIT = "explicit"
    INFERRED = "inferred"
    WEAK = "weak"


class Artifact(BaseModel):
    """A root source artifact (e.g. GitHub Issue #123)."""
    id: str
    type: ArtifactType
    url: Optional[str] = None
    content_hash: Optional[str] = None
    simhash: Optional[str] = None
    metadata: dict = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class ArtifactVersion(BaseModel):
    """An immutable version of an artifact at a point in time."""
    id: str = Field(..., description="Hash of content + artifact_id")
    artifact_id: str
    content: str
    checksum: str  # content_hash
    simhash: Optional[str] = None
    metadata: dict = Field(default_factory=dict)
    version_num: int
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class Evidence(BaseModel):
    """Specific textual evidence supporting an assertion/claim."""
    claim_id: Optional[str] = Field(None, description="ID of the claim this supports")
    artifact_version_id: str = Field(..., description="ID of the artifact version")
    source_id: Optional[str] = Field(None, description="ID of the original artifact (e.g. Issue #)")
    url: Optional[str] = Field(None, description="URL to the source artifact")
    timestamp: Optional[str] = Field(None, description="Timestamp of the original artifact")
    excerpt: str = Field(..., description="Exact text span from the source")
    offset_start: Optional[int] = Field(None, description="Start character offset in source")
    offset_end: Optional[int] = Field(None, description="End character offset in source")
    
    # New enhancements for 9.5/10
    confidence: float = Field(1.0, ge=0.0, le=1.0, description="Confidence in this specific item")
    support_strength: SupportStrength = SupportStrength.EXPLICIT
    source_type: Optional[str] = Field(None, description="Artifact type: issue, pull_request, etc.")
    embedding: Optional[list[float]] = None

    def evidence_key(self) -> str:
        return f"{self.artifact_version_id}::{self.offset_start}:{self.offset_end}"


# =============================================================================
# Entity Types
# =============================================================================

class EntityType(str, Enum):
    # --- Artifact Layer ---
    ISSUE = "Issue"
    PULL_REQUEST = "PullRequest"
    COMMENT = "Comment"
    MESSAGE = "Message"
    EMAIL = "Email"
    
    # --- Semantic Layer ---
    PERSON = "Person"
    TEAM = "Team"
    PROJECT = "Project"
    COMPONENT = "Component"
    DECISION = "Decision"
    OWNERSHIP = "Ownership"
    TASK = "Task"
    BUG = "Bug"
    DESIGN_PROPOSAL = "DesignProposal"
    INCIDENT = "Incident"
    RELEASE = "Release"
    LABEL = "Label"


class Entity(BaseModel):
    """A canonical entity in the memory graph."""
    id: str = Field(..., description="Unique canonical ID")
    type: EntityType
    name: str = Field(..., description="Display name")
    aliases: list[str] = Field(default_factory=list, description="Known aliases")
    properties: dict = Field(default_factory=dict, description="Type-specific properties")
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None
    merged_from: list[str] = Field(default_factory=list, description="IDs merged into this entity")

    from pydantic import model_validator
    @model_validator(mode='before')
    @classmethod
    def _map_category_to_type(cls, data: dict) -> dict:
        if isinstance(data, dict):
            if 'category' in data and 'type' not in data:
                data['type'] = data.pop('category')
        return data
    
    # New for 9.3
    memory_strength: float = Field(1.0, description="Durable memory decay score")
    decay_rate: float = Field(0.01, description="Rate at which this entity fades if not reinforced")

    def entity_key(self) -> str:
        return f"{self.type.value}::{self.id}"


# =============================================================================
# Claim Types
# =============================================================================

class ClaimType(str, Enum):
    # Relational
    ASSIGNED_TO = "AssignedTo"
    WORKS_ON = "WorksOn"
    DEPENDS_ON = "DependsOn"
    AFFECTS = "Affects"
    FIXES = "Fixes"
    RELATED_TO = "RelatedTo"

    # Participation (connect people to issues/PRs)
    COMMENTED = "Commented"          # Person commented on Issue/PR
    AUTHORED_BY = "AuthoredBy"       # Issue/PR authored by Person
    LABELED_WITH = "LabeledWith"     # Issue/PR has Label
    REFERENCED_PR = "ReferencedPR"  # Issue references a PullRequest

    # Semantic
    DECISION_MADE = "DecisionMade"
    OWNERSHIP_DECLARED = "OwnershipDeclared"
    STATUS_CHANGED = "StatusChanged"
    ISSUE_REPORTED = "IssueReported"
    RELEASE_PUBLISHED = "ReleasePublished"
    INCIDENT_DETECTED = "IncidentDetected"


class AssertionType(str, Enum):
    PROPOSAL = "proposal"
    AGREEMENT = "agreement"
    DECISION = "decision"
    OBSERVATION = "observation"
    CORRECTION = "correction"


class Assertion(BaseModel):
    """An individual assertion made by a specific author in a specific artifact."""
    id: str = Field(..., description="Unique assertion ID")
    claim_id: Optional[str] = Field(None, description="The canonical claim this assertion supports")
    artifact_version_id: str
    asserted_by: str = Field(..., description="The author of the assertion")
    type: AssertionType
    
    # Semantic mapping for aggregation
    claim_type: ClaimType
    subject_id: str
    object_id: Optional[str] = None
    properties: dict = Field(default_factory=dict)
    
    from pydantic import model_validator
    @model_validator(mode='before')
    @classmethod
    def _map_category_to_type(cls, data: dict) -> dict:
        if isinstance(data, dict):
            if 'category' in data and 'type' not in data:
                data['type'] = data.pop('category')
        return data
    
    timestamp: str = Field(..., description="When the assertion was originally made")
    confidence: float = Field(1.0, ge=0.0, le=1.0)
    evidence: list[Evidence] = Field(default_factory=list)

    def assertion_key(self) -> str:
        return f"{self.asserted_by}::{self.type.value}::{self.claim_type.value}::{self.subject_id}::{self.object_id or 'none'}"


class ClaimStatus(str, Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    RETRACTED = "retracted"
    UNCERTAIN = "uncertain"
    REDACTED = "redacted"
    UNGROUNDED = "ungrounded"


class Claim(BaseModel):
    """
    A canonical fact/relationship in the memory graph.
    Formed by aggregating one or more assertions.
    """
    id: str = Field(..., description="Unique claim ID")
    type: ClaimType
    subject_id: str = Field(..., description="Source entity ID")
    object_id: Optional[str] = Field(None, description="Target entity ID")
    properties: dict = Field(default_factory=dict, description="Claim-specific properties")
    confidence: float = Field(0.5, ge=0.0, le=1.0, description="Global extraction/fact confidence")
    status: ClaimStatus = ClaimStatus.ACTIVE
    evidence: list[Evidence] = Field(default_factory=list, description="Aggregated supporting evidence")
    assertions: list[str] = Field(default_factory=list, description="IDs of assertions supporting this fact")
    valid_from: Optional[str] = Field(None, description="Bitemporal: Validity Start")
    valid_until: Optional[str] = Field(None, description="Bitemporal: Validity End")
    extracted_at: Optional[str] = Field(None, description="System Time: Extraction")
    
    # Memory Strength Model
    memory_strength: float = Field(1.0, description="Durable memory score")
    decay_rate: float = Field(0.01, description="Rate at which this fact fades")
    reinforcement_count: int = Field(0, description="How many assertions support this")
    authority_weight: float = Field(1.0, description="Weight based on author reputation")
    merged_from: list[str] = Field(default_factory=list, description="IDs of claims merged into this one")
    superseded_by: Optional[str] = Field(None, description="ID of the claim that superseded this one")

    def claim_key(self) -> str:
        return f"{self.type.value}::{self.subject_id}::{self.object_id or 'none'}"

    def is_current(self) -> bool:
        return self.status == ClaimStatus.ACTIVE and self.valid_until is None


# =============================================================================
# Extraction Output
# =============================================================================

class ExtractionResult(BaseModel):
    """The output of running extraction on a single source artifact."""
    source_id: str
    entities: list[Entity] = Field(default_factory=list)
    assertions: list[Assertion] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    raw_text_length: int = 0
    extraction_version: str = "v3.0-ideal"
    extracted_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    model: str = ""
    errors: list[str] = Field(default_factory=list)


class ExtractionResultBatch(BaseModel):
    """The output of running batch extraction on multiple artifacts."""
    results: list[ExtractionResult] = Field(default_factory=list)
    


# =============================================================================
# Descriptions
# =============================================================================

ENTITY_TYPE_DESCRIPTIONS = {
    EntityType.PERSON: "A contributor or user",
    EntityType.DECISION: "A formal architectural or policy choice made during discussion",
    EntityType.OWNERSHIP: "Responsibility assignment for a component or task",
    EntityType.COMPONENT: "A module, package, or subsystem",
    EntityType.INCIDENT: "A bug, regression, or service outage",
    EntityType.RELEASE: "A versioned software delivery",
    EntityType.BUG: "A reported defect or unexpected behavior",
}

CLAIM_TYPE_DESCRIPTIONS = {
    ClaimType.DECISION_MADE: "A concrete conclusion was reached in the artifact",
    ClaimType.OWNERSHIP_DECLARED: "An individual or team took responsibility for an item",
    ClaimType.STATUS_CHANGED: "An item's state (e.g. bug status) evolved",
}

# =============================================================================
# Constants
# =============================================================================

SCHEMA_VERSION = "2.0.0"
