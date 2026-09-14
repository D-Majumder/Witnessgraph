// Provenance UX: expandable inline disclosure, never a separate page
// (docs/phase-ui-v1-architecture-design.md §8). Two entry points:
// - EvidenceLineageList: renders an already-resolved ResolvedEvidenceRef[]
//   (a Relationship's evidence_lineage, always present from the API).
// - ProvenanceItem: resolves one bare derived_from id on demand (an
//   Entity's own lineage, which the API only resolves lazily via
//   GET /evidence/{id} -- see witnessgraph.service.evidence_service).

import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { resolveEvidence } from '../api/client'
import type { EvidenceItem, NormalizedEvent, ResolvedEvidenceRef } from '../api/types'

function EvidenceItemFacts({ item }: { item: EvidenceItem }) {
  return (
    <dl className="provenance-facts">
      <dt>source_adapter</dt>
      <dd>{item.source_adapter}</dd>
      <dt>source_locator</dt>
      <dd>{item.source_locator}</dd>
      <dt>collected_at</dt>
      <dd>{item.collected_at}</dd>
      <dt>raw_size_bytes</dt>
      <dd>{item.raw_size_bytes}</dd>
    </dl>
  )
}

function NormalizedEventFacts({ event }: { event: NormalizedEvent }) {
  return (
    <dl className="provenance-facts">
      <dt>event_type</dt>
      <dd>{event.event_type}</dd>
      <dt>derived_from</dt>
      <dd>{event.derived_from.join(', ') || '(none)'}</dd>
    </dl>
  )
}

function ResolvedRefBody({ resolved }: { resolved: ResolvedEvidenceRef }) {
  if (resolved.kind === 'evidence_item' && resolved.evidence_item) {
    return (
      <div className="provenance-body">
        <span className="provenance-kind">evidence_item</span>
        <EvidenceItemFacts item={resolved.evidence_item} />
      </div>
    )
  }
  if (resolved.kind === 'normalized_event' && resolved.normalized_event) {
    return (
      <div className="provenance-body">
        <span className="provenance-kind">normalized_event</span>
        <NormalizedEventFacts event={resolved.normalized_event} />
      </div>
    )
  }
  return (
    <div className="provenance-body provenance-not-found">
      Not found in this case -- a dangling reference. Never fabricated to fill the gap.
    </div>
  )
}

export function EvidenceLineageList({ lineage }: { lineage: ResolvedEvidenceRef[] }) {
  if (lineage.length === 0) {
    return <p className="provenance-empty">No derived_from references recorded.</p>
  }
  return (
    <ul className="provenance-list">
      {lineage.map((ref) => (
        <li key={ref.id}>
          <ProvenanceDisclosure id={ref.id} resolved={ref} />
        </li>
      ))}
    </ul>
  )
}

export function ProvenanceItem({ refId }: { refId: string }) {
  return <ProvenanceDisclosure id={refId} />
}

/** One expandable disclosure triangle. When `resolved` is already known
 * (a relationship's own evidence_lineage), it renders immediately with no
 * request; otherwise it resolves `id` on first expansion. */
function ProvenanceDisclosure({ id, resolved }: { id: string; resolved?: ResolvedEvidenceRef }) {
  const [open, setOpen] = useState(false)
  const query = useQuery({
    queryKey: ['evidence', id],
    queryFn: () => resolveEvidence(id),
    enabled: open && resolved === undefined,
  })
  const resolvedRef = resolved ?? query.data

  return (
    <div className="provenance-disclosure">
      <button
        type="button"
        className="provenance-toggle"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        {open ? '▾' : '▸'} <code>{id}</code>
      </button>
      {open &&
        (resolvedRef ? (
          <ResolvedRefBody resolved={resolvedRef} />
        ) : (
          <span className="provenance-loading">Resolving...</span>
        ))}
    </div>
  )
}
