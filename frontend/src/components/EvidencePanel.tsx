// Evidence browsing: a list of EvidenceItem metadata plus a detail
// disclosure per row. Never exposes raw blob bytes or a filesystem
// path -- only the same content-addressed id/metadata fields every
// other provenance view already shows.

import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { listEvidence } from '../api/client'

export function EvidencePanel() {
  const [filter, setFilter] = useState('')
  const query = useQuery({ queryKey: ['evidence'], queryFn: () => listEvidence() })

  if (query.isLoading) return <p>Loading evidence...</p>
  if (query.isError) return <p className="error-text">{(query.error as Error).message}</p>
  if (!query.data) return null

  const visible = filter
    ? query.data.filter((item) => item.source_adapter.toLowerCase().includes(filter.toLowerCase()))
    : query.data

  return (
    <div className="view-panel" data-testid="evidence-panel">
      <h2>Evidence</h2>
      <p className="provenance-caption">
        Every EvidenceItem ingested into this case, identified by its content hash. This is the
        provenance root -- nothing here is derived from anything else.
      </p>
      <input
        type="search"
        placeholder="Filter by source adapter..."
        value={filter}
        onChange={(event) => setFilter(event.target.value)}
        aria-label="Filter evidence by source adapter"
      />
      {visible.length === 0 && <p className="empty-note">No evidence matches.</p>}
      <table className="evidence-table">
        <thead>
          <tr>
            <th>id</th>
            <th>source_adapter</th>
            <th>source_locator</th>
            <th>collected_at</th>
            <th>raw_size_bytes</th>
          </tr>
        </thead>
        <tbody>
          {visible.map((item) => (
            <tr key={item.id}>
              <td>
                <code>{item.id}</code>
              </td>
              <td>{item.source_adapter}</td>
              <td>{item.source_locator}</td>
              <td>{item.collected_at}</td>
              <td>{item.raw_size_bytes}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
