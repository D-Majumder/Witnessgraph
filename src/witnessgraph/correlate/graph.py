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
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

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


def _relationship_to_json(rel: Relationship) -> dict[str, object]:
    return {
        "id": rel.id,
        "relationship_type": rel.relationship_type,
        "source_entity_id": rel.source_entity_id,
        "target_entity_id": rel.target_entity_id,
        "attributes": dict(rel.attributes),
        "derived_from": list(rel.derived_from),
    }


def _step_to_json(step: TraversalStep) -> dict[str, object]:
    return {
        "from_entity_id": step.from_entity_id,
        "to_entity_id": step.to_entity_id,
        "walked_direction": step.walked_direction,
        "relationship": _relationship_to_json(step.relationship),
    }


def neighbors_result_to_json(result: NeighborsResult) -> dict[str, object]:
    """A plain dict/list tree for ``result`` -- pass to
    ``core.ids.canonical_json_bytes`` for deterministic encoding, exactly
    like ``report.render_json``'s builders."""
    return {
        "origin_entity_id": result.origin_entity_id,
        "direction": result.direction.value,
        "max_depth": result.max_depth,
        "reached": [
            {
                "entity_id": r.entity_id,
                "hop_count": r.hop_count,
                "via": _step_to_json(r.via),
            }
            for r in result.reached
        ],
    }


def path_result_to_json(result: PathResult) -> dict[str, object]:
    return {
        "source_entity_id": result.source_entity_id,
        "target_entity_id": result.target_entity_id,
        "direction": result.direction.value,
        "max_depth": result.max_depth,
        "found": result.found,
        "hop_count": result.hop_count,
        "steps": [_step_to_json(step) for step in result.steps],
    }


def components_result_to_json(result: ComponentsResult) -> dict[str, object]:
    return {
        "min_size": result.min_size,
        "total_entities_in_graph": result.total_entities_in_graph,
        "total_relationships": result.total_relationships,
        "total_components_found": result.total_components_found,
        "components": [
            {
                "index": component.index,
                "entity_ids": list(component.entity_ids),
                "relationships": [_relationship_to_json(rel) for rel in component.relationships],
            }
            for component in result.components
        ],
    }
