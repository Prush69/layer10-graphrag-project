"""
Entity canonicalization.

Resolves entity aliases, normalizes names, and maintains a persistent
alias → canonical_id registry. Uses an immutable merge ledger:
entities are never deleted, only linked via CANONICAL_REFERENT relationships.
"""
import json
import re
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from schema.ontology import Entity, EntityType


# =============================================================================
# Component alias map — maps common variations to canonical form
# =============================================================================

COMPONENT_ALIASES = {
    # react-dom variants
    "react-dom": "reactdom",
    "reactdom": "reactdom",
    "react dom": "reactdom",
    "the dom renderer": "reactdom",
    "dom renderer": "reactdom",
    "react-dom/client": "reactdom",
    "react-dom/server": "reactdom-server",
    # scheduler variants
    "scheduler": "scheduler",
    "react-scheduler": "scheduler",
    "the scheduler": "scheduler",
    # reconciler variants
    "react-reconciler": "reconciler",
    "reconciler": "reconciler",
    "the reconciler": "reconciler",
    "fiber": "fiber",
    "react fiber": "fiber",
    # hooks variants
    "hooks": "hooks",
    "react hooks": "hooks",
    "usestate": "hooks",
    "useeffect": "hooks",
    "usememo": "hooks",
    "useref": "hooks",
    "usecallback": "hooks",
    # concurrent mode
    "concurrent mode": "concurrent",
    "concurrent": "concurrent",
    "concurrent features": "concurrent",
    "concurrent rendering": "concurrent",
    # server components
    "server components": "server-components",
    "rsc": "server-components",
    "react server components": "server-components",
}


class EntityMergeRecord(BaseModel):
    """Audit record for an entity merge (immutable ledger entry)."""
    merge_id: str
    merged_at: str
    canonical_id: str
    merged_entity_id: str = Field(..., description="ID of the entity that was merged into the canonical")
    reason: str
    reversible: bool = True
    timestamp: str = ""
    event_type: str = "merge"  # 'merge' or 'split' for append-only ledger


class UnionFind:
    """
    Union-Find (Disjoint Set Union) with path compression and union-by-rank.
    
    At query time, instantly resolves aliases (e.g., '@danabramov' and
    'Dan Abramov') to their Canonical Root in near-constant time.
    """

    def __init__(self):
        self.parent: dict[str, str] = {}  # node → parent
        self.rank: dict[str, int] = {}    # node → rank

    def make_set(self, x: str):
        """Create a new set with x as its own root."""
        if x not in self.parent:
            self.parent[x] = x
            self.rank[x] = 0

    def find(self, x: str) -> str:
        """Find the canonical root with path compression."""
        if x not in self.parent:
            self.make_set(x)
            return x
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])  # path compression
        return self.parent[x]

    def union(self, x: str, y: str) -> str:
        """Union by rank. Returns the new root."""
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return rx
        # Union by rank
        if self.rank[rx] < self.rank[ry]:
            rx, ry = ry, rx
        self.parent[ry] = rx
        if self.rank[rx] == self.rank[ry]:
            self.rank[rx] += 1
        return rx

    def connected(self, x: str, y: str) -> bool:
        return self.find(x) == self.find(y)

    def split(self, x: str):
        """Detach x from its set, making it its own root."""
        self.parent[x] = x
        self.rank[x] = 0

    def to_dict(self) -> dict:
        return {"parent": dict(self.parent), "rank": dict(self.rank)}

    def from_dict(self, data: dict):
        self.parent = data.get("parent", {})
        self.rank = data.get("rank", {})


class EntityCanonicalizer:
    """
    Resolves entity aliases and maintains a canonical entity registry.

    Implements the Immutable Union-Find Ledger pattern:
    - Union-Find with path compression for instant alias resolution
    - Append-only event ledger (MergeEvent / SplitEvent)
    - Entities are never deleted, only linked
    """

    def __init__(self):
        self.alias_registry_path = config.DATA_DIR / "alias_registry.json"
        self.merge_ledger_path = config.DATA_DIR / "entity_merges.json"

        # Union-Find for instant canonical resolution
        self.uf = UnionFind()
        # alias → canonical_id mapping (for name lookups)
        self.alias_registry: dict[str, str] = {}
        # canonical_id → Entity data
        self.canonical_entities: dict[str, Entity] = {}
        # Merge audit log (append-only: MergeEvent + SplitEvent)
        self.merge_ledger: list[EntityMergeRecord] = []

        self._load()

    def _load(self):
        """Load persistent state from disk."""
        if self.alias_registry_path.exists():
            with open(self.alias_registry_path, "r") as f:
                data = json.load(f)
                # Support both old (flat dict) and new (with union_find) format
                if isinstance(data, dict) and "union_find" in data:
                    self.alias_registry = data.get("aliases", {})
                    self.uf.from_dict(data.get("union_find", {}))
                else:
                    self.alias_registry = data
                    # Rebuild Union-Find from alias registry
                    for alias, canonical in self.alias_registry.items():
                        self.uf.make_set(canonical)
                        self.uf.make_set(alias)
                        self.uf.union(alias, canonical)

        if self.merge_ledger_path.exists():
            with open(self.merge_ledger_path, "r") as f:
                data = json.load(f)
                self.merge_ledger = [EntityMergeRecord(**m) for m in data]

    def _save(self):
        """Persist state to disk."""
        with open(self.alias_registry_path, "w") as f:
            json.dump({
                "aliases": self.alias_registry,
                "union_find": self.uf.to_dict(),
            }, f, indent=2)

        with open(self.merge_ledger_path, "w") as f:
            json.dump(
                [m.model_dump(by_alias=True) for m in self.merge_ledger],
                f, indent=2
            )

    # -------------------------------------------------------------------------
    # Normalization helpers
    # -------------------------------------------------------------------------

    def _normalize_person(self, name: str) -> str:
        """
        Normalize a GitHub username.
        - Strip leading '@'
        - Lowercase
        - Strip whitespace
        """
        name = name.strip().lstrip("@").lower()
        return name

    def _normalize_component(self, name: str) -> str:
        """
        Normalize a React component/subsystem name.
        Maps common aliases to canonical form using the COMPONENT_ALIASES table.
        """
        normalized = name.strip().lower()
        normalized = re.sub(r'[^a-z0-9\-/ ]', '', normalized)

        # Check alias table
        if normalized in COMPONENT_ALIASES:
            return COMPONENT_ALIASES[normalized]

        # Fallback: strip non-alphanumeric
        return re.sub(r'[^a-z0-9]', '', normalized)

    def _normalize_name(self, entity_type: EntityType, name: str) -> str:
        """Dispatch to type-specific normalization."""
        if entity_type == EntityType.PERSON:
            return self._normalize_person(name)
        elif entity_type == EntityType.COMPONENT:
            return self._normalize_component(name)
        else:
            return name.strip()

    def _make_canonical_id(self, entity_type: EntityType, normalized_name: str) -> str:
        """Generate the canonical ID for an entity."""
        type_prefix = entity_type.value.lower()
        return f"{type_prefix}::{normalized_name}"

    # -------------------------------------------------------------------------
    # Core operations
    # -------------------------------------------------------------------------

    def register_entity(self, entity: Entity) -> Entity:
        """
        Register an entity. If an equivalent canonical entity already exists,
        merge aliases and return the canonical version. Otherwise, create a new
        canonical entity.

        Returns the canonical Entity (possibly with merged aliases).
        """
        normalized_name = self._normalize_name(entity.type, entity.name)
        canonical_id = self._make_canonical_id(entity.type, normalized_name)

        # Check alias registry first
        if entity.name.lower() in self.alias_registry:
            existing_id = self.alias_registry[entity.name.lower()]
            if existing_id in self.canonical_entities:
                return self._merge_into(
                    self.canonical_entities[existing_id], entity,
                    reason="Alias registry match"
                )

        # Check if canonical entity already exists
        if canonical_id in self.canonical_entities:
            return self._merge_into(
                self.canonical_entities[canonical_id], entity,
                reason="Canonical ID match"
            )

        # Also check by original entity id
        if entity.id in self.canonical_entities:
            return self._merge_into(
                self.canonical_entities[entity.id], entity,
                reason="Entity ID match"
            )

        # New canonical entity
        entity.id = canonical_id
        entity.name = normalized_name if entity.type in (EntityType.PERSON, EntityType.COMPONENT) else entity.name

        # Register all known aliases
        self._register_aliases(canonical_id, entity)

        self.canonical_entities[canonical_id] = entity
        self._save()
        return entity

    def _merge_into(self, canonical: Entity, incoming: Entity, reason: str) -> Entity:
        """
        Merge an incoming entity into an existing canonical entity.
        Uses the Immutable Merge Ledger: never deletes, only links.
        """
        # Merge aliases
        for alias in incoming.aliases:
            if alias not in canonical.aliases:
                canonical.aliases.append(alias)

        # Add the incoming name as an alias if different
        if incoming.name != canonical.name and incoming.name not in canonical.aliases:
            canonical.aliases.append(incoming.name)

        # Track merged_from
        if incoming.id and incoming.id != canonical.id and incoming.id not in canonical.merged_from:
            canonical.merged_from.append(incoming.id)

        # Merge properties (incoming properties don't overwrite existing)
        for k, v in incoming.properties.items():
            if k not in canonical.properties:
                canonical.properties[k] = v

        # Update temporal bounds
        if incoming.first_seen:
            if not canonical.first_seen or incoming.first_seen < canonical.first_seen:
                canonical.first_seen = incoming.first_seen
        if incoming.last_seen:
            if not canonical.last_seen or incoming.last_seen > canonical.last_seen:
                canonical.last_seen = incoming.last_seen

        # Register new aliases
        self._register_aliases(canonical.id, incoming)

        # Record in the immutable merge ledger
        merge_record = EntityMergeRecord(
            merge_id=f"em_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{hashlib.md5(incoming.id.encode() if incoming.id else b'unknown').hexdigest()[:6]}",
            merged_at=datetime.utcnow().isoformat(),
            canonical_id=canonical.id,
            merged_entity_id=incoming.id or "unknown",
            reason=reason,
            reversible=True,
            timestamp=datetime.utcnow().isoformat(),
        )
        self.merge_ledger.append(merge_record)
        self._save()

        return canonical

    def _register_aliases(self, canonical_id: str, entity: Entity):
        """Register all known names/aliases for an entity in the Union-Find."""
        names_to_register = [entity.name.lower()]
        names_to_register.extend(a.lower() for a in entity.aliases)
        if entity.id:
            names_to_register.append(entity.id.lower())

        self.uf.make_set(canonical_id)
        for name in names_to_register:
            if name:
                self.alias_registry[name] = canonical_id
                self.uf.make_set(name)
                self.uf.union(name, canonical_id)

    def get_canonical_id(self, name: Optional[str]) -> Optional[str]:
        """Look up the canonical ID via Union-Find root resolution."""
        if name is None or str(name).strip() == "" or str(name).lower() == "none":
            return None
        
        # Normalize name for consistent lookup (same logic as register_entity)
        name_str = str(name).strip()
        # Note: We don't have the entity type here, so we try raw and normalized variants
        variants = [
            name_str.lower(),
            name_str.lower().lstrip("@"),
            name_str.lower().replace("-", "").replace(" ", ""),
        ]
        
        for key in variants:
            if key in self.alias_registry:
                # Resolve through Union-Find with path compression
                root = self.uf.find(self.alias_registry[key])
                # Map the root back through alias_registry to get the authoritative canonical_id.
                return self.alias_registry.get(root, root)
        return None

    def get_canonical_entity(self, entity_id: str) -> Optional[Entity]:
        """Get the canonical entity by ID."""
        return self.canonical_entities.get(entity_id)

    def undo_merge(self, merge_id: str) -> bool:
        """
        Undo a specific merge by appending a SplitEvent to the ledger.
        
        The ledger is append-only: we never delete entries. Instead, a
        SplitEvent records the reversal, and the Union-Find is updated
        to detach the merged entity.
        """
        # Find the original merge record
        original = None
        for record in self.merge_ledger:
            if record.merge_id == merge_id and record.reversible and record.event_type == "merge":
                original = record
                break

        if not original:
            return False

        # Append a SplitEvent (never delete the MergeEvent)
        split_record = EntityMergeRecord(
            merge_id=f"split_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{hashlib.md5(merge_id.encode()).hexdigest()[:6]}",
            merged_at=datetime.utcnow().isoformat(),
            canonical_id=original.canonical_id,
            merged_entity_id=original.merged_entity_id,
            reason=f"Split: reversal of {merge_id}",
            reversible=True,
            timestamp=datetime.utcnow().isoformat(),
            event_type="split",
        )
        self.merge_ledger.append(split_record)

        # Detach in Union-Find
        self.uf.split(original.merged_entity_id)

        self._save()
        return True

    def get_merge_history(self, entity_id: str) -> list[EntityMergeRecord]:
        """Get all merge records involving an entity (as canonical or merged)."""
        return [
            m for m in self.merge_ledger
            if m.canonical_id == entity_id or m.merged_entity_id == entity_id
        ]

    def get_stats(self) -> dict:
        """Get canonicalization statistics."""
        return {
            "total_canonical_entities": len(self.canonical_entities),
            "total_aliases": len(self.alias_registry),
            "total_merges": len(self.merge_ledger),
            "reversible_merges": sum(1 for m in self.merge_ledger if m.reversible),
        }
