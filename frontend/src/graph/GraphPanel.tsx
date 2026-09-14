import { useQuery } from '@tanstack/react-query'
import type { LayoutOptions } from 'cytoscape'
import { useMemo, useState } from 'react'
import { getNeighbors } from '../api/client'
import type { Entity, Relationship, ResolvedEntity, TraversalStep } from '../api/types'
import { CytoscapeGraph } from './CytoscapeGraph'
import { egoNetworkElements, fullGraphElements, pathOverlayElements, withHighlightClasses } from './elements'
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
}: GraphPanelProps) {
  const [mode, setMode] = useState<'full' | 'ego'>(
    entities.length <= FULL_GRAPH_WARNING_THRESHOLD ? 'full' : 'ego',
  )
  const [egoDepth, setEgoDepth] = useState(1)
  const [forceFull, setForceFull] = useState(false)

  const effectiveMode: 'full' | 'ego' | 'path' = pathOverlay ? 'path' : mode

  const neighborsQuery = useQuery({
    queryKey: ['neighbors', selectedEntityId, egoDepth],
    queryFn: () => getNeighbors({ entityId: selectedEntityId as string, maxDepth: egoDepth }),
    enabled: effectiveMode === 'ego' && selectedEntityId !== null,
  })

  const { elements, edgeChainClasses } = useMemo(() => {
    if (effectiveMode === 'path' && pathOverlay) {
      return pathOverlayElements(pathOverlay.chains, pathOverlay.entities)
    }
    if (effectiveMode === 'ego' && selectedEntityId && neighborsQuery.data) {
      return { elements: egoNetworkElements(neighborsQuery.data), edgeChainClasses: {} }
    }
    if (effectiveMode === 'ego') {
      return { elements: [], edgeChainClasses: {} }
    }
    return { elements: fullGraphElements(entities, relationships), edgeChainClasses: {} }
  }, [effectiveMode, pathOverlay, selectedEntityId, neighborsQuery.data, entities, relationships])

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
    if (effectiveMode === 'path') {
      return { name: 'breadthfirst', directed: true, spacingFactor: 1.3 } as LayoutOptions
    }
    return { name: 'grid', spacingFactor: 1.1 } as LayoutOptions
  }, [effectiveMode, selectedEntityId])

  const showLargeGraphWarning =
    mode === 'full' && !pathOverlay && entities.length > FULL_GRAPH_WARNING_THRESHOLD && !forceFull

  return (
    <div className="graph-panel">
      <div className="graph-controls">
        <span className="graph-mode-label" data-testid="graph-mode-label">
          {pathOverlay
            ? `Analytical overlay: ${pathOverlay.chains.length} chain(s)`
            : mode === 'ego'
              ? `Ego network (depth ${egoDepth})`
              : 'Full case graph'}
        </span>
        {pathOverlay && (
          <button type="button" onClick={onClearOverlay}>
            Clear overlay -- return to graph context
          </button>
        )}
        {!pathOverlay && mode === 'ego' && (
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
        {!pathOverlay && mode === 'full' && selectedEntityId && (
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
