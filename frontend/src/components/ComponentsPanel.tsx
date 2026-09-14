// Connected-components browse list. Renders exactly the existing
// GET /graph/components result -- no recomputation in TypeScript.

import { useQuery } from '@tanstack/react-query'
import { getComponents } from '../api/client'
import type { GraphComponent, ResolvedEntity } from '../api/types'

export function ComponentsPanel({
  focusedIndex,
  onFocus,
}: {
  focusedIndex: number | null
  onFocus: (component: GraphComponent | null, entities?: Record<string, ResolvedEntity>) => void
}) {
  const query = useQuery({ queryKey: ['components'], queryFn: () => getComponents() })

  if (query.isLoading) return <p>Loading components...</p>
  if (query.isError) return <p className="error-text">{(query.error as Error).message}</p>
  if (!query.data) return null

  return (
    <div className="browse-list" data-testid="components-list">
      <p className="provenance-caption">
        Weakly-connected clusters (direction-independent -- a different notion of "connected"
        than the directed graph view).
      </p>
      {query.data.total_components_found === 0 && (
        <p className="empty-note">No components -- this case has no relationships yet.</p>
      )}
      <ul>
        {query.data.components.map((component) => (
          <li key={component.index}>
            <button
              type="button"
              className={component.index === focusedIndex ? 'selected' : ''}
              onClick={() =>
                onFocus(
                  component.index === focusedIndex ? null : component,
                  query.data.entities,
                )
              }
            >
              Component {component.index + 1}: {component.entity_ids.length} entities,{' '}
              {component.relationships.length} relationships
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
