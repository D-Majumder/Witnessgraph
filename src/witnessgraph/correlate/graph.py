"""Deterministic, bounded graph traversal over a case's Entities and Relationships.

Relationships (v1.1) gave Witnessgraph edges; this module is what makes
them analyzable. Two operations, both built on one shared breadth-first
search:

- :func:`find_neighbors` -- every entity reachable from an origin entity
  within a bounded number of hops (a bounded ego-network / neighborhood).
- :func:`find_path` -- one deterministic, shortest (fewest-hop)
  relationship chain between two entities, with full step-by-step
  provenance back to the evidence each hop is grounded in.

Design decisions, load-bearing:

- **Directed by default.** A ``Relationship`` is directed
  (``source_entity_id`` -> ``target_entity_id``); traversal defaults to
  following only that direction (``direction="out"``). Witnessgraph never
  silently treats ``A --connected_to--> B`` as also meaning
  ``B --connected_to--> A``. ``direction="in"`` (follow edges backward)
  and ``direction="both"`` (either way) are explicit opt-ins. Whichever
  way an edge is walked, the ``Relationship`` object itself is always
  reported exactly as stored -- its own ``source_entity_id``/
  ``target_entity_id`` are never swapped; :class:`TraversalStep` instead
  records ``walked_direction`` ("forward"/"backward") separately, so a
  caller can always tell the true edge from the walk that used it.
- **Deterministic, independent of storage order.** ``Store.list_relationships()``
  is treated as an unordered collection: this module always sorts by
  ``Relationship.id`` itself (mirroring ``correlate.contradictions`` and
  ``correlate.gaps``) before using it, never relying on SQLite's
  incidental row order. BFS visits the current frontier's entities in
  the deterministic order they were themselves discovered, and each
  entity's own edges in relationship-id order, so re-running traversal
  against unchanged data always produces byte-identical results, and a
  tie between two equal-length paths is always broken the same way.
- **Bounded and cycle-safe.** An entity is discovered at most once (the
  first time BFS reaches it); a cycle anywhere in the graph (including a
  relationship pointing back to an already-visited entity) is simply
  never re-expanded, not specially detected -- termination is
  structural, not heuristic. ``max_depth`` additionally caps how many
  hops are ever explored, independent of graph size.
- **No entity resolution, no inference.** This module never merges,
  resolves, or invents an entity or relationship; it only reports
  relationship chains and neighborhoods that already exist, exactly as
  recorded. A returned chain describes a *structural connection*,
  grounded in cited evidence (each step's ``relationship.derived_from``)
  -- never a claim of causation, responsibility, or truth. Renderers of
  this module's output must preserve that distinction (see
  ``cli.main``'s graph command help text).
- **One shortest path, not all paths.** ``find_path`` never enumerates
  every path between two entities (unbounded path enumeration is
  exponential in general graphs); it returns the single, deterministic,
  fewest-hop chain BFS discovers first, or reports none exists within
  ``max_depth``.

``find_path`` answers "is there a connection, and one example of it";
it cannot answer whether that connection is corroborated by more than
one structurally distinct relationship chain, or rests on a single link
that a single missing/mistaken Relationship would sever entirely. That
is a different, genuinely structural question -- :func:`find_all_shortest_paths`
answers it, without falling into the unbounded-enumeration trap
``find_path``'s docstring above warns about:

- **Shortest-length paths only, never all paths.** Only chains tied for
  the minimum hop count between source and target are considered --
  exactly the same notion of "shortest" ``find_path`` already uses.
  Longer, structurally uninteresting detours are never enumerated.
- **Hard-capped, not merely bounded by depth.** Even restricted to
  shortest length, the number of *tied* chains can still grow quickly
  in a densely-connected graph. ``limit`` (validated, like
  ``max_depth``, against a fixed ceiling) caps how many are ever
  materialized; ``truncated=True`` reports honestly that more exist
  beyond the cap rather than silently returning a partial answer that
  looks complete.
- **No wasted work.** Enumeration runs only over the subgraph already
  known to lie on some shortest source-target chain (found via one
  extra bounded BFS run backward from the target); every branch DFS
  explores is guaranteed to reach the target, so no time is spent on
  dead ends, and the two-BFS-plus-capped-DFS cost stays a small,
  fixed multiple of ``find_path``'s own cost.
- **Corroboration, not confirmation.** Multiple structurally distinct
  shortest chains are a structural fact -- they say the connection does
  not depend on any single Relationship -- never a claim that the
  connection is therefore true, important, or causal. A single chain
  is likewise never reported as suspect; it is simply what the
  evidence currently records.
- **Structural multiplicity is not evidence independence.** Two
  structurally distinct chains -- different Relationships, different
  intermediate entities -- can still cite the very same underlying
  EvidenceItem (e.g. two Relationships both ``derived_from`` the one
  log line that happened to name both connections). Nothing above
  claims otherwise; :func:`analyze_paths_evidence_overlap` is the
  separate, explicit analysis of whether a set of returned chains are
  *also* grounded in disjoint evidence, never conflated with the
  chain-counting this function does.

A third operation, :func:`find_components`, answers a different kind of
question than the two above: not "what is reachable from this one
entity" but "how does the whole case's relationship graph partition into
independent clusters". Load-bearing design decisions specific to it:

- **Weakly connected, not directed.** "Are these two entities part of
  the same cluster" is answered ignoring relationship direction --
  standard graph theory's weakly-connected-components definition, and
  the only sense in which "connected" is well-defined for a whole-graph
  partition (a directed notion, strongly-connected components requiring
  mutual reachability, is a different, harder question this module does
  not answer). This is a deliberate, narrow exception to this module's
  otherwise-universal "directed by default" rule for :func:`find_neighbors`/
  :func:`find_path` -- component membership and point-to-point
  reachability are genuinely different questions, and conflating them
  would be the actual inconsistency.
- **Scoped to entities that actually appear in a relationship.** An
  entity with zero relationships is not part of any component -- it is
  not silently reported as a size-1 component of its own. This keeps
  output meaningful for a case with many entities but sparse
  relationships, and mirrors :func:`find_neighbors`/:func:`find_path`
  already treating an entity with no edges as simply having nothing to
  report.
- **Bounded by case size, like ``correlate.contradictions``/``correlate.gaps``.**
  There is no ``max_depth`` here because there is no traversal depth to
  bound -- this computes the full partition in one O(V+E) pass over
  whatever the case actually contains, exactly as ``detect_time_contradictions``/
  ``find_gaps`` already process their whole store unconditionally. The
  only user-facing bound is ``min_size`` (default 1, show everything),
  a display filter applied after computing the full partition, never a
  correctness-affecting limit.
- **Deterministic without needing a traversal tie-break.** Unlike a
  shortest path, which relationship chain to report between two entities,
  which entities end up in the *same* component is a property of the
  graph alone, independent of traversal order. Determinism here is only
  about *presentation*: components are ordered by their smallest member
  entity id, and entities/relationships within a component are each
  sorted by id -- never by discovery order or incidental storage order.

Explainability (``resolve_evidence_ref``/``resolve_entity``/``explain_relationship``):
every result above already carries a relationship's own id, type,
source/target, and ``derived_from`` id list -- that was already true the
day ``find_neighbors``/``find_path`` shipped. What was still missing was
turning a bare ``derived_from`` id into something a person (or a future
UI) can read without a second, manual lookup: no CLI command anywhere in
this project can show a single EvidenceItem or NormalizedEvent by id.
``resolve_evidence_ref`` closes exactly that gap and nothing more:

- **Pure lookup, never fabrication.** Resolving an id means calling the
  same ``Store.get_evidence``/``get_normalized_event`` every other
  referential-existence check in this codebase already uses (see
  ``cli.main._resolve_evidence_ref``, ``relationships_create``'s own
  validation). Nothing is invented, summarized, or guessed; a
  ``derived_from`` id that names neither is reported as ``"not_found"``
  (a real, if unlikely, possibility -- ``core/`` does not enforce
  referential integrity at construction time, exactly as
  ``Hypothesis.EvidenceRef``'s own docstring already documents), never
  silently dropped or treated as an error.
- **Bounded by the result it explains, not a new traversal.** Explaining
  a path/neighborhood/component resolves only the ids already present in
  that (already depth- or min-size-bounded) result -- one O(1) primary-
  key lookup per id. No new graph walking, no new depth parameter.
- **Opt-in, additive, and never changes existing output.** Every CLI
  command in this module renders exactly as before unless a caller
  explicitly asks for explanation (``--explain``); the JSON shape gains
  extra keys only when asked, so an existing consumer parsing today's
  output is unaffected.
- **Structural fact and provenance fact only, never a forensic
  conclusion.** An explanation says "this relationship is grounded in
  EvidenceItem E, collected via adapter jsonl from source.jsonl:3" -- it
  never says who did something or why, and it never claims two entities
  belong to the same incident merely because a path connects them.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from witnessgraph.core.entities import Entity
from witnessgraph.core.events import NormalizedEvent
from witnessgraph.core.evidence import EvidenceItem
from witnessgraph.core.relationships import Relationship
from witnessgraph.store.base import Store

#: "Neighbors" defaults to direct (one-hop) connections -- the common
#: case -- while still allowing a caller to widen it into a bounded
#: multi-hop neighborhood via --max-depth.
DEFAULT_NEIGHBORS_MAX_DEPTH = 1

#: A path search is generally interested in "is there a plausible, short
#: chain", not the graph's full diameter; 10 hops is a generous default
#: for a hand-curated investigation graph without inviting a search deep
#: enough to be uninterpretable.
DEFAULT_PATH_MAX_DEPTH = 10

#: Hard ceiling on --max-depth for both operations -- defensive input
#: validation (never trust a user-supplied depth unconditionally), not a
#: performance necessity: BFS with a visited set is already O(V+E)
#: regardless of the requested depth, since it can never do more work
#: than the graph actually contains.
MAX_ALLOWED_DEPTH = 50

#: Default cap on how many tied shortest chains find_all_shortest_paths
#: ever materializes -- generous enough to see "a handful of independent
#: chains" without inviting a large response by default.
DEFAULT_PATHS_LIMIT = 10

#: Hard ceiling on --limit -- defensive input validation, same rationale
#: as MAX_ALLOWED_DEPTH: unlike max_depth, this one *does* bound real
#: work (each additional path costs up to max_depth steps of DFS), so it
#: is also a genuine performance safeguard, not only defensive.
MAX_ALLOWED_PATHS_LIMIT = 500


class GraphDirection(str, Enum):
    OUT = "out"
    IN = "in"
    BOTH = "both"


def validate_max_depth(max_depth: int) -> None:
    if not (1 <= max_depth <= MAX_ALLOWED_DEPTH):
        raise ValueError(f"max_depth must be between 1 and {MAX_ALLOWED_DEPTH} (got {max_depth})")


@dataclass(frozen=True)
class TraversalStep:
    """One edge crossed during traversal, from the walk's perspective.

    ``relationship`` is always the stored ``Relationship`` exactly as
    recorded. ``from_entity_id``/``to_entity_id`` describe the walk (which
    can move against the relationship's own arrow under
    ``direction="in"``/``"both"``); ``walked_direction`` makes that
    explicit: ``"forward"`` when ``from_entity_id == relationship.source_entity_id``,
    ``"backward"`` when the edge was followed against its own arrow.
    """

    relationship: Relationship
    from_entity_id: str
    to_entity_id: str
    walked_direction: str  # "forward" | "backward"


@dataclass(frozen=True)
class ReachableEntity:
    entity_id: str
    hop_count: int
    via: TraversalStep


@dataclass(frozen=True)
class NeighborsResult:
    origin_entity_id: str
    direction: GraphDirection
    max_depth: int
    #: Sorted by (hop_count, entity_id); never includes the origin itself.
    reached: tuple[ReachableEntity, ...]


@dataclass(frozen=True)
class PathResult:
    source_entity_id: str
    target_entity_id: str
    direction: GraphDirection
    max_depth: int
    found: bool
    #: Ordered source -> target; empty when source == target (trivially
    #: connected, 0 hops) or when no path was found within max_depth.
    steps: tuple[TraversalStep, ...]

    @property
    def hop_count(self) -> int | None:
        return len(self.steps) if self.found else None


@dataclass(frozen=True)
class AllShortestPathsResult:
    """Every distinct chain tied for shortest between two entities, up to ``limit``.

    See :func:`find_all_shortest_paths` and this module's docstring for
    why this is a different question than :class:`PathResult` answers.
    """

    source_entity_id: str
    target_entity_id: str
    direction: GraphDirection
    max_depth: int
    limit: int
    found: bool
    hop_count: int | None
    #: Each element is one complete source -> target chain (steps in
    #: order), exactly like PathResult.steps. Deterministically ordered
    #: (see find_all_shortest_paths); length <= limit always.
    paths: tuple[tuple[TraversalStep, ...], ...]
    #: True if more tied-shortest chains exist beyond ``limit`` -- the
    #: response is then an honest partial view, never silently complete.
    truncated: bool


@dataclass(frozen=True)
class GraphComponent:
    """One weakly-connected cluster of entities and the relationships joining them.

    ``index`` is this component's position (0-based) among the displayed
    result, ordered by each component's smallest member entity id --
    stable for a given graph and ``min_size``, but not a persistent
    identity (adding a relationship that merges two components, or
    changing ``min_size``, can renumber everything).
    """

    index: int
    entity_ids: tuple[str, ...]  # sorted ascending; every member entity
    relationships: tuple[Relationship, ...]  # sorted by id; every edge joining two members


@dataclass(frozen=True)
class ComponentsResult:
    min_size: int
    #: Every entity that appears as a source or target of at least one
    #: relationship in the case -- the population components partition.
    total_entities_in_graph: int
    total_relationships: int
    #: Component count *before* the min_size filter -- lets a caller
    #: report "N components exist, M meet the threshold" even when M is 0.
    total_components_found: int
    #: Sorted by component.index; only components with
    #: len(entity_ids) >= min_size are included.
    components: tuple[GraphComponent, ...]


@dataclass(frozen=True)
class ResolvedEvidenceRef:
    """One ``Relationship.derived_from`` id, resolved to its stored record.

    ``kind`` is ``"evidence_item"``, ``"normalized_event"``, or
    ``"not_found"`` -- a dangling id (``core/`` does not enforce
    referential integrity at construction time; see this module's
    docstring) is reported, not silently dropped or raised as an error.
    Exactly one of ``evidence_item``/``normalized_event`` is set when
    found; both are ``None`` for ``"not_found"``.
    """

    id: str
    kind: str
    evidence_item: EvidenceItem | None = None
    normalized_event: NormalizedEvent | None = None


@dataclass(frozen=True)
class ResolvedEntity:
    """One entity id, resolved to its stored ``Entity`` record (``None``
    if the id does not name a known entity -- reported, not raised)."""

    entity_id: str
    entity: Entity | None


def resolve_evidence_ref(store: Store, ref_id: str) -> ResolvedEvidenceRef:
    """Resolve one id to its EvidenceItem or NormalizedEvent record.

    Mirrors ``cli.main._resolve_evidence_ref``'s exact lookup order
    (evidence first, then normalized event) -- the same resolution
    strategy already used for Hypothesis's EvidenceRef, applied here to
    a Relationship's derived_from instead.
    """
    evidence = store.get_evidence(ref_id)
    if evidence is not None:
        return ResolvedEvidenceRef(id=ref_id, kind="evidence_item", evidence_item=evidence)
    event = store.get_normalized_event(ref_id)
    if event is not None:
        return ResolvedEvidenceRef(id=ref_id, kind="normalized_event", normalized_event=event)
    return ResolvedEvidenceRef(id=ref_id, kind="not_found")


def resolve_entity(store: Store, entity_id: str) -> ResolvedEntity:
    return ResolvedEntity(entity_id=entity_id, entity=store.get_entity(entity_id))


def explain_relationship(
    store: Store, relationship: Relationship
) -> tuple[ResolvedEvidenceRef, ...]:
    """Resolve every id in ``relationship.derived_from``, in its recorded
    order (never re-sorted -- that order is itself part of the
    relationship's identity, not incidental), to its stored record."""
    return tuple(resolve_evidence_ref(store, ref_id) for ref_id in relationship.derived_from)


def _build_adjacency(
    store: Store,
) -> tuple[dict[str, list[Relationship]], dict[str, list[Relationship]]]:
    """Build (out_adjacency, in_adjacency) once from the store.

    Each entity's edge list is sorted by relationship id -- see this
    module's docstring on determinism.
    """
    out_adj: dict[str, list[Relationship]] = {}
    in_adj: dict[str, list[Relationship]] = {}
    for rel in sorted(store.list_relationships(), key=lambda r: r.id):
        out_adj.setdefault(rel.source_entity_id, []).append(rel)
        in_adj.setdefault(rel.target_entity_id, []).append(rel)
    return out_adj, in_adj


def _steps_from(
    entity_id: str,
    out_adj: dict[str, list[Relationship]],
    in_adj: dict[str, list[Relationship]],
    direction: GraphDirection,
) -> list[TraversalStep]:
    """Every step leaving ``entity_id`` in ``direction``, in a fixed order:
    forward edges (relationship-id order) before backward edges."""
    steps: list[TraversalStep] = []
    if direction in (GraphDirection.OUT, GraphDirection.BOTH):
        for rel in out_adj.get(entity_id, []):
            steps.append(
                TraversalStep(
                    relationship=rel,
                    from_entity_id=entity_id,
                    to_entity_id=rel.target_entity_id,
                    walked_direction="forward",
                )
            )
    if direction in (GraphDirection.IN, GraphDirection.BOTH):
        for rel in in_adj.get(entity_id, []):
            steps.append(
                TraversalStep(
                    relationship=rel,
                    from_entity_id=entity_id,
                    to_entity_id=rel.source_entity_id,
                    walked_direction="backward",
                )
            )
    return steps


def _bfs(
    store: Store,
    origin_entity_id: str,
    *,
    max_depth: int,
    direction: GraphDirection,
) -> dict[str, tuple[int, TraversalStep]]:
    """Breadth-first search from ``origin_entity_id``, bounded to
    ``max_depth`` hops. Returns, for every entity reached (never the
    origin itself), ``(hop_count, step)`` where ``step`` is the
    TraversalStep that first discovered it -- ``step.from_entity_id`` is
    that entity's BFS predecessor, enough to reconstruct a full path by
    walking backward.

    Cycle-safe by construction: an entity is added to ``visited`` (and
    therefore never re-expanded) the first time it is discovered, so a
    relationship cycle of any length is simply not re-traversed, not
    specially detected.
    """
    out_adj, in_adj = _build_adjacency(store)
    discovered: dict[str, tuple[int, TraversalStep]] = {}
    visited = {origin_entity_id}
    frontier = [origin_entity_id]
    depth = 0
    while frontier and depth < max_depth:
        depth += 1
        next_frontier: list[str] = []
        for entity_id in frontier:
            for step in _steps_from(entity_id, out_adj, in_adj, direction):
                if step.to_entity_id in visited:
                    continue
                visited.add(step.to_entity_id)
                discovered[step.to_entity_id] = (depth, step)
                next_frontier.append(step.to_entity_id)
        frontier = next_frontier
    return discovered


def find_neighbors(
    store: Store,
    origin_entity_id: str,
    *,
    max_depth: int = DEFAULT_NEIGHBORS_MAX_DEPTH,
    direction: GraphDirection = GraphDirection.OUT,
) -> NeighborsResult:
    """Every entity reachable from ``origin_entity_id`` within ``max_depth``
    hops, in ``direction``. Does not itself confirm ``origin_entity_id``
    names a real entity -- callers with a Store-backed Case should check
    that first (see ``cli.main``'s "no such entity" handling); an unknown
    id simply has no outgoing/incoming edges and yields an empty result.
    """
    validate_max_depth(max_depth)
    discovered = _bfs(store, origin_entity_id, max_depth=max_depth, direction=direction)
    reached = tuple(
        sorted(
            (
                ReachableEntity(entity_id=eid, hop_count=hop, via=step)
                for eid, (hop, step) in discovered.items()
            ),
            key=lambda r: (r.hop_count, r.entity_id),
        )
    )
    return NeighborsResult(
        origin_entity_id=origin_entity_id,
        direction=direction,
        max_depth=max_depth,
        reached=reached,
    )


def find_path(
    store: Store,
    source_entity_id: str,
    target_entity_id: str,
    *,
    max_depth: int = DEFAULT_PATH_MAX_DEPTH,
    direction: GraphDirection = GraphDirection.OUT,
) -> PathResult:
    """The single, deterministic, fewest-hop relationship chain from
    ``source_entity_id`` to ``target_entity_id``, or ``found=False`` if
    none exists within ``max_depth`` hops (never "no path anywhere in the
    graph" -- only within the searched bound; see this module's
    docstring). ``source_entity_id == target_entity_id`` is a valid
    request, not an error: trivially connected, 0 hops, no steps.
    """
    validate_max_depth(max_depth)
    if source_entity_id == target_entity_id:
        return PathResult(
            source_entity_id=source_entity_id,
            target_entity_id=target_entity_id,
            direction=direction,
            max_depth=max_depth,
            found=True,
            steps=(),
        )
    discovered = _bfs(store, source_entity_id, max_depth=max_depth, direction=direction)
    if target_entity_id not in discovered:
        return PathResult(
            source_entity_id=source_entity_id,
            target_entity_id=target_entity_id,
            direction=direction,
            max_depth=max_depth,
            found=False,
            steps=(),
        )
    chain: list[TraversalStep] = []
    current = target_entity_id
    while current != source_entity_id:
        _hop, step = discovered[current]
        chain.append(step)
        current = step.from_entity_id
    chain.reverse()
    return PathResult(
        source_entity_id=source_entity_id,
        target_entity_id=target_entity_id,
        direction=direction,
        max_depth=max_depth,
        found=True,
        steps=tuple(chain),
    )


def validate_paths_limit(limit: int) -> None:
    if not (1 <= limit <= MAX_ALLOWED_PATHS_LIMIT):
        raise ValueError(f"limit must be between 1 and {MAX_ALLOWED_PATHS_LIMIT} (got {limit})")


def _reverse_direction(direction: GraphDirection) -> GraphDirection:
    """The direction that turns "distance from X" into "distance to X".

    BOTH is its own reverse (an undirected search is symmetric); OUT and
    IN swap, since "how far can I get following outgoing edges from X"
    is exactly "how far can something reach X by following incoming
    edges to X" run from X instead.
    """
    if direction is GraphDirection.OUT:
        return GraphDirection.IN
    if direction is GraphDirection.IN:
        return GraphDirection.OUT
    return GraphDirection.BOTH


def _distance_map(
    store: Store, origin_entity_id: str, *, max_depth: int, direction: GraphDirection
) -> dict[str, int]:
    """``{entity_id: hop_count}`` from ``origin_entity_id``, including the
    origin itself at distance 0 (unlike ``_bfs``, which never reports the
    origin -- callers here need it as a valid, zero-distance member)."""
    discovered = _bfs(store, origin_entity_id, max_depth=max_depth, direction=direction)
    distances = {eid: hop for eid, (hop, _step) in discovered.items()}
    distances[origin_entity_id] = 0
    return distances


def find_all_shortest_paths(
    store: Store,
    source_entity_id: str,
    target_entity_id: str,
    *,
    max_depth: int = DEFAULT_PATH_MAX_DEPTH,
    direction: GraphDirection = GraphDirection.OUT,
    limit: int = DEFAULT_PATHS_LIMIT,
) -> AllShortestPathsResult:
    """Every distinct relationship chain tied for shortest (fewest-hop)
    between ``source_entity_id`` and ``target_entity_id``, within
    ``max_depth`` hops, up to ``limit`` chains.

    Unlike :func:`find_path`, which reports one representative shortest
    chain, this answers "how many *structurally distinct* shortest
    chains connect these two entities, and what are they" -- see this
    module's docstring for why that is a genuinely different,
    still-bounded question. ``source_entity_id == target_entity_id`` is
    trivially connected (one zero-hop path, ``limit`` never applies to
    it), exactly as in :func:`find_path`.

    Deliberately not called "independent": two structurally distinct
    chains (different relationships, different intermediate entities)
    can still cite the very same underlying ``EvidenceItem`` -- see
    :func:`analyze_paths_evidence_overlap` for the separate, store-backed
    analysis of whether the chains this function returns are also
    *evidence*-independent.

    Bounded computation, no exponential blow-up: two BFS passes (forward
    from source, backward from target) restrict enumeration to only the
    edges that actually lie on some shortest chain; depth-first
    enumeration over that pruned subgraph then stops the instant
    ``limit`` chains are found, so cost is bounded by the cost of two
    BFS passes plus ``O(limit * max_depth)`` -- independent of how many
    tied chains the graph may actually contain.
    """
    validate_max_depth(max_depth)
    validate_paths_limit(limit)
    if source_entity_id == target_entity_id:
        return AllShortestPathsResult(
            source_entity_id=source_entity_id,
            target_entity_id=target_entity_id,
            direction=direction,
            max_depth=max_depth,
            limit=limit,
            found=True,
            hop_count=0,
            paths=((),),
            truncated=False,
        )

    dist_from_source = _distance_map(
        store, source_entity_id, max_depth=max_depth, direction=direction
    )
    if target_entity_id not in dist_from_source:
        return AllShortestPathsResult(
            source_entity_id=source_entity_id,
            target_entity_id=target_entity_id,
            direction=direction,
            max_depth=max_depth,
            limit=limit,
            found=False,
            hop_count=None,
            paths=(),
            truncated=False,
        )
    hop_count = dist_from_source[target_entity_id]
    dist_to_target = _distance_map(
        store, target_entity_id, max_depth=max_depth, direction=_reverse_direction(direction)
    )

    def on_some_shortest_chain(entity_id: str) -> bool:
        return (
            entity_id in dist_from_source
            and entity_id in dist_to_target
            and dist_from_source[entity_id] + dist_to_target[entity_id] == hop_count
        )

    out_adj, in_adj = _build_adjacency(store)
    dag_adj: dict[str, list[TraversalStep]] = {}
    for entity_id, from_dist in dist_from_source.items():
        if from_dist >= hop_count or not on_some_shortest_chain(entity_id):
            continue
        next_steps = [
            step
            for step in _steps_from(entity_id, out_adj, in_adj, direction)
            if dist_from_source.get(step.to_entity_id) == from_dist + 1
            and on_some_shortest_chain(step.to_entity_id)
        ]
        next_steps.sort(key=lambda s: (s.to_entity_id, s.relationship.id))
        if next_steps:
            dag_adj[entity_id] = next_steps

    found_paths: list[tuple[TraversalStep, ...]] = []
    current_chain: list[TraversalStep] = []

    def dfs(entity_id: str) -> None:
        if len(found_paths) > limit:
            return
        if entity_id == target_entity_id:
            found_paths.append(tuple(current_chain))
            return
        for step in dag_adj.get(entity_id, []):
            current_chain.append(step)
            dfs(step.to_entity_id)
            current_chain.pop()
            if len(found_paths) > limit:
                return

    dfs(source_entity_id)
    truncated = len(found_paths) > limit
    return AllShortestPathsResult(
        source_entity_id=source_entity_id,
        target_entity_id=target_entity_id,
        direction=direction,
        max_depth=max_depth,
        limit=limit,
        found=True,
        hop_count=hop_count,
        paths=tuple(found_paths[:limit]),
        truncated=truncated,
    )


@dataclass(frozen=True)
class ChainEvidence:
    """One returned chain's own root evidence, resolved for
    :func:`analyze_paths_evidence_overlap`.

    ``chain_index`` is the chain's position in the
    ``AllShortestPathsResult.paths`` tuple it was computed from (0-based,
    stable for that result). ``root_evidence_ids`` is that chain's every
    relationship's ``derived_from`` id, resolved down to the root
    ``EvidenceItem`` id(s) it ultimately traces to (see
    :func:`_resolve_root_evidence_ids`) -- sorted for determinism, never
    the raw, possibly-``NormalizedEvent`` ``derived_from`` ids themselves.
    """

    chain_index: int
    root_evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class PathsEvidenceOverlap:
    """Whether a set of structurally distinct shortest chains (an
    :class:`AllShortestPathsResult`'s ``paths``) are also grounded in
    disjoint evidence -- see :func:`analyze_paths_evidence_overlap`.

    Deliberately a separate result type from ``AllShortestPathsResult``,
    never merged into it: computing this requires resolving
    ``NormalizedEvent`` records via the ``Store`` (a store-backed,
    ``--explain``-style provenance lookup, exactly like
    ``explain_relationship``/``resolve_entity``), whereas
    ``find_all_shortest_paths`` itself only ever needs ``Relationship``/
    adjacency data already loaded once into memory.
    """

    #: One entry per chain in the ``AllShortestPathsResult`` this was
    #: computed from, in the same order (``chains[i].chain_index == i``).
    chains: tuple[ChainEvidence, ...]
    #: Every root EvidenceItem id cited by 2 or more of the chains --
    #: empty when every chain's root evidence is disjoint from every
    #: other's. Sorted for determinism.
    shared_evidence_ids: tuple[str, ...]
    #: True only when there are 2 or more chains and none share any root
    #: evidence id; False when 2+ chains exist and at least one root
    #: evidence id is shared; None when there are fewer than 2 chains --
    #: nothing to compare (0 or 1 chain is neither independent nor
    #: overlapping; the question does not apply).
    fully_evidence_independent: bool | None


def _resolve_root_evidence_ids(store: Store, ref_id: str) -> frozenset[str]:
    """Resolve one ``Relationship.derived_from`` id down to the root
    ``EvidenceItem`` id(s) it ultimately traces to.

    A ``derived_from`` id names either an ``EvidenceItem`` directly
    (already root -- resolves to itself) or a ``NormalizedEvent``, whose
    own ``derived_from`` names the ``EvidenceItem`` id(s) it was built
    from (``core.events``: an ``EvidenceItem`` has no ``derived_from`` of
    its own -- it is always the root; see that module's docstring). A
    dangling id (names neither -- ``core/`` does not enforce referential
    integrity at construction time, exactly as :func:`resolve_evidence_ref`
    already documents) contributes nothing, mirroring that function's own
    ``"not_found"`` handling -- never fabricated, never raised.

    Cycle-safe by construction, like :func:`_bfs`: an id is resolved at
    most once (a visited set), so even hypothetically malformed data
    (e.g. a ``NormalizedEvent`` whose ``derived_from`` names another
    ``NormalizedEvent``, which the current ingest pipeline never
    produces but ``core/`` does not forbid) cannot loop forever --
    termination is structural, not heuristic, exactly as this module's
    docstring already establishes for BFS.
    """
    root_ids: set[str] = set()
    visited: set[str] = set()
    frontier = [ref_id]
    while frontier:
        next_frontier: list[str] = []
        for rid in frontier:
            if rid in visited:
                continue
            visited.add(rid)
            resolved = resolve_evidence_ref(store, rid)
            if resolved.kind == "evidence_item":
                root_ids.add(rid)
            elif resolved.kind == "normalized_event" and resolved.normalized_event is not None:
                next_frontier.extend(resolved.normalized_event.derived_from)
        frontier = next_frontier
    return frozenset(root_ids)


def analyze_paths_evidence_overlap(
    store: Store, result: AllShortestPathsResult
) -> PathsEvidenceOverlap:
    """Are the chains ``result.paths`` also grounded in disjoint evidence?

    Answers the question :func:`find_all_shortest_paths` deliberately
    does not: two structurally distinct chains (different Relationships,
    different intermediate entities) can still cite the very same
    underlying EvidenceItem, in which case counting them as separate
    corroboration would overclaim what the evidence actually supports.
    This resolves each returned chain's relationships' ``derived_from``
    ids down to root EvidenceItem ids and reports, precisely, which
    chains (if any) share one.

    What this means: a root evidence id in ``shared_evidence_ids`` names
    an EvidenceItem that backs two or more of the returned chains --
    those chains' apparent structural corroboration rests, at least in
    part, on the same underlying record. ``fully_evidence_independent``
    is ``True`` only when every returned chain's root evidence is
    disjoint from every other's.

    What this does NOT mean: it never claims a chain is therefore true,
    false, more important, or more trustworthy than another, and it
    never claims disjoint evidence makes a connection "confirmed" --
    only that the records cited are distinct. It also says nothing about
    chains beyond ``result``'s own ``limit``/``truncated`` bound; a
    truncated result's evidence-independence verdict describes only the
    chains actually returned.

    Bounded, not a new traversal: for each of ``result.paths`` (already
    bounded by ``max_depth``/``limit``), this resolves each step's
    already-known ``derived_from`` ids via :func:`_resolve_root_evidence_ids`
    -- no graph traversal, no new depth parameter, cost proportional only
    to the size of the result already computed.
    """
    chains: list[ChainEvidence] = []
    for index, chain in enumerate(result.paths):
        ids: set[str] = set()
        for step in chain:
            for ref_id in step.relationship.derived_from:
                ids |= _resolve_root_evidence_ids(store, ref_id)
        chains.append(ChainEvidence(chain_index=index, root_evidence_ids=tuple(sorted(ids))))

    counts: dict[str, int] = {}
    for chain_evidence in chains:
        for evidence_id in chain_evidence.root_evidence_ids:
            counts[evidence_id] = counts.get(evidence_id, 0) + 1
    shared_evidence_ids = tuple(sorted(eid for eid, count in counts.items() if count >= 2))
    fully_evidence_independent = None if len(chains) < 2 else len(shared_evidence_ids) == 0
    return PathsEvidenceOverlap(
        chains=tuple(chains),
        shared_evidence_ids=shared_evidence_ids,
        fully_evidence_independent=fully_evidence_independent,
    )


def _chain_evidence_to_json(chain_evidence: ChainEvidence) -> dict[str, object]:
    return {
        "chain_index": chain_evidence.chain_index,
        "root_evidence_ids": list(chain_evidence.root_evidence_ids),
    }


def paths_evidence_overlap_to_json(overlap: PathsEvidenceOverlap) -> dict[str, object]:
    return {
        "chains": [_chain_evidence_to_json(c) for c in overlap.chains],
        "shared_evidence_ids": list(overlap.shared_evidence_ids),
        "fully_evidence_independent": overlap.fully_evidence_independent,
    }


def validate_min_size(min_size: int) -> None:
    if min_size < 1:
        raise ValueError(f"min_size must be at least 1 (got {min_size})")


def find_components(store: Store, *, min_size: int = 1) -> ComponentsResult:
    """Partition every entity that appears in at least one relationship
    into weakly-connected clusters (see this module's docstring for why
    "weakly connected" -- ignoring direction -- is the right notion for a
    whole-graph partition, unlike :func:`find_neighbors`/:func:`find_path`).

    ``min_size`` filters the *displayed* components to those with at
    least that many entities (default 1: show everything, including
    isolated pairs); it never changes which entities are computed as
    connected to which -- only which already-computed components are
    included in the result.
    """
    validate_min_size(min_size)
    relationships = sorted(store.list_relationships(), key=lambda r: r.id)
    undirected_adj: dict[str, list[tuple[str, Relationship]]] = {}
    for rel in relationships:
        undirected_adj.setdefault(rel.source_entity_id, []).append(
            (rel.target_entity_id, rel)
        )
        undirected_adj.setdefault(rel.target_entity_id, []).append(
            (rel.source_entity_id, rel)
        )
    for neighbors in undirected_adj.values():
        neighbors.sort(key=lambda pair: (pair[0], pair[1].id))

    all_entity_ids = sorted(undirected_adj.keys())
    visited: set[str] = set()
    raw_components: list[tuple[set[str], set[str]]] = []
    for start in all_entity_ids:
        if start in visited:
            continue
        component_entities = {start}
        component_relationship_ids: set[str] = set()
        visited.add(start)
        frontier = [start]
        while frontier:
            next_frontier: list[str] = []
            for entity_id in frontier:
                for neighbor_id, rel in undirected_adj.get(entity_id, []):
                    component_relationship_ids.add(rel.id)
                    if neighbor_id not in visited:
                        visited.add(neighbor_id)
                        component_entities.add(neighbor_id)
                        next_frontier.append(neighbor_id)
            frontier = next_frontier
        raw_components.append((component_entities, component_relationship_ids))

    raw_components.sort(key=lambda c: min(c[0]))
    rel_by_id = {rel.id: rel for rel in relationships}
    components = tuple(
        GraphComponent(
            index=i,
            entity_ids=tuple(sorted(entity_ids)),
            relationships=tuple(rel_by_id[rid] for rid in sorted(relationship_ids)),
        )
        for i, (entity_ids, relationship_ids) in enumerate(
            c for c in raw_components if len(c[0]) >= min_size
        )
    )
    return ComponentsResult(
        min_size=min_size,
        total_entities_in_graph=len(all_entity_ids),
        total_relationships=len(relationships),
        total_components_found=len(raw_components),
        components=components,
    )


def _evidence_item_to_json(item: EvidenceItem) -> dict[str, object]:
    return {
        "id": item.id,
        "source_adapter": item.source_adapter,
        "adapter_version": item.adapter_version,
        "source_locator": item.source_locator,
        "raw_size_bytes": item.raw_size_bytes,
        "collected_at": item.collected_at,
        "observed_at": item.observed_at,
    }


def _normalized_event_to_json(event: NormalizedEvent) -> dict[str, object]:
    return {
        "id": event.id,
        "event_type": event.event_type,
        "attributes": dict(event.attributes),
        "derived_from": list(event.derived_from),
    }


def _resolved_evidence_ref_to_json(ref: ResolvedEvidenceRef) -> dict[str, object]:
    return {
        "id": ref.id,
        "kind": ref.kind,
        "evidence_item": (
            _evidence_item_to_json(ref.evidence_item) if ref.evidence_item is not None else None
        ),
        "normalized_event": (
            _normalized_event_to_json(ref.normalized_event)
            if ref.normalized_event is not None
            else None
        ),
    }


def _resolved_entity_to_json(resolved: ResolvedEntity) -> dict[str, object]:
    entity = resolved.entity
    return {
        "entity_id": resolved.entity_id,
        "found": entity is not None,
        "entity_type": entity.entity_type if entity is not None else None,
        "identifiers": dict(entity.identifiers) if entity is not None else None,
    }


def _relationship_to_json(rel: Relationship, *, store: Store | None = None) -> dict[str, object]:
    """``store`` is optional and additive only: when given (``--explain``),
    an extra ``evidence_lineage`` key resolves every ``derived_from`` id to
    its stored record (see :func:`explain_relationship`); omitting it
    reproduces the exact JSON shape from before this capability existed."""
    doc: dict[str, object] = {
        "id": rel.id,
        "relationship_type": rel.relationship_type,
        "source_entity_id": rel.source_entity_id,
        "target_entity_id": rel.target_entity_id,
        "attributes": dict(rel.attributes),
        "derived_from": list(rel.derived_from),
    }
    if store is not None:
        doc["evidence_lineage"] = [
            _resolved_evidence_ref_to_json(ref) for ref in explain_relationship(store, rel)
        ]
    return doc


def resolved_evidence_ref_to_json(ref: ResolvedEvidenceRef) -> dict[str, object]:
    """Public entry point for :func:`_resolved_evidence_ref_to_json`.

    Exists for the same reason as :func:`relationship_to_json`: a caller
    outside this module (the service layer's ``evidence_service``, which
    resolves an ``Entity.derived_from`` id the same way a relationship's
    own lineage already resolves ``Relationship.derived_from``) needs a
    supported way to serialize one resolved reference.
    """
    return _resolved_evidence_ref_to_json(ref)


def relationship_to_json(rel: Relationship, *, store: Store | None = None) -> dict[str, object]:
    """Public entry point for :func:`_relationship_to_json`.

    Every existing caller inside this module keeps using the private
    name; this alias exists so a caller outside ``correlate.graph`` (the
    service layer, in particular) has a supported way to serialize one
    ``Relationship`` -- including its resolved ``evidence_lineage`` when
    ``store`` is given -- without duplicating this function's field list.
    """
    return _relationship_to_json(rel, store=store)


def _step_to_json(step: TraversalStep, *, store: Store | None = None) -> dict[str, object]:
    return {
        "from_entity_id": step.from_entity_id,
        "to_entity_id": step.to_entity_id,
        "walked_direction": step.walked_direction,
        "relationship": _relationship_to_json(step.relationship, store=store),
    }


def _entities_json(store: Store, entity_ids: set[str]) -> dict[str, object]:
    """A ``{entity_id: resolved_entity}`` map, keys sorted, for every id in
    ``entity_ids`` -- the same additive, ``--explain``-only augmentation
    ``_relationship_to_json`` applies to relationships, applied to the
    entities participating in a result."""
    return {
        entity_id: _resolved_entity_to_json(resolve_entity(store, entity_id))
        for entity_id in sorted(entity_ids)
    }


def neighbors_result_to_json(
    result: NeighborsResult, *, store: Store | None = None
) -> dict[str, object]:
    """A plain dict/list tree for ``result`` -- pass to
    ``core.ids.canonical_json_bytes`` for deterministic encoding, exactly
    like ``report.render_json``'s builders. ``store`` is optional and
    additive only -- see :func:`_relationship_to_json`."""
    doc: dict[str, object] = {
        "origin_entity_id": result.origin_entity_id,
        "direction": result.direction.value,
        "max_depth": result.max_depth,
        "reached": [
            {
                "entity_id": r.entity_id,
                "hop_count": r.hop_count,
                "via": _step_to_json(r.via, store=store),
            }
            for r in result.reached
        ],
    }
    if store is not None:
        entity_ids = {result.origin_entity_id} | {r.entity_id for r in result.reached}
        doc["entities"] = _entities_json(store, entity_ids)
    return doc


def path_result_to_json(result: PathResult, *, store: Store | None = None) -> dict[str, object]:
    doc: dict[str, object] = {
        "source_entity_id": result.source_entity_id,
        "target_entity_id": result.target_entity_id,
        "direction": result.direction.value,
        "max_depth": result.max_depth,
        "found": result.found,
        "hop_count": result.hop_count,
        "steps": [_step_to_json(step, store=store) for step in result.steps],
    }
    if store is not None:
        entity_ids = {result.source_entity_id, result.target_entity_id}
        for step in result.steps:
            entity_ids.add(step.from_entity_id)
            entity_ids.add(step.to_entity_id)
        doc["entities"] = _entities_json(store, entity_ids)
    return doc


def all_shortest_paths_result_to_json(
    result: AllShortestPathsResult, *, store: Store | None = None
) -> dict[str, object]:
    doc: dict[str, object] = {
        "source_entity_id": result.source_entity_id,
        "target_entity_id": result.target_entity_id,
        "direction": result.direction.value,
        "max_depth": result.max_depth,
        "limit": result.limit,
        "found": result.found,
        "hop_count": result.hop_count,
        "truncated": result.truncated,
        "paths": [
            [_step_to_json(step, store=store) for step in chain] for chain in result.paths
        ],
    }
    if store is not None:
        entity_ids = {result.source_entity_id, result.target_entity_id}
        for chain in result.paths:
            for step in chain:
                entity_ids.add(step.from_entity_id)
                entity_ids.add(step.to_entity_id)
        doc["entities"] = _entities_json(store, entity_ids)
        doc["evidence_independence"] = paths_evidence_overlap_to_json(
            analyze_paths_evidence_overlap(store, result)
        )
    return doc


def components_result_to_json(
    result: ComponentsResult, *, store: Store | None = None
) -> dict[str, object]:
    doc: dict[str, object] = {
        "min_size": result.min_size,
        "total_entities_in_graph": result.total_entities_in_graph,
        "total_relationships": result.total_relationships,
        "total_components_found": result.total_components_found,
        "components": [
            {
                "index": component.index,
                "entity_ids": list(component.entity_ids),
                "relationships": [
                    _relationship_to_json(rel, store=store) for rel in component.relationships
                ],
            }
            for component in result.components
        ],
    }
    if store is not None:
        entity_ids = {eid for component in result.components for eid in component.entity_ids}
        doc["entities"] = _entities_json(store, entity_ids)
    return doc
