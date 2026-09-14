import { useQuery } from '@tanstack/react-query'
import { getRelationship } from '../api/client'
import { EvidenceLineageList } from './Provenance'

export function RelationshipDetail({
  relationshipId,
  onClose,
}: {
  relationshipId: string
  onClose: () => void
}) {
  const query = useQuery({
    queryKey: ['relationship', relationshipId],
    queryFn: () => getRelationship(relationshipId),
  })

  return (
    <div className="detail-panel" data-testid="relationship-detail">
      <div className="detail-header">
        <h3>Relationship</h3>
        <button type="button" onClick={onClose} aria-label="Close">
          &times;
        </button>
      </div>
      {query.isLoading && <p>Loading...</p>}
      {query.isError && <p className="error-text">{(query.error as Error).message}</p>}
      {query.data && (
        <>
          <dl className="detail-facts">
            <dt>id</dt>
            <dd>
              <code>{query.data.id}</code>
            </dd>
            <dt>relationship_type</dt>
            <dd>{query.data.relationship_type}</dd>
            <dt>source -&gt; target</dt>
            <dd>
              <code>{query.data.source_entity_id}</code> &rarr; <code>{query.data.target_entity_id}</code>
            </dd>
            {Object.keys(query.data.attributes).length > 0 && (
              <>
                <dt>attributes</dt>
                <dd>
                  <ul className="identifier-list">
                    {Object.entries(query.data.attributes).map(([key, value]) => (
                      <li key={key}>
                        <code>{key}</code> = {value}
                      </li>
                    ))}
                  </ul>
                </dd>
              </>
            )}
          </dl>
          <section>
            <h4>Provenance -- evidence lineage</h4>
            <p className="provenance-caption">
              This relationship is grounded in the following cited evidence -- a structural,
              provenance fact only, never a claim of causation or responsibility.
            </p>
            <EvidenceLineageList lineage={query.data.evidence_lineage ?? []} />
          </section>
        </>
      )}
    </div>
  )
}
