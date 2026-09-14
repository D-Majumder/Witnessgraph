// Builds Cytoscape.js `{data:{...}}` elements directly from Entity/
// Relationship records -- never a second "node"/"edge" schema (see
// docs/phase-ui-v1-architecture-design.md §15: "no second graph model").
// Every field on a produced element is traceable 1:1 back to the
// Entity/Relationship it came from; nothing here is synthesized.

import type { ElementDefinition } from 'cytoscape'
import type {
  Entity,
  GraphComponent,
  NeighborsResult,
  Relationship,
  ResolvedEntity,
  TraversalStep,
} from '../api/types'

export function displayLabel(entity: Pick<Entity, 'entity_type' | 'identifiers' | 'id'>): string {
  const keys = Object.keys(entity.identifiers)
  if (keys.length === 0) return `${entity.entity_type}:${entity.id.slice(0, 8)}`
  // Prefer a small set of conventional identifier keys per entity_type
  // when present; otherwise fall back to the first identifier -- a
  // display heuristic only, never a new domain concept (§7).
  const preferredKeys = ['hostname', 'ip', 'username', 'hash', 'domain', 'name']
  const key = preferredKeys.find((k) => k in entity.identifiers) ?? keys.sort()[0]
  return `${entity.entity_type}: ${entity.identifiers[key]}`
}

export function entityToElement(entity: Entity): ElementDefinition {
  return {
    data: {
      id: entity.id,
      label: displayLabel(entity),
      entity_type: entity.entity_type,
    },
    classes: `entity-type-${sanitizeClass(entity.entity_type)}`,
  }
}

export function relationshipToElement(rel: Relationship): ElementDefinition {
  return {
    data: {
      id: rel.id,
      source: rel.source_entity_id,
      target: rel.target_entity_id,
      label: rel.relationship_type,
      relationship_type: rel.relationship_type,
    },
  }
}

function sanitizeClass(value: string): string {
  return value.replace(/[^a-zA-Z0-9_-]/g, '_')
}

function byId<T extends { id: string }>(a: T, b: T): number {
  return a.id < b.id ? -1 : a.id > b.id ? 1 : 0
}

/** Every element map below is emitted sorted by id -- a `grid`/
 * `breadthfirst` Cytoscape layout places elements in the order they were
 * added, so this is what makes rendering deterministic across reloads of
 * the same underlying case data (§7's determinism requirement), not an
 * incidental detail. */
function sortedById(elements: ElementDefinition[]): ElementDefinition[] {
  return [...elements].sort((a, b) => byId({ id: a.data.id as string }, { id: b.data.id as string }))
}

/** Build elements for the full-case graph directly from the already-fetched
 * entity/relationship lists -- no extra request. */
export function fullGraphElements(entities: Entity[], relationships: Relationship[]): ElementDefinition[] {
  const nodes = [...entities].sort(byId).map(entityToElement)
  const edges = [...relationships].sort(byId).map(relationshipToElement)
  return [...nodes, ...edges]
}

function resolvedEntityToElement(entityId: string, resolved: ResolvedEntity | undefined): ElementDefinition {
  if (!resolved || !resolved.found) {
    return { data: { id: entityId, label: entityId, entity_type: 'unknown' } }
  }
  return {
    data: {
      id: entityId,
      label: displayLabel({
        id: entityId,
        entity_type: resolved.entity_type ?? 'unknown',
        identifiers: resolved.identifiers ?? {},
      }),
      entity_type: resolved.entity_type ?? 'unknown',
    },
    classes: `entity-type-${sanitizeClass(resolved.entity_type ?? 'unknown')}`,
  }
}

/** Build elements for a bounded ego-network from a NeighborsResult --
 * the API always resolves `entities` (§14), so every node gets its real
 * type/identifiers, never a synthesized placeholder. */
export function egoNetworkElements(result: NeighborsResult): ElementDefinition[] {
  const nodeById = new Map<string, ElementDefinition>()
  const resolved = result.entities ?? {}
  nodeById.set(result.origin_entity_id, resolvedEntityToElement(result.origin_entity_id, resolved[result.origin_entity_id]))
  const edgeById = new Map<string, ElementDefinition>()
  for (const r of result.reached) {
    if (!nodeById.has(r.entity_id)) {
      nodeById.set(r.entity_id, resolvedEntityToElement(r.entity_id, resolved[r.entity_id]))
    }
    const rel = r.via.relationship
    if (!edgeById.has(rel.id)) {
      edgeById.set(rel.id, relationshipToElement(rel))
    }
  }
  return sortedById([...nodeById.values(), ...edgeById.values()])
}

/** Build elements for one focused GraphComponent (from GET /graph/components,
 * always explain-resolved) -- renders exactly that weakly-connected
 * cluster's own entities/relationships, nothing recomputed. */
export function componentElements(
  component: GraphComponent,
  entities: Record<string, ResolvedEntity> | undefined,
): ElementDefinition[] {
  const nodes = component.entity_ids.map((id) => resolvedEntityToElement(id, entities?.[id]))
  const edges = component.relationships.map(relationshipToElement)
  return sortedById([...nodes, ...edges])
}

/** Build elements for a path/tied-shortest-paths overlay: the union of
 * every entity/relationship appearing in any returned chain, plus a
 * per-edge-id list of chain classes (an edge shared by two chains gets
 * both -- a real, visible signal of shared structure, never hidden). */
export function pathOverlayElements(
  chains: TraversalStep[][],
  entities: Record<string, ResolvedEntity> | undefined,
): { elements: ElementDefinition[]; edgeChainClasses: Record<string, string[]> } {
  const nodeById = new Map<string, ElementDefinition>()
  const edgeById = new Map<string, ElementDefinition>()
  const edgeChainClasses: Record<string, string[]> = {}
  chains.forEach((chain, chainIndex) => {
    const cls = chainClass(chainIndex)
    for (const step of chain) {
      if (!nodeById.has(step.from_entity_id)) {
        nodeById.set(
          step.from_entity_id,
          resolvedEntityToElement(step.from_entity_id, entities?.[step.from_entity_id]),
        )
      }
      if (!nodeById.has(step.to_entity_id)) {
        nodeById.set(
          step.to_entity_id,
          resolvedEntityToElement(step.to_entity_id, entities?.[step.to_entity_id]),
        )
      }
      const rel = step.relationship
      if (!edgeById.has(rel.id)) {
        edgeById.set(rel.id, relationshipToElement(rel))
      }
      edgeChainClasses[rel.id] = [...(edgeChainClasses[rel.id] ?? []), cls]
    }
  })
  return { elements: sortedById([...nodeById.values(), ...edgeById.values()]), edgeChainClasses }
}

/** Chain-index -> a stable set of Cytoscape classes for highlighting a
 * tied-shortest-path overlay, one class per chain, distinct from the base
 * "context" styling (§7: "clear distinction between the selected graph
 * context and analytical overlays"). */
export function chainClass(index: number): string {
  return `path-chain-${index % PATH_CHAIN_COLORS.length}`
}

/** Overlay `.wg-selected` (the node/edge currently open in the detail
 * panel) and any per-edge chain classes onto a base element list, without
 * mutating the inputs -- keeps "selected" and "path overlay" visually
 * distinct concepts (§7) that can both apply to the same element. */
export function withHighlightClasses(
  elements: ElementDefinition[],
  options: {
    selectedId?: string | null
    edgeChainClasses?: Record<string, string[]>
  },
): ElementDefinition[] {
  return elements.map((el) => {
    const id = el.data.id as string
    const existing = Array.isArray(el.classes) ? el.classes.join(' ') : (el.classes ?? '')
    const classes = new Set(existing.split(' ').filter(Boolean))
    if (options.selectedId && id === options.selectedId) classes.add('wg-selected')
    for (const cls of options.edgeChainClasses?.[id] ?? []) classes.add(cls)
    return { ...el, classes: [...classes].join(' ') }
  })
}

export const PATH_CHAIN_COLORS = [
  '#e6550d', // orange
  '#3182bd', // blue
  '#31a354', // green
  '#d62728', // red
  '#9467bd', // purple
  '#8c564b', // brown
]
