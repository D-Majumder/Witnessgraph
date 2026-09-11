"""Provenance manifest: a deterministic, cryptographically verifiable case summary.

See DESIGN.md principle 5. The manifest hash changes if and only if the
set of evidence, normalized events, entities, time assertions, or
hypotheses in the case changes. It does not depend on insertion order,
the machine it was computed on, or wall-clock time (aside from
timestamps that are themselves part of the case's content).

Note: EvidenceItem's contribution to the manifest is its
``raw_content_hash`` (== its id), not a hash of the full serialized
object -- this deliberately excludes ``chain_of_custody``, so that
recording an "exported"/"imported" custody event never changes a case's
reproducibility hash. See EvidenceItem's docstring.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict

from witnessgraph.core.ids import canonical_json_bytes, sha256_hex

if TYPE_CHECKING:
    from witnessgraph.store.base import Store


class ProvenanceManifest(BaseModel):
    """A deterministic, cryptographically verifiable summary of a case's contents."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    collection_hashes: dict[str, str]
    manifest_hash: str


def content_hash_of(model: BaseModel) -> str:
    """Content hash of a pydantic model's canonical JSON form."""
    return sha256_hex(canonical_json_bytes(model.model_dump(mode="json")))


def _collection_hash(object_hashes: dict[str, str]) -> str:
    """Hash a collection of (id -> content_hash) pairs, independent of insertion order."""
    sorted_pairs: list[Any] = sorted(object_hashes.items())
    return sha256_hex(canonical_json_bytes(sorted_pairs))


def compute_manifest(store: Store) -> ProvenanceManifest:
    """Compute the current provenance manifest for everything held in ``store``."""
    collections: dict[str, dict[str, str]] = {
        "evidence_items": {e.id: e.raw_content_hash for e in store.list_evidence()},
        "normalized_events": {e.id: content_hash_of(e) for e in store.list_normalized_events()},
        "entities": {e.id: content_hash_of(e) for e in store.list_entities()},
        "time_assertions": {t.id: content_hash_of(t) for t in store.list_time_assertions()},
        "hypotheses": {h.id: content_hash_of(h) for h in store.list_hypotheses()},
    }
    collection_hashes = {name: _collection_hash(hashes) for name, hashes in collections.items()}
    manifest_hash = sha256_hex(canonical_json_bytes(sorted(collection_hashes.items())))
    return ProvenanceManifest(collection_hashes=collection_hashes, manifest_hash=manifest_hash)
