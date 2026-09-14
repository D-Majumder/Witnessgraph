import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { AllShortestPathsResult } from '../api/types'
import { EvidenceIndependencePanel } from './EvidenceIndependencePanel'

function baseResult(overrides: Partial<AllShortestPathsResult>): AllShortestPathsResult {
  return {
    source_entity_id: 'e-a',
    target_entity_id: 'e-d',
    direction: 'out',
    max_depth: 10,
    limit: 10,
    found: true,
    hop_count: 2,
    truncated: false,
    paths: [[]],
    ...overrides,
  }
}

describe('EvidenceIndependencePanel', () => {
  it('renders "not applicable" for a null verdict -- never a default true', () => {
    render(
      <EvidenceIndependencePanel
        result={baseResult({
          evidence_independence: { chains: [], shared_evidence_ids: [], fully_evidence_independent: null },
        })}
      />,
    )
    expect(screen.getByTestId('evidence-fact')).toHaveTextContent('not applicable');
    expect(screen.getByTestId('evidence-fact')).not.toHaveTextContent('yes')
  })

  it('renders the shared-evidence case distinctly from the structural fact, never merged', () => {
    render(
      <EvidenceIndependencePanel
        result={baseResult({
          paths: [[], []],
          evidence_independence: {
            chains: [
              { chain_index: 0, root_evidence_ids: ['ev-1'] },
              { chain_index: 1, root_evidence_ids: ['ev-1'] },
            ],
            shared_evidence_ids: ['ev-1'],
            fully_evidence_independent: false,
          },
        })}
      />,
    )
    expect(screen.getByTestId('structural-fact')).toHaveTextContent('2 structurally distinct')
    const evidenceFact = screen.getByTestId('evidence-fact')
    expect(evidenceFact).toHaveTextContent('evidence-independent: no')
    expect(evidenceFact).toHaveTextContent('ev-1')
    // The two facts must never be collapsed into "therefore independently
    // corroborated" -- assert that exact phrase never appears anywhere.
    expect(document.body.textContent).not.toMatch(/independently corroborated/i)
    expect(document.body.textContent).not.toMatch(/confirms/i)
  })

  it('renders a true verdict without implying epistemic proof', () => {
    render(
      <EvidenceIndependencePanel
        result={baseResult({
          paths: [[], []],
          evidence_independence: {
            chains: [
              { chain_index: 0, root_evidence_ids: ['ev-1'] },
              { chain_index: 1, root_evidence_ids: ['ev-2'] },
            ],
            shared_evidence_ids: [],
            fully_evidence_independent: true,
          },
        })}
      />,
    )
    expect(screen.getByTestId('evidence-fact')).toHaveTextContent('evidence-independent: yes')
    expect(document.body.textContent).not.toMatch(/proves|confirmed|therefore true/i)
  })
})
