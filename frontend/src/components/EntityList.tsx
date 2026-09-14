import { useState } from 'react'
import type { Entity } from '../api/types'
import { displayLabel } from '../graph/elements'

export function EntityList({
  entities,
  selectedEntityId,
  onSelect,
}: {
  entities: Entity[]
  selectedEntityId: string | null
  onSelect: (id: string) => void
}) {
  const [filter, setFilter] = useState('')
  const sorted = [...entities].sort((a, b) => (a.id < b.id ? -1 : 1))
  const visible = filter
    ? sorted.filter(
        (e) =>
          e.entity_type.toLowerCase().includes(filter.toLowerCase()) ||
          Object.values(e.identifiers).some((v) => v.toLowerCase().includes(filter.toLowerCase())),
      )
    : sorted

  return (
    <div className="browse-list" data-testid="entity-list">
      <input
        type="search"
        placeholder="Filter entities..."
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        aria-label="Filter entities"
      />
      <ul>
        {visible.map((entity) => (
          <li key={entity.id}>
            <button
              type="button"
              className={entity.id === selectedEntityId ? 'selected' : ''}
              onClick={() => onSelect(entity.id)}
            >
              {displayLabel(entity)}
            </button>
          </li>
        ))}
      </ul>
      {visible.length === 0 && <p className="empty-note">No entities match.</p>}
    </div>
  )
}
