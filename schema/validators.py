"""
Validators for the ontology schema.

Handles validation, repair, normalization, and confidence scoring
for extracted entities and claims.
"""
from __future__ import annotations
import re
import hashlib
from datetime import datetime
from typing import Optional

from schema.ontology import (
    Entity, EntityType, Assertion, AssertionType, Claim, ClaimType, ClaimStatus,
    Evidence, ArtifactType, ExtractionResult, SupportStrength
)


def normalize_timestamp(ts: Optional[str]) -> Optional[str]:
    """Normalize various timestamp formats to ISO-8601."""
    if not ts:
        return None
    try:
        # Try ISO format first
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.isoformat()
    except (ValueError, AttributeError):
        pass
    # Try common formats
    for fmt in ["%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"]:
        try:
            dt = datetime.strptime(str(ts), fmt)
            return dt.isoformat()
        except ValueError:
            continue
    return None


def normalize_text(text: str) -> str:
    """Strip and normalize whitespace in text."""
    if not text:
        return ""
    return re.sub(r'\s+', ' ', text.strip())


def generate_entity_id(entity_type: EntityType, name: str) -> str:
    """Generate a deterministic entity ID from type and name."""
    normalized = name.lower().strip().replace(" ", "_")
    return f"{entity_type.value.lower()}::{normalized}"


def generate_claim_id(claim_type: ClaimType, subject_id: str, object_id: Optional[str], timestamp: Optional[str] = None) -> str:
    """Generate a deterministic claim ID."""
    parts = [claim_type.value, subject_id, object_id or "none"]
    if timestamp:
        parts.append(timestamp)
    raw = "::".join(parts)
    hash_suffix = hashlib.md5(raw.encode()).hexdigest()[:8]
    return f"claim::{claim_type.value.lower()}::{hash_suffix}"


def validate_entity(entity: dict) -> tuple[Optional[Entity], list[str]]:
    """
    Validate and repair a raw entity dict.
    Returns (Entity or None, list of error messages).
    """
    errors = []

    # Required fields
    if not entity.get("name"):
        errors.append("Entity missing 'name'")
        return None, errors

    # Normalize type
    # Guard against 'category' LLM output
    entity_type_raw = entity.get("type") or entity.get("category", "")
    if entity_type_raw is None:
        entity_type_raw = ""
        
    entity_type = None
    for et in EntityType:
        if et.value.lower() == str(entity_type_raw).lower():
            entity_type = et
            break
    if not entity_type:
        errors.append(f"Unknown entity type: {entity_type_raw}")
        return None, errors

    # Generate ID if missing
    entity_id = entity.get("id") or generate_entity_id(entity_type, entity["name"])

    # Normalize name
    name = normalize_text(entity["name"])

    # Normalize aliases
    aliases = entity.get("aliases", [])
    if isinstance(aliases, str):
        aliases = [aliases]
    aliases = [normalize_text(a) for a in aliases if a]

    # Normalize timestamps
    first_seen = normalize_timestamp(entity.get("first_seen"))
    last_seen = normalize_timestamp(entity.get("last_seen"))

    try:
        validated = Entity(
            id=entity_id,
            type=entity_type,
            name=name,
            aliases=aliases,
            properties=entity.get("properties", {}),
            first_seen=first_seen,
            last_seen=last_seen,
            merged_from=entity.get("merged_from", [])
        )
        return validated, errors
    except Exception as e:
        errors.append(f"Entity validation failed: {str(e)}")
        return None, errors


def validate_evidence(evidence: dict) -> tuple[Optional[Evidence], list[str]]:
    """Validate and repair a raw evidence dict."""
    errors = []

    artifact_version_id = evidence.get("artifact_version_id", "")
    if not artifact_version_id:
        # Fallback to source_id if artifact_version_id is missing (for legacy or raw extraction)
        artifact_version_id = evidence.get("source_id", "unknown-v1")

    excerpt = normalize_text(evidence.get("excerpt", ""))
    if not excerpt:
        errors.append("Evidence missing 'excerpt'")
        return None, errors

    # Normalize support strength
    ss_raw = evidence.get("support_strength", "explicit")
    support_strength = SupportStrength.EXPLICIT
    for ss in SupportStrength:
        if ss.value.lower() == str(ss_raw).lower():
            support_strength = ss
            break

    try:
        validated = Evidence(
            artifact_version_id=artifact_version_id,
            excerpt=excerpt[:2000],
            offset_start=evidence.get("offset_start"),
            offset_end=evidence.get("offset_end"),
            support_strength=support_strength
        )
        return validated, errors
    except Exception as e:
        errors.append(f"Evidence validation failed: {str(e)}")
        return None, errors


def validate_assertion(assertion: dict) -> tuple[Optional[Assertion], list[str]]:
    """Validate and repair a raw assertion dict."""
    errors = []

    # Required fields
    asserted_by = assertion.get("asserted_by", "")
    if not asserted_by:
        errors.append("Assertion missing 'asserted_by' (author)")
        return None, errors

    artifact_version_id = assertion.get("artifact_version_id", "")
    if not artifact_version_id:
        artifact_version_id = assertion.get("source_id", "unknown-v1")

    # Normalize type
    assertion_type_raw = assertion.get("type", "observation")
    assertion_type = AssertionType.OBSERVATION
    for at in AssertionType:
        if at.value.lower() == str(assertion_type_raw).lower():
            assertion_type = at
            break

    # Normalize claim type
    claim_type_raw = assertion.get("claim_type", "")
    claim_type = None
    for ct in ClaimType:
        if ct.value.lower() == str(claim_type_raw).lower():
            claim_type = ct
            break
    if not claim_type:
        errors.append(f"Assertion missing or unknown 'claim_type': {claim_type_raw}")
        return None, errors

    subject_id = assertion.get("subject_id", "")
    if not subject_id:
        errors.append("Assertion missing 'subject_id'")
        return None, errors

    # Normalize confidence
    confidence = assertion.get("confidence", 0.5)
    try:
        confidence = float(confidence)
        confidence = max(0.0, min(1.0, confidence))
    except (ValueError, TypeError):
        confidence = 0.5

    # Validate evidence
    validated_evidence = []
    for ev in assertion.get("evidence", []):
        if isinstance(ev, dict):
            v_ev, ev_errors = validate_evidence(ev)
            if v_ev:
                validated_evidence.append(v_ev)
            errors.extend(ev_errors)

    try:
        validated = Assertion(
            id=assertion.get("id") or f"assertion::{hashlib.md5(str(assertion).encode()).hexdigest()[:8]}",
            claim_id=assertion.get("claim_id"),
            artifact_version_id=artifact_version_id,
            asserted_by=asserted_by,
            type=assertion_type,
            claim_type=claim_type,
            subject_id=subject_id,
            object_id=assertion.get("object_id"),
            properties=assertion.get("properties", {}),
            timestamp=normalize_timestamp(assertion.get("timestamp")) or datetime.utcnow().isoformat(),
            confidence=confidence,
            evidence=validated_evidence
        )
        return validated, errors
    except Exception as e:
        errors.append(f"Assertion validation failed: {str(e)}")
        return None, errors


def validate_claim(claim: dict) -> tuple[Optional[Claim], list[str]]:
    """Validate and repair a raw claim dict."""
    errors = []

    # Required fields
    subject_id = claim.get("subject_id", "")
    if not subject_id:
        errors.append("Claim missing 'subject_id'")
        return None, errors

    # Normalize claim type
    claim_type_raw = claim.get("type", "")
    claim_type = None
    for ct in ClaimType:
        if ct.value.lower() == str(claim_type_raw).lower():
            claim_type = ct
            break
    if not claim_type:
        errors.append(f"Unknown claim type: {claim_type_raw}")
        return None, errors

    # Generate ID if missing
    claim_id = claim.get("id") or generate_claim_id(
        claim_type, subject_id, claim.get("object_id"),
        claim.get("valid_from")
    )

    # Normalize confidence
    confidence = claim.get("confidence", 0.5)
    try:
        confidence = float(confidence)
        confidence = max(0.0, min(1.0, confidence))
    except (ValueError, TypeError):
        confidence = 0.5

    # Validate evidence
    validated_evidence = []
    for ev in claim.get("evidence", []):
        if isinstance(ev, dict):
            v_ev, ev_errors = validate_evidence(ev)
            if v_ev:
                validated_evidence.append(v_ev)
            errors.extend(ev_errors)

    # Normalize status
    status_raw = claim.get("status", "active")
    status = ClaimStatus.ACTIVE
    for cs in ClaimStatus:
        if cs.value.lower() == str(status_raw).lower():
            status = cs
            break

    try:
        validated = Claim(
            id=claim_id,
            type=claim_type,
            subject_id=subject_id,
            object_id=claim.get("object_id"),
            properties=claim.get("properties", {}),
            confidence=confidence,
            status=status,
            evidence=validated_evidence,
            valid_from=normalize_timestamp(claim.get("valid_from")),
            valid_until=normalize_timestamp(claim.get("valid_until")),
            extracted_at=normalize_timestamp(claim.get("extracted_at")) or datetime.utcnow().isoformat(),
            extraction_version=claim.get("extraction_version", "v1.0"),
            superseded_by=claim.get("superseded_by"),
            merged_from=claim.get("merged_from", [])
        )
        return validated, errors
    except Exception as e:
        errors.append(f"Claim validation failed: {str(e)}")
        return None, errors


def validate_extraction_result(raw: dict) -> tuple[ExtractionResult, list[str]]:
    """
    Validate a full extraction result dict.
    Returns a validated ExtractionResult and a list of all errors encountered.
    """
    all_errors = []

    # Validate entities
    validated_entities = []
    for ent in raw.get("entities", []):
        if isinstance(ent, dict):
            v_ent, ent_errors = validate_entity(ent)
            if v_ent:
                validated_entities.append(v_ent)
            all_errors.extend(ent_errors)

    # Validate assertions
    validated_assertions = []
    for ass in raw.get("assertions", []):
        if isinstance(ass, dict):
            v_ass, ass_errors = validate_assertion(ass)
            if v_ass:
                validated_assertions.append(v_ass)
            all_errors.extend(ass_errors)

    # Validate claims (Facts)
    validated_claims = []
    for clm in raw.get("claims", []):
        if isinstance(clm, dict):
            v_clm, clm_errors = validate_claim(clm)
            if v_clm:
                validated_claims.append(v_clm)
            all_errors.extend(clm_errors)

    result = ExtractionResult(
        source_id=raw.get("source_id", "unknown"),
        entities=validated_entities,
        assertions=validated_assertions,
        claims=validated_claims,
        raw_text_length=raw.get("raw_text_length", 0),
        extraction_version=raw.get("extraction_version", "v3.0-ideal"),
        extracted_at=raw.get("extracted_at", datetime.utcnow().isoformat()),
        model=raw.get("model", ""),
        errors=all_errors
    )

    return result, all_errors


def verify_evidence_offsets(result: ExtractionResult, source_text: str) -> dict:
    """
    Verify that evidence excerpts match the source text at the given offsets.
    
    Implements the Critic Loop's offset verification step:
    - If excerpt == source_text[offset_start:offset_end] → verified
    - If mismatch, attempt fuzzy recovery via substring search
    - Returns verification stats
    """
    stats = {"total": 0, "verified": 0, "recovered": 0, "failed": 0}

    for claim in result.claims:
        for evidence in claim.evidence:
            stats["total"] += 1

            if evidence.offset_start is None or evidence.offset_end is None:
                # No offsets provided — attempt to find excerpt in source
                idx = source_text.find(evidence.excerpt[:80])
                if idx >= 0:
                    evidence.offset_start = idx
                    evidence.offset_end = idx + len(evidence.excerpt)
                    stats["recovered"] += 1
                else:
                    stats["failed"] += 1
                continue

            # Verify offset alignment
            expected = source_text[evidence.offset_start:evidence.offset_end]
            if expected.strip() == evidence.excerpt.strip():
                stats["verified"] += 1
            else:
                # Fuzzy recovery: find the excerpt in the source text
                idx = source_text.find(evidence.excerpt[:80])
                if idx >= 0:
                    evidence.offset_start = idx
                    evidence.offset_end = idx + len(evidence.excerpt)
                    stats["recovered"] += 1
                else:
                    # Try normalized matching
                    norm_excerpt = re.sub(r'\s+', ' ', evidence.excerpt.strip())
                    norm_source = re.sub(r'\s+', ' ', source_text)
                    idx = norm_source.find(norm_excerpt[:80])
                    if idx >= 0:
                        evidence.offset_start = idx
                        evidence.offset_end = idx + len(norm_excerpt)
                        stats["recovered"] += 1
                    else:
                        stats["failed"] += 1

    return stats
