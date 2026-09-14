import { useState } from 'react'
import type { Relationship } from '../api/types'

export function RelationshipList({
  relationships,
  selectedRelationshipId,
  onSelect,
}: {
  relationships: Relationship[]
  selectedRelationshipId: string | null
  onSelect: (id: string) => void
}) {
  const [filter, setFilter] = useState('')
  const sorted = [...relationships].sort((a, b) => (a.id < b.id ? -1 : 1))
  const visible = filter
    ? sorted.filter((r) => r.relationship_type.toLowerCase().includes(filter.toLowerCase()))
    : sorted

  return (
    <div className="browse-list" data-testid="relationship-list">
      <input
        type="search"
        placeholder="Filter relationships..."
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        aria-label="Filter relationships"
      />
      <ul>
        {visible.map((rel) => (
          <li key={rel.id}>
            <button
              type="button"
              className={rel.id === selectedRelationshipId ? 'selected' : ''}
              onClick={() => onSelect(rel.id)}
            >
              {rel.source_entity_id} &#8594;[{rel.relationship_type}]&#8594; {rel.target_entity_id}
            </button>
          </li>
        ))}
      </ul>
      {visible.length === 0 && <p className="empty-note">No relationships match.</p>}
    </div>
  )
}
