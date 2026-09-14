import { useQuery } from '@tanstack/react-query'
import type { LayoutOptions } from 'cytoscape'
import { useMemo, useState } from 'react'
import { getNeighbors } from '../api/client'
import type { Entity, GraphComponent, Relationship, ResolvedEntity, TraversalStep } from '../api/types'
import { CytoscapeGraph } from './CytoscapeGraph'
import {
  componentElements,
  egoNetworkElements,
  fullGraphElements,
  pathOverlayElements,
  withHighlightClasses,
} from './elements'
import { baseStylesheet } from './stylesheet'

/** Above this many entities, "show the whole case" becomes an explicit,
 * warned opt-in rather than the default -- §16's "no premature
 * optimization, but the engine's own bounds are the first line of
 * defense" applied to what the frontend renders by default. */
const FULL_GRAPH_WARNING_THRESHOLD = 60

export interface PathOverlay {
  chains: TraversalStep[][]
  entities?: Record<string, ResolvedEntity>
}

interface GraphPanelProps {
  entities: Entity[]
  relationships: Relationship[]
  selectedEntityId: string | null
  selectedRelationshipId: string | null
  onSelectEntity: (id: string | null) => void
  onSelectRelationship: (id: string | null) => void
  pathOverlay: PathOverlay | null
  onClearOverlay: () => void
  focusComponent: GraphComponent | null
  focusComponentEntities?: Record<string, ResolvedEntity>
  onClearComponent: () => void
}

export function GraphPanel({
  entities,
  relationships,
  selectedEntityId,
  selectedRelationshipId,
  onSelectEntity,
  onSelectRelationship,
  pathOverlay,
  onClearOverlay,
  focusComponent,
  focusComponentEntities,
  onClearComponent,
}: GraphPanelProps) {
  const [mode, setMode] = useState<'full' | 'ego'>(
    entities.length <= FULL_GRAPH_WARNING_THRESHOLD ? 'full' : 'ego',
  )
  const [egoDepth, setEgoDepth] = useState(1)
  const [forceFull, setForceFull] = useState(false)

  const effectiveMode: 'full' | 'ego' | 'path' | 'component' = pathOverlay
    ? 'path'
    : focusComponent
      ? 'component'
      : mode

  const neighborsQuery = useQuery({
    queryKey: ['neighbors', selectedEntityId, egoDepth],
    queryFn: () => getNeighbors({ entityId: selectedEntityId as string, maxDepth: egoDepth }),
    enabled: effectiveMode === 'ego' && selectedEntityId !== null,
  })

  const { elements, edgeChainClasses } = useMemo(() => {
    if (effectiveMode === 'path' && pathOverlay) {
      return pathOverlayElements(pathOverlay.chains, pathOverlay.entities)
    }
    if (effectiveMode === 'component' && focusComponent) {
      return { elements: componentElements(focusComponent, focusComponentEntities), edgeChainClasses: {} }
    }
    if (effectiveMode === 'ego' && selectedEntityId && neighborsQuery.data) {
      return { elements: egoNetworkElements(neighborsQuery.data), edgeChainClasses: {} }
    }
    if (effectiveMode === 'ego') {
      return { elements: [], edgeChainClasses: {} }
    }
    return { elements: fullGraphElements(entities, relationships), edgeChainClasses: {} }
  }, [
    effectiveMode,
    pathOverlay,
    focusComponent,
    focusComponentEntities,
    selectedEntityId,
    neighborsQuery.data,
    entities,
    relationships,
  ])

  const styledElements = useMemo(
    () =>
      withHighlightClasses(elements, {
        selectedId: selectedEntityId ?? selectedRelationshipId,
        edgeChainClasses,
      }),
    [elements, selectedEntityId, selectedRelationshipId, edgeChainClasses],
  )

  const layout: LayoutOptions = useMemo(() => {
    if (effectiveMode === 'ego' && selectedEntityId) {
      return { name: 'breadthfirst', directed: true, spacingFactor: 1.3, roots: `#${selectedEntityId}` } as LayoutOptions
    }
    if (effectiveMode === 'path' || effectiveMode === 'component') {
      return { name: 'breadthfirst', directed: true, spacingFactor: 1.3 } as LayoutOptions
    }
    return { name: 'grid', spacingFactor: 1.1 } as LayoutOptions
  }, [effectiveMode, selectedEntityId])

  const showLargeGraphWarning =
    mode === 'full' &&
    !pathOverlay &&
    !focusComponent &&
    entities.length > FULL_GRAPH_WARNING_THRESHOLD &&
    !forceFull

  const modeLabel = pathOverlay
    ? `Analytical overlay: ${pathOverlay.chains.length} chain(s)`
    : focusComponent
      ? `Component ${focusComponent.index + 1} (${focusComponent.entity_ids.length} entities)`
      : mode === 'ego'
        ? `Ego network (depth ${egoDepth})`
        : 'Full case graph'

  return (
    <div className="graph-panel">
      <div className="graph-controls">
        <span className="graph-mode-label" data-testid="graph-mode-label">
          {modeLabel}
        </span>
        {pathOverlay && (
          <button type="button" onClick={onClearOverlay}>
            Clear path overlay -- return to graph context
          </button>
        )}
        {!pathOverlay && focusComponent && (
          <button type="button" onClick={onClearComponent}>
            Clear component focus -- return to graph context
          </button>
        )}
        {!pathOverlay && !focusComponent && mode === 'ego' && (
          <>
            <label>
              Depth
              <input
                type="number"
                min={1}
                max={10}
                value={egoDepth}
                onChange={(event) => setEgoDepth(Number(event.target.value))}
              />
            </label>
            <button
              type="button"
              onClick={() => {
                setMode('full')
                onSelectEntity(null)
              }}
            >
              Show full graph
            </button>
          </>
        )}
        {!pathOverlay && !focusComponent && mode === 'full' && selectedEntityId && (
          <button type="button" onClick={() => setMode('ego')}>
            Focus on selected entity
          </button>
        )}
      </div>
      {showLargeGraphWarning ? (
        <div className="graph-warning">
          This case has {entities.length} entities -- rendering all of them at once may be slow.
          <button type="button" onClick={() => setForceFull(true)}>
            Show full graph anyway
          </button>
        </div>
      ) : elements.length === 0 ? (
        <div className="graph-warning">
          {effectiveMode === 'ego'
            ? 'Select an entity to explore its neighborhood.'
            : 'Nothing to render yet -- this case has no entities.'}
        </div>
      ) : (
        <CytoscapeGraph
          elements={styledElements}
          stylesheet={baseStylesheet}
          layout={layout}
          onSelectNode={onSelectEntity}
          onSelectEdge={onSelectRelationship}
        />
      )}
    </div>
  )
}
