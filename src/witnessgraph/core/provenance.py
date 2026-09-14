"""Provenance manifest: a deterministic, cryptographically verifiable case summary.

See DESIGN.md principle 5. The manifest hash changes if and only if the
set of evidence, normalized events, entities, relationships, time
assertions, or hypotheses in the case changes. It does not depend on
insertion order, the machine it was computed on, or wall-clock time
(aside from timestamps that are themselves part of the case's content).

Note: EvidenceItem's contribution to the manifest is its
``raw_content_hash`` (== its id), not a hash of the full serialized
object -- this deliberately excludes ``chain_of_custody``, so that
recording an "exported"/"imported" custody event never changes a case's
reproducibility hash. See EvidenceItem's docstring.

See docs/phase3-v0.3-design.md §6.4/§11 for the v0.3 change:
``NormalizedEvent``/``TimeAssertion`` now contribute ``obj.id`` directly
(mirroring ``EvidenceItem``), not a full-object hash -- because their id
is now itself a content hash of their identity-relevant fields
(``created_at`` excluded), this makes the manifest hash independent of
*when* a case was ingested, not just independent of insertion order.
``manifest_version`` distinguishes a manifest computed under this (v0.3,
version 2) algorithm from one computed under the old (v0.1/v0.2, version
1) algorithm, which hashed the full object including ``created_at`` for
those two types -- the two are not comparable, and callers must check
the version before comparing hashes (see ``witnessgraph.replay.replay``).

v1.1 adds a sixth collection, ``relationships`` (``core.relationships.
Relationship``, content-addressed exactly like ``NormalizedEvent``/
``TimeAssertion`` -- contributes ``obj.id`` directly). This changes the
manifest hash for every case, even one with zero relationships, since
the set of collection names hashed together is itself part of the
manifest -- so ``manifest_version`` bumps to 3, following the exact
v0.1/v0.2 -> v0.3 precedent above. An old case's case.db lazily gains an
empty ``relationships`` table on next open (``SqliteStore``'s
``CREATE TABLE IF NOT EXISTS`` schema, run unconditionally on every
open) -- no migration step is required, and every existing collection's
recorded content and manifest.json are left completely untouched. Its
recorded (v2) manifest simply reads as version-incomparable against a
freshly recomputed (v3) one, exactly like a v0.1/v0.2 case does today;
`witnessgraph verify`/`replay` already report that as NOT COMPARABLE,
never a false MISMATCH.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict

from witnessgraph.core.ids import canonical_json_bytes, sha256_hex

if TYPE_CHECKING:
    from witnessgraph.store.base import Store

#: The current manifest algorithm version. Bump this, and document the
#: change in docs/, whenever a change to what/how collections are hashed
#: would make an old manifest incomparable to a newly computed one.
CURRENT_MANIFEST_VERSION = 3


class ProvenanceManifest(BaseModel):
    """A deterministic, cryptographically verifiable summary of a case's contents.

    ``manifest_version`` defaults to ``1`` so that a pre-v0.3
    ``manifest.json`` file (which predates this field entirely) is read
    as version 1 via this Pydantic default, not rejected -- see
    docs/phase3-v0.3-design.md §11. Any manifest freshly computed by
    :func:`compute_manifest` is stamped with ``CURRENT_MANIFEST_VERSION``
    explicitly, never left to the default.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    collection_hashes: dict[str, str]
    manifest_hash: str
    manifest_version: int = 1


def content_hash_of(model: BaseModel) -> str:
    """Content hash of a pydantic model's canonical JSON form."""
    return sha256_hex(canonical_json_bytes(model.model_dump(mode="json")))


def _collection_hash(object_hashes: dict[str, str]) -> str:
    """Hash a collection of (id -> content_hash) pairs, independent of insertion order."""
    sorted_pairs: list[Any] = sorted(object_hashes.items())
    return sha256_hex(canonical_json_bytes(sorted_pairs))


def manifest_verdict(
    recomputed: ProvenanceManifest, recorded: ProvenanceManifest | None
) -> str:
    """Compare a freshly recomputed manifest against the recorded one.

    One of ``"NO_RECORDED_MANIFEST"`` (no ``manifest.json`` exists yet),
    ``"NOT_COMPARABLE"`` (recorded under a different ``manifest_version``
    algorithm -- see this module's docstring), ``"MATCH"``, or
    ``"MISMATCH"``. Shared by ``report.render_json`` and
    ``witnessgraph.service`` so both surfaces report identical verdicts
    for identical case state.
    """
    if recorded is None:
        return "NO_RECORDED_MANIFEST"
    if recorded.manifest_version != recomputed.manifest_version:
        return "NOT_COMPARABLE"
    if recomputed.manifest_hash == recorded.manifest_hash:
        return "MATCH"
    return "MISMATCH"


def compute_manifest(store: Store) -> ProvenanceManifest:
    """Compute the current provenance manifest for everything held in ``store``.

    Always stamped with ``CURRENT_MANIFEST_VERSION`` (the v0.3 algorithm).
    """
    collections: dict[str, dict[str, str]] = {
        "evidence_items": {e.id: e.raw_content_hash for e in store.list_evidence()},
        "normalized_events": {e.id: e.id for e in store.list_normalized_events()},
        "entities": {e.id: content_hash_of(e) for e in store.list_entities()},
        "relationships": {r.id: r.id for r in store.list_relationships()},
        "time_assertions": {t.id: t.id for t in store.list_time_assertions()},
        "hypotheses": {h.id: content_hash_of(h) for h in store.list_hypotheses()},
    }
    collection_hashes = {name: _collection_hash(hashes) for name, hashes in collections.items()}
    manifest_hash = sha256_hex(canonical_json_bytes(sorted(collection_hashes.items())))
    return ProvenanceManifest(
        collection_hashes=collection_hashes,
        manifest_hash=manifest_hash,
        manifest_version=CURRENT_MANIFEST_VERSION,
    )
