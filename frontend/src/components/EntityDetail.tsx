import type { Entity } from '../api/types'
import { ProvenanceItem } from './Provenance'

export function EntityDetail({ entity, onClose }: { entity: Entity; onClose: () => void }) {
  return (
    <div className="detail-panel" data-testid="entity-detail">
      <div className="detail-header">
        <h3>Entity</h3>
        <button type="button" onClick={onClose} aria-label="Close">
          &times;
        </button>
      </div>
      <dl className="detail-facts">
        <dt>id</dt>
        <dd>
          <code>{entity.id}</code>
        </dd>
        <dt>entity_type</dt>
        <dd>{entity.entity_type}</dd>
        <dt>identifiers</dt>
        <dd>
          <ul className="identifier-list">
            {Object.entries(entity.identifiers).map(([key, value]) => (
              <li key={key}>
                <code>{key}</code> = {value}
              </li>
            ))}
          </ul>
        </dd>
      </dl>
      <section>
        <h4>Provenance -- derived_from</h4>
        <p className="provenance-caption">
          Every fact about this entity traces back to one of these records; nothing here is
          inferred.
        </p>
        <ul className="provenance-list">
          {entity.derived_from.map((id) => (
            <li key={id}>
              <ProvenanceItem refId={id} />
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}
