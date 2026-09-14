import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { getPath, getPaths } from '../api/client'
import type { AllShortestPathsResult, Entity, GraphDirection, PathResult } from '../api/types'
import { displayLabel } from '../graph/elements'
import type { PathOverlay } from '../graph/GraphPanel'
import { EvidenceIndependencePanel } from './EvidenceIndependencePanel'

interface PathExplorerProps {
  entities: Entity[]
  onOverlay: (overlay: PathOverlay | null) => void
}

export function PathExplorer({ entities, onOverlay }: PathExplorerProps) {
  const sorted = [...entities].sort((a, b) => (a.id < b.id ? -1 : 1))
  const [sourceId, setSourceId] = useState(sorted[0]?.id ?? '')
  const [targetId, setTargetId] = useState(sorted[1]?.id ?? sorted[0]?.id ?? '')
  const [direction, setDirection] = useState<GraphDirection>('out')
  const [maxDepth, setMaxDepth] = useState(10)
  const [limit, setLimit] = useState(10)
  const [pathResult, setPathResult] = useState<PathResult | null>(null)
  const [pathsResult, setPathsResult] = useState<AllShortestPathsResult | null>(null)

  const pathMutation = useMutation({
    mutationFn: () => getPath({ sourceEntityId: sourceId, targetEntityId: targetId, maxDepth, direction }),
    onSuccess: (result) => {
      setPathResult(result)
      setPathsResult(null)
      if (result.found && result.steps.length > 0) {
        onOverlay({ chains: [result.steps], entities: result.entities })
      } else {
        onOverlay(null)
      }
    },
  })

  const pathsMutation = useMutation({
    mutationFn: () => getPaths({ sourceEntityId: sourceId, targetEntityId: targetId, maxDepth, direction, limit }),
    onSuccess: (result) => {
      setPathsResult(result)
      setPathResult(null)
      if (result.found && result.paths.some((chain) => chain.length > 0)) {
        onOverlay({ chains: result.paths, entities: result.entities })
      } else {
        onOverlay(null)
      }
    },
  })

  const error = pathMutation.error ?? pathsMutation.error

  return (
    <div className="path-explorer" data-testid="path-explorer">
      <h3>Graph path / tied-shortest-paths</h3>
      <div className="path-controls">
        <label>
          Source
          <select value={sourceId} onChange={(e) => setSourceId(e.target.value)}>
            {sorted.map((e) => (
              <option key={e.id} value={e.id}>
                {displayLabel(e)}
              </option>
            ))}
          </select>
        </label>
        <label>
          Target
          <select value={targetId} onChange={(e) => setTargetId(e.target.value)}>
            {sorted.map((e) => (
              <option key={e.id} value={e.id}>
                {displayLabel(e)}
              </option>
            ))}
          </select>
        </label>
        <label>
          Direction
          <select value={direction} onChange={(e) => setDirection(e.target.value as GraphDirection)}>
            <option value="out">out</option>
            <option value="in">in</option>
            <option value="both">both</option>
          </select>
        </label>
        <label>
          Max depth
          <input type="number" min={1} max={50} value={maxDepth} onChange={(e) => setMaxDepth(Number(e.target.value))} />
        </label>
        <label>
          Limit (paths only)
          <input type="number" min={1} max={500} value={limit} onChange={(e) => setLimit(Number(e.target.value))} />
        </label>
      </div>
      <div className="path-actions">
        <button type="button" disabled={!sourceId || !targetId} onClick={() => pathMutation.mutate()}>
          Find shortest path
        </button>
        <button type="button" disabled={!sourceId || !targetId} onClick={() => pathsMutation.mutate()}>
          Find all tied-shortest chains
        </button>
      </div>
      {error && <p className="error-text">{(error as Error).message}</p>}
      {pathResult && (
        <div className="path-result" data-testid="path-result">
          {pathResult.found ? (
            <p>
              Path found: {pathResult.hop_count} hop(s). Highlighted in the graph above.
            </p>
          ) : (
            <p>
              No path found from <code>{sourceId}</code> to <code>{targetId}</code> within{' '}
              {maxDepth} hop(s) (direction={direction}).
            </p>
          )}
        </div>
      )}
      {pathsResult && (
        <div className="paths-result" data-testid="paths-result">
          {pathsResult.found ? (
            <>
              <p>
                {pathsResult.paths.length} shortest chain(s) found, {pathsResult.hop_count} hop(s)
                each{pathsResult.truncated ? ' -- more exist beyond the limit' : ''}.
              </p>
              <EvidenceIndependencePanel result={pathsResult} />
            </>
          ) : (
            <p>
              No path found from <code>{sourceId}</code> to <code>{targetId}</code> within{' '}
              {maxDepth} hop(s) (direction={direction}).
            </p>
          )}
        </div>
      )}
    </div>
  )
}
