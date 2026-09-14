import type { CaseOverview } from '../api/types'

const VERDICT_LABEL: Record<CaseOverview['manifest_verdict'], string> = {
  MATCH: 'Manifest verified (MATCH)',
  MISMATCH: 'Manifest MISMATCH -- case contents changed since last recorded',
  NOT_COMPARABLE: 'Manifest not comparable (different algorithm version)',
  NO_RECORDED_MANIFEST: 'No recorded manifest yet',
}

export function CaseHeader({ overview }: { overview: CaseOverview }) {
  return (
    <header className="case-header" data-testid="case-header">
      <h1>{overview.case_name}</h1>
      <dl className="case-counts">
        <dt>Evidence</dt>
        <dd>{overview.evidence_count}</dd>
        <dt>Entities</dt>
        <dd>{overview.entity_count}</dd>
        <dt>Relationships</dt>
        <dd>{overview.relationship_count}</dd>
        <dt>Hypotheses</dt>
        <dd>{overview.hypothesis_count}</dd>
        <dt>Tracked findings</dt>
        <dd>{overview.tracked_finding_count}</dd>
        <dt>Tracked contradictions</dt>
        <dd>{overview.tracked_contradiction_count}</dd>
      </dl>
      <span className={`manifest-badge manifest-${overview.manifest_verdict.toLowerCase()}`}>
        {VERDICT_LABEL[overview.manifest_verdict]}
      </span>
    </header>
  )
}
