// The single most identity-defining piece of UI in this project (see
// docs/phase-ui-v1-architecture-design.md §7 and the researcher demo
// script §19 step 6). Renders two facts that must NEVER be merged into
// one sentence and must NEVER read as "therefore independently
// corroborated":
//   A. STRUCTURAL FACT -- how many distinct shortest chains exist.
//   B. EVIDENCE FACT -- whether those chains' root evidence is disjoint,
//      per the engine's own analyze_paths_evidence_overlap. A null
//      verdict (fewer than 2 chains) is rendered as "not applicable",
//      never coerced to true.

import type { AllShortestPathsResult } from '../api/types'

export function EvidenceIndependencePanel({ result }: { result: AllShortestPathsResult }) {
  const overlap = result.evidence_independence

  return (
    <div className="evidence-independence-panel" data-testid="evidence-independence">
      <h4>Structural multiplicity vs. evidence independence</h4>

      <p className="structural-fact" data-testid="structural-fact">
        <strong>Structural fact:</strong> {result.paths.length} structurally distinct shortest
        chain(s) of length {result.hop_count} connect <code>{result.source_entity_id}</code> and{' '}
        <code>{result.target_entity_id}</code>
        {result.truncated ? ' (more may exist beyond the current limit)' : ''}.
      </p>

      <p className="evidence-fact" data-testid="evidence-fact">
        <strong>Evidence fact (a separate question):</strong>{' '}
        {overlap === undefined && 'not resolved for this result.'}
        {overlap?.fully_evidence_independent === null &&
          'not applicable -- fewer than 2 chains were found, so there is nothing to compare.'}
        {overlap?.fully_evidence_independent === true &&
          'evidence-independent: yes -- no root EvidenceItem is cited by more than one chain.'}
        {overlap?.fully_evidence_independent === false && (
          <>
            evidence-independent: no -- {overlap.shared_evidence_ids.length} EvidenceItem(s) are
            cited by more than one chain (
            {overlap.shared_evidence_ids.map((id, i) => (
              <span key={id}>
                {i > 0 ? ', ' : ''}
                <code>{id}</code>
              </span>
            ))}
            ).
          </>
        )}
      </p>

      <p className="independence-disclaimer">
        These are two separate facts, deliberately never merged: structural distinctness does not
        imply evidence independence, and neither one implies the connection is true, important, or
        causal.
      </p>

      {overlap && overlap.chains.length > 0 && (
        <ul className="chain-evidence-list">
          {overlap.chains.map((chain) => (
            <li key={chain.chain_index}>
              Chain {chain.chain_index + 1} root evidence:{' '}
              {chain.root_evidence_ids.length > 0 ? (
                chain.root_evidence_ids.map((id, i) => (
                  <span key={id}>
                    {i > 0 ? ', ' : ''}
                    <code>{id}</code>
                  </span>
                ))
              ) : (
                <em>(none found)</em>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
