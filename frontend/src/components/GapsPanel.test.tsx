import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { GapAnalysisResult, TrackSummary } from '../api/types'
import { GapsPanel } from './GapsPanel'

vi.mock('../api/client', () => ({
  analyzeGaps: vi.fn(),
  trackGaps: vi.fn(),
}))

import { analyzeGaps, trackGaps } from '../api/client'

const result: GapAnalysisResult = {
  refine_source_by_attribute: null,
  findings: [
    {
      absent_source: 'hostA',
      present_source: 'hostB',
      absent_source_refinement: null,
      present_source_refinement: null,
      interval_start: '2026-01-01T00:00:00Z',
      interval_end: '2026-01-01T01:00:00Z',
      corroborating_time_assertion_ids: ['ta-1', 'ta-2'],
      bounding_absent_assertion_ids: ['ta-0', 'ta-3'],
    },
  ],
  excluded_no_time_assertion: 0,
  excluded_no_declared_source: 0,
  excluded_ambiguous_source: 0,
  excluded_unrefined_fallback_with_refined_sibling: 0,
}

function renderPanel() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <GapsPanel />
    </QueryClientProvider>,
  )
}

describe('GapsPanel', () => {
  beforeEach(() => {
    vi.mocked(analyzeGaps).mockReset()
    vi.mocked(trackGaps).mockReset()
  })

  it('never renders findings as "did not happen" -- only "no matching evidence"', async () => {
    vi.mocked(analyzeGaps).mockResolvedValue(result)
    const user = userEvent.setup()
    renderPanel()

    await user.click(screen.getByRole('button', { name: 'Analyze' }))

    const gapsResult = await screen.findByTestId('gaps-result')
    expect(gapsResult).toHaveTextContent('No evidence from hostA')
    // The per-finding rendering itself must never assert absence of the
    // event -- only absence of matching evidence.
    expect(gapsResult.textContent).not.toMatch(/did not happen/i)
    expect(gapsResult.textContent).not.toMatch(/never happened/i)
    // The panel's own caption states the boundary explicitly, as a
    // negation ("never a claim that ... did not happen") -- this is the
    // one legitimate place that exact phrase appears.
    expect(document.body.textContent).toMatch(/never.*a claim that an event did not happen/i)
  })

  it('offers tracking only after an analysis found something to track', async () => {
    vi.mocked(analyzeGaps).mockResolvedValue({ ...result, findings: [] })
    const user = userEvent.setup()
    renderPanel()

    expect(screen.queryByRole('button', { name: 'Track findings' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Analyze' }))
    await waitFor(() => expect(screen.getByTestId('gaps-result')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: 'Track findings' })).not.toBeInTheDocument()
  })

  it('tracking shows the new/already_tracked summary', async () => {
    vi.mocked(analyzeGaps).mockResolvedValue(result)
    const summary: TrackSummary = { new: 1, already_tracked: 0 }
    vi.mocked(trackGaps).mockResolvedValue(summary)
    const user = userEvent.setup()
    renderPanel()

    await user.click(screen.getByRole('button', { name: 'Analyze' }))
    await screen.findByTestId('gaps-result')
    await user.click(screen.getByRole('button', { name: 'Track findings' }))

    expect(await screen.findByText(/1 new, 0 already tracked/)).toBeInTheDocument()
  })
})
